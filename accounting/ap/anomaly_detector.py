"""Anomaly flagging via arithmetic rules — no API calls.

Rules:
- duplicate: same vendor + same gross amount already in the DB within 30 days
- missing VAT: total present but no VAT line found
- VAT mismatch: VAT differs from the configured rate by more than tolerance
- date out of range: invoice dated in the future or more than a year old
- extraction incomplete: rules/LLM could not fill every required field
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from accounting.ap.parser import ParsedInvoice
from accounting.config import Settings
from accounting.logging_conf import get_logger
from accounting.models import InboundInvoice

logger = get_logger(__name__)

DUPLICATE_WINDOW_DAYS = 30
VAT_TOLERANCE = 0.02  # 2p rounding slack on the expected VAT amount
MAX_INVOICE_AGE_DAYS = 365


def detect_anomalies(
    parsed: ParsedInvoice,
    session: Session,
    settings: Settings,
    today: date | None = None,
) -> list[str]:
    today = today or date.today()
    flags: list[str] = []

    if not parsed.complete:
        flags.append("extraction incomplete")

    if parsed.amount is not None and parsed.vendor is not None:
        window = today - timedelta(days=DUPLICATE_WINDOW_DAYS)
        stmt = select(InboundInvoice).where(
            InboundInvoice.vendor == parsed.vendor,
            InboundInvoice.amount == parsed.amount,
        )
        for existing in session.scalars(stmt):
            if existing.invoice_date is None or existing.invoice_date >= window:
                flags.append(f"possible duplicate of #{existing.id}")
                break

    if parsed.amount is not None:
        if parsed.vat_amount is None:
            flags.append("missing VAT")
        else:
            net = parsed.amount - parsed.vat_amount
            expected_vat = round(net * settings.vat_rate, 2)
            if abs(parsed.vat_amount - expected_vat) > VAT_TOLERANCE:
                flags.append(
                    f"VAT mismatch (got {parsed.vat_amount:.2f}, expected {expected_vat:.2f})"
                )

    if parsed.invoice_date is not None:
        if parsed.invoice_date > today:
            flags.append("invoice dated in the future")
        elif (today - parsed.invoice_date).days > MAX_INVOICE_AGE_DAYS:
            flags.append("invoice older than a year")

    if flags:
        logger.info("anomalies for %r: %s", parsed.vendor, flags)
    return flags
