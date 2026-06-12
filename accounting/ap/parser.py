"""Supplier invoice field extraction.

Strategy: pdfplumber text extraction + regex first — covers structured PDFs
with zero API cost. Only when the PDF yields no usable text (scanned or
image-based) AND an Anthropic API key is configured do we fall back to
claude-haiku vision (the cheapest Claude model) for a single extraction call.
"""

import base64
import json
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import dateparser

from accounting.config import Settings
from accounting.logging_conf import get_logger

logger = get_logger(__name__)

REQUIRED_FIELDS = ("vendor", "amount", "invoice_date")

# Text shorter than this after extraction means the PDF is likely scanned
MIN_USABLE_TEXT = 40

_INVOICE_NUMBER_RE = re.compile(
    r"invoice\s*(?:no\.?|number|#|ref(?:erence)?)\s*[:\-]?\s*([A-Za-z0-9][\w/\-]*)",
    re.IGNORECASE,
)
_DATE_LINE_RE = re.compile(
    r"(?:invoice\s+date|date\s+of\s+issue|issued?|date)\s*[:\-]\s*(.+)", re.IGNORECASE
)
_AMOUNT_RE = re.compile(r"[£$€]?\s*([\d,]+\.\d{2})\b")
# Words that mark a line as a heading rather than the vendor name
_NON_VENDOR_WORDS = ("invoice", "statement", "receipt", "tax", "bill")


@dataclass(frozen=True)
class ParsedInvoice:
    vendor: str | None = None
    invoice_number: str | None = None
    amount: float | None = None       # gross total
    vat_amount: float | None = None
    invoice_date: date | None = None
    method: str = "rules"             # rules | llm | failed
    raw_text: str = ""

    @property
    def complete(self) -> bool:
        return all(getattr(self, f) is not None for f in REQUIRED_FIELDS)


def extract_text(pdf_path: str) -> str:
    """Pull text from every page with pdfplumber. Empty for scanned PDFs."""
    import pdfplumber  # heavy import — kept lazy

    try:
        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
    except Exception:
        logger.exception("pdfplumber failed on %s", pdf_path)
        return ""


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ""))


def _find_vendor(lines: list[str]) -> str | None:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(w in stripped.lower() for w in _NON_VENDOR_WORDS):
            continue
        return stripped[:200]
    return None


def _find_date(text: str) -> date | None:
    for match in _DATE_LINE_RE.finditer(text):
        candidate = match.group(1).strip()[:40]
        # dateparser with DATE_ORDER=DMY rejects ISO dates, so handle them first
        iso = re.match(r"(\d{4}-\d{2}-\d{2})", candidate)
        if iso:
            return date.fromisoformat(iso.group(1))
        parsed = dateparser.parse(candidate, settings={"DATE_ORDER": "DMY"})
        if parsed:
            return parsed.date()
    return None


def _find_amounts(lines: list[str]) -> tuple[float | None, float | None]:
    """Return (total, vat). Line-based so 'Subtotal' never wins over 'Total due'."""
    total: float | None = None
    vat: float | None = None
    for line in lines:
        lowered = line.lower()
        match = _AMOUNT_RE.search(line)
        if not match:
            continue
        value = _to_float(match.group(1))
        if "vat" in lowered or "tax" in lowered:
            vat = value
        elif "total" in lowered and "subtotal" not in lowered:
            total = value  # last qualifying 'total' line wins (e.g. 'Total due')
    return total, vat


def parse_text(text: str) -> ParsedInvoice:
    """Rule-based extraction from PDF text. No API calls."""
    lines = text.splitlines()
    number_match = _INVOICE_NUMBER_RE.search(text)
    total, vat = _find_amounts(lines)
    return ParsedInvoice(
        vendor=_find_vendor(lines),
        invoice_number=number_match.group(1) if number_match else None,
        amount=total,
        vat_amount=vat,
        invoice_date=_find_date(text),
        method="rules",
        raw_text=text,
    )


def parse_with_claude(pdf_path: str, settings: Settings) -> ParsedInvoice:
    """Vision fallback for scanned PDFs. One call to the cheapest Claude model."""
    import anthropic

    pdf_b64 = base64.standard_b64encode(Path(pdf_path).read_bytes()).decode()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract these fields from this supplier invoice and reply with"
                            " ONLY a JSON object, no other text:\n"
                            '{"vendor": str|null, "invoice_number": str|null,'
                            ' "amount": float|null (gross total),'
                            ' "vat_amount": float|null,'
                            ' "invoice_date": "YYYY-MM-DD"|null}'
                        ),
                    },
                ],
            }
        ],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    data = json.loads(raw)
    parsed_date = dateparser.parse(data["invoice_date"]) if data.get("invoice_date") else None
    return ParsedInvoice(
        vendor=data.get("vendor"),
        invoice_number=data.get("invoice_number"),
        amount=data.get("amount"),
        vat_amount=data.get("vat_amount"),
        invoice_date=parsed_date.date() if parsed_date else None,
        method="llm",
    )


def parse_invoice(pdf_path: str, settings: Settings) -> ParsedInvoice:
    """pdfplumber + regex first; Claude vision only for scanned PDFs."""
    text = extract_text(pdf_path)
    if len(text) >= MIN_USABLE_TEXT:
        result = parse_text(text)
        logger.info(
            "rules parsed %s: vendor=%r amount=%s date=%s",
            Path(pdf_path).name, result.vendor, result.amount, result.invoice_date,
        )
        return result

    if not settings.anthropic_api_key:
        logger.warning("%s has no extractable text and no API key set", pdf_path)
        return ParsedInvoice(method="failed", raw_text=text)

    logger.info("falling back to %s for scanned PDF %s", settings.claude_model, pdf_path)
    try:
        return parse_with_claude(pdf_path, settings)
    except Exception:
        logger.exception("claude vision fallback failed for %s", pdf_path)
        return replace(ParsedInvoice(raw_text=text), method="failed")
