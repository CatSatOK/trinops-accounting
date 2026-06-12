"""Parser tests: rule-based extraction from text and from real PDFs."""

from datetime import date
from pathlib import Path

import pytest

from accounting.ap.parser import extract_text, parse_invoice, parse_text

SAMPLE_TEXT = """Supplier X Cloud Services
INVOICE
Invoice number: SUP-X-1042
Invoice date: 2026-05-14

Description Amount
Cloud hosting subscription - monthly £96.00
Backup storage licence £24.00

Subtotal £120.00
VAT (20%) £24.00
Total due £144.00
"""


def _make_pdf(tmp_path: Path, html: str) -> str:
    from weasyprint import HTML

    path = tmp_path / "invoice.pdf"
    HTML(string=html).write_pdf(str(path))
    return str(path)


class TestParseText:
    def test_extracts_all_fields(self):
        result = parse_text(SAMPLE_TEXT)
        assert result.vendor == "Supplier X Cloud Services"
        assert result.invoice_number == "SUP-X-1042"
        assert result.amount == 144.00
        assert result.vat_amount == 24.00
        assert result.invoice_date == date(2026, 5, 14)
        assert result.method == "rules"
        assert result.complete

    def test_total_due_beats_subtotal(self):
        result = parse_text("Vendor A\nSubtotal £900.00\nTotal due £1,080.00")
        assert result.amount == 1080.00

    def test_thousands_separator(self):
        result = parse_text("Vendor A\nTotal £12,345.67")
        assert result.amount == 12345.67

    def test_vendor_skips_heading_lines(self):
        result = parse_text("INVOICE\nTax statement\nVendor B Ltd\nTotal £10.00")
        assert result.vendor == "Vendor B Ltd"

    def test_missing_vat_is_none(self):
        result = parse_text("Vendor C\nInvoice date: 01/06/2026\nTotal due £265.00")
        assert result.vat_amount is None
        assert result.amount == 265.00

    def test_uk_date_order(self):
        result = parse_text("Vendor D\nInvoice date: 03/04/2026\nTotal £5.00")
        assert result.invoice_date == date(2026, 4, 3)

    def test_incomplete_when_fields_missing(self):
        result = parse_text("just some text with no invoice fields")
        assert not result.complete


class TestParsePdf:
    def test_parses_generated_pdf(self, tmp_path, settings):
        html = f"<html><body><pre>{SAMPLE_TEXT}</pre></body></html>"
        pdf_path = _make_pdf(tmp_path, html)

        text = extract_text(pdf_path)
        assert "SUP-X-1042" in text

        result = parse_invoice(pdf_path, settings)
        assert result.method == "rules"
        assert result.vendor == "Supplier X Cloud Services"
        assert result.amount == 144.00
        assert result.invoice_date == date(2026, 5, 14)

    def test_textless_pdf_fails_without_api_key(self, tmp_path, settings):
        pdf_path = _make_pdf(tmp_path, "<html><body></body></html>")
        result = parse_invoice(pdf_path, settings)
        assert result.method == "failed"
        assert not result.complete


@pytest.mark.parametrize(
    "line,expected",
    [
        ("Invoice number: ABC-123", "ABC-123"),
        ("Invoice no. 4567", "4567"),
        ("Invoice # INV/2026/01", "INV/2026/01"),
        ("Invoice ref: X99", "X99"),
    ],
)
def test_invoice_number_variants(line, expected):
    result = parse_text(f"Vendor E\n{line}\nTotal £1.00")
    assert result.invoice_number == expected
