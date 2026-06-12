"""SQLAlchemy 2.0 models."""

import enum
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class InvoiceStatus(enum.StrEnum):
    DRAFT = "DRAFT"        # created, not yet sent
    SENT = "SENT"          # emailed to the client
    OVERDUE = "OVERDUE"    # past due date, unpaid
    PAID = "PAID"          # payment received


class OutboundInvoice(Base):
    """AR: an invoice we issue to a client."""

    __tablename__ = "outbound_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_name: Mapped[str] = mapped_column(String(200))
    client_email: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(500))
    amount: Mapped[float] = mapped_column(Float)  # net amount; VAT added on the PDF
    issued_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)

    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, native_enum=False, length=20),
        default=InvoiceStatus.DRAFT,
        index=True,
    )
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(128))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    reminders: Mapped[list["ReminderLog"]] = relationship(back_populates="invoice")

    @property
    def reminder_count(self) -> int:
        return len(self.reminders)

    def __repr__(self) -> str:
        return f"<OutboundInvoice {self.id} {self.client_name!r} {self.status}>"


class ReminderLog(Base):
    """AR: one row per reminder email sent for an overdue invoice."""

    __tablename__ = "reminder_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("outbound_invoices.id"), index=True)
    reminder_number: Mapped[int] = mapped_column(Integer)  # 1-based index into REMINDER_DAYS
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    invoice: Mapped[OutboundInvoice] = relationship(back_populates="reminders")

    def __repr__(self) -> str:
        return f"<ReminderLog inv={self.invoice_id} #{self.reminder_number}>"


class InboundInvoice(Base):
    """AP: a supplier invoice extracted from an email attachment."""

    __tablename__ = "inbound_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor: Mapped[str | None] = mapped_column(String(200))
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[float | None] = mapped_column(Float)       # gross total
    vat_amount: Mapped[float | None] = mapped_column(Float)
    invoice_date: Mapped[date | None] = mapped_column(Date)

    category: Mapped[str] = mapped_column(String(100), default="Uncategorised", index=True)
    # Comma-joined anomaly reasons; NULL = clean. Cleared by staff review.
    anomaly_flag: Mapped[str | None] = mapped_column(String(300))
    extraction_method: Mapped[str] = mapped_column(String(20), default="rules")  # rules | llm | failed

    raw_email_id: Mapped[str] = mapped_column(String(128), index=True)
    source_path: Mapped[str | None] = mapped_column(String(500))  # saved attachment PDF
    raw_text_snippet: Mapped[str | None] = mapped_column(Text)    # first chars of extracted text
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def __repr__(self) -> str:
        return f"<InboundInvoice {self.id} {self.vendor!r} {self.amount}>"
