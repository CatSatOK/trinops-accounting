"""AR reminders: detect overdue invoices and send escalating reminder emails.

Runs on a schedule (REMINDER_CHECK_HOURS). Pure date arithmetic — no API calls.

- SENT invoices past their due date become OVERDUE.
- OVERDUE invoices get one reminder per threshold in REMINDER_DAYS
  (default 7, 14, 30 days overdue), each logged in ReminderLog so it is
  never sent twice.
"""

from datetime import date

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from accounting.config import Settings
from accounting.logging_conf import get_logger
from accounting.models import InvoiceStatus, OutboundInvoice, ReminderLog
from accounting.notifier import Notifier

logger = get_logger(__name__)

_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)


def mark_overdue(session: Session, today: date | None = None) -> list[OutboundInvoice]:
    """Move SENT invoices past their due date to OVERDUE. Returns those updated."""
    today = today or date.today()
    stmt = select(OutboundInvoice).where(
        OutboundInvoice.status == InvoiceStatus.SENT,
        OutboundInvoice.due_date < today,
    )
    updated = list(session.scalars(stmt))
    for invoice in updated:
        invoice.status = InvoiceStatus.OVERDUE
        logger.info("invoice %d is now OVERDUE (due %s)", invoice.id, invoice.due_date)
    return updated


def due_reminder_number(
    invoice: OutboundInvoice, sent_numbers: set[int], settings: Settings, today: date
) -> int | None:
    """Highest reminder threshold reached that has not been sent yet, or None."""
    days_overdue = (today - invoice.due_date).days
    due = [
        number
        for number, threshold in enumerate(settings.reminder_days, start=1)
        if days_overdue >= threshold and number not in sent_numbers
    ]
    return max(due) if due else None


def send_due_reminders(
    session: Session, settings: Settings, notifier: Notifier, today: date | None = None
) -> int:
    """Send any reminders that are due. Returns the number sent."""
    today = today or date.today()
    template = _env.get_template("reminder_email.html.j2")
    sent_count = 0

    stmt = select(OutboundInvoice).where(OutboundInvoice.status == InvoiceStatus.OVERDUE)
    for invoice in session.scalars(stmt):
        sent_numbers = {r.reminder_number for r in invoice.reminders}
        number = due_reminder_number(invoice, sent_numbers, settings, today)
        if number is None:
            continue
        days_overdue = (today - invoice.due_date).days
        vat = round(invoice.amount * settings.vat_rate, 2)
        html = template.render(
            company_name=settings.company_name,
            company_email=settings.company_email,
            client_name=invoice.client_name,
            invoice_number=f"INV-{invoice.id:05d}",
            due_date=invoice.due_date.isoformat(),
            days_overdue=days_overdue,
            total=f"{invoice.amount + vat:.2f}",
            reminder_number=number,
            final=number == len(settings.reminder_days),
        )
        notifier.send(
            to=invoice.client_email,
            subject=f"Payment reminder {number}: INV-{invoice.id:05d} is {days_overdue} days overdue",
            html_body=html,
            attachment=invoice.pdf_path,
        )
        # append via the relationship so re-runs in the same session see it
        invoice.reminders.append(ReminderLog(reminder_number=number))
        sent_count += 1
        logger.info("reminder %d sent for invoice %d", number, invoice.id)
    return sent_count


def run_reminder_check(session: Session, settings: Settings, notifier: Notifier) -> None:
    mark_overdue(session)
    send_due_reminders(session, settings, notifier)
