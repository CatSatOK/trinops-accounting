"""Demo seed for the AR side: load outbound invoices on first start.

Seed records use day offsets (`issued_days_ago`) rather than fixed dates so
the demo always contains a realistic mix of current, overdue and paid
invoices regardless of when it is run.
"""

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from accounting.config import Settings
from accounting.logging_conf import get_logger
from accounting.models import InvoiceStatus, OutboundInvoice, utcnow

logger = get_logger(__name__)


def load_seed_outbound(session: Session, settings: Settings) -> int:
    """Insert seed AR invoices if the table is empty. Returns rows added."""
    if not settings.demo_mode:
        return 0
    if session.scalar(select(OutboundInvoice).limit(1)) is not None:
        return 0

    path = settings.seed_outbound_file
    try:
        records = json.loads(open(path, encoding="utf-8").read())
    except FileNotFoundError:
        logger.warning("seed file %s not found", path)
        return 0

    today = date.today()
    for r in records:
        issued = today - timedelta(days=r["issued_days_ago"])
        due = issued + timedelta(days=settings.payment_terms_days)
        status = InvoiceStatus(r["status"])
        session.add(
            OutboundInvoice(
                client_name=r["client_name"],
                client_email=r["client_email"],
                description=r["description"],
                amount=r["amount"],
                issued_date=issued,
                due_date=due,
                status=status,
                paid_at=utcnow() if status == InvoiceStatus.PAID else None,
            )
        )
    logger.info("seeded %d outbound invoice(s)", len(records))
    return len(records)
