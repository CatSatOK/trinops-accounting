"""Reminder tests: overdue detection and escalating reminder schedule."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select

from accounting.ar.reminder import due_reminder_number, mark_overdue, send_due_reminders
from accounting.models import InvoiceStatus, OutboundInvoice, ReminderLog

TODAY = date(2026, 6, 12)


@dataclass
class FakeNotifier:
    sent: list[dict] = field(default_factory=list)

    def send(self, to, subject, html_body, attachment=None):
        self.sent.append({"to": to, "subject": subject})
        return f"fake-thread-{len(self.sent)}"


def _invoice(status: InvoiceStatus, due_days_ago: int, **overrides) -> OutboundInvoice:
    due = TODAY - timedelta(days=due_days_ago)
    defaults = dict(
        client_name="Client X",
        client_email="client.x@example.com",
        description="Test work",
        amount=100.00,
        issued_date=due - timedelta(days=14),
        due_date=due,
        status=status,
    )
    defaults.update(overrides)
    return OutboundInvoice(**defaults)


class TestMarkOverdue:
    def test_sent_past_due_becomes_overdue(self, session):
        invoice = _invoice(InvoiceStatus.SENT, due_days_ago=3)
        session.add(invoice)
        session.flush()
        updated = mark_overdue(session, today=TODAY)
        assert invoice.status == InvoiceStatus.OVERDUE
        assert updated == [invoice]

    def test_sent_not_yet_due_is_untouched(self, session):
        invoice = _invoice(InvoiceStatus.SENT, due_days_ago=-5)  # due in 5 days
        session.add(invoice)
        session.flush()
        mark_overdue(session, today=TODAY)
        assert invoice.status == InvoiceStatus.SENT

    def test_draft_and_paid_are_untouched(self, session):
        draft = _invoice(InvoiceStatus.DRAFT, due_days_ago=10)
        paid = _invoice(InvoiceStatus.PAID, due_days_ago=10)
        session.add_all([draft, paid])
        session.flush()
        mark_overdue(session, today=TODAY)
        assert draft.status == InvoiceStatus.DRAFT
        assert paid.status == InvoiceStatus.PAID


class TestDueReminderNumber:
    def test_below_first_threshold(self, settings):
        invoice = _invoice(InvoiceStatus.OVERDUE, due_days_ago=3)
        assert due_reminder_number(invoice, set(), settings, TODAY) is None

    def test_first_threshold(self, settings):
        invoice = _invoice(InvoiceStatus.OVERDUE, due_days_ago=8)
        assert due_reminder_number(invoice, set(), settings, TODAY) == 1

    def test_skips_already_sent(self, settings):
        invoice = _invoice(InvoiceStatus.OVERDUE, due_days_ago=8)
        assert due_reminder_number(invoice, {1}, settings, TODAY) is None

    def test_escalates_to_highest_unsent(self, settings):
        invoice = _invoice(InvoiceStatus.OVERDUE, due_days_ago=35)
        assert due_reminder_number(invoice, {1}, settings, TODAY) == 3


class TestSendDueReminders:
    def test_sends_and_logs_once(self, session, settings):
        invoice = _invoice(InvoiceStatus.OVERDUE, due_days_ago=10)
        session.add(invoice)
        session.flush()
        notifier = FakeNotifier()

        assert send_due_reminders(session, settings, notifier, today=TODAY) == 1
        assert len(notifier.sent) == 1
        assert "INV-" in notifier.sent[0]["subject"]
        assert session.scalar(select(func.count()).select_from(ReminderLog)) == 1

        # second run on the same day sends nothing
        assert send_due_reminders(session, settings, notifier, today=TODAY) == 0
        assert len(notifier.sent) == 1

    def test_full_check_marks_and_reminds(self, session, settings):
        invoice = _invoice(InvoiceStatus.SENT, due_days_ago=8)
        session.add(invoice)
        session.flush()
        notifier = FakeNotifier()

        # run_reminder_check uses date.today(); call the parts with a fixed date instead
        mark_overdue(session, today=TODAY)
        sent = send_due_reminders(session, settings, notifier, today=TODAY)
        assert invoice.status == InvoiceStatus.OVERDUE
        assert sent == 1

    def test_paid_invoice_gets_no_reminder(self, session, settings):
        invoice = _invoice(InvoiceStatus.PAID, due_days_ago=20)
        session.add(invoice)
        session.flush()
        notifier = FakeNotifier()
        assert send_due_reminders(session, settings, notifier, today=TODAY) == 0
