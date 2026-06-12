"""AP orchestration: attachment → parse → categorise → flag → store."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from accounting.ap.anomaly_detector import detect_anomalies
from accounting.ap.categoriser import categorise
from accounting.ap.email_watcher import InboxSource
from accounting.ap.parser import parse_invoice
from accounting.config import Settings
from accounting.logging_conf import get_logger
from accounting.models import InboundInvoice

logger = get_logger(__name__)


def process_inbox(session: Session, settings: Settings, source: InboxSource) -> int:
    """Process unread supplier invoices. Returns the number stored."""
    stored = 0
    for attachment in source.fetch_unread():
        already = session.scalar(
            select(InboundInvoice).where(InboundInvoice.raw_email_id == attachment.email_id)
        )
        if already is not None:
            source.mark_processed(attachment.email_id)
            continue

        parsed = parse_invoice(attachment.pdf_path, settings)
        category = categorise(parsed.raw_text, parsed.vendor, settings)
        flags = detect_anomalies(parsed, session, settings)

        session.add(
            InboundInvoice(
                vendor=parsed.vendor,
                invoice_number=parsed.invoice_number,
                amount=parsed.amount,
                vat_amount=parsed.vat_amount,
                invoice_date=parsed.invoice_date,
                category=category,
                anomaly_flag=", ".join(flags) if flags else None,
                extraction_method=parsed.method,
                raw_email_id=attachment.email_id,
                source_path=attachment.pdf_path,
                raw_text_snippet=parsed.raw_text[:300] or None,
            )
        )
        session.flush()  # make this row visible to duplicate checks on the next loop
        source.mark_processed(attachment.email_id)
        stored += 1
        logger.info("stored inbound invoice from %r (%s)", parsed.vendor, category)
    return stored
