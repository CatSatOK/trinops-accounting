"""AR endpoints: list, create draft, send, mark as paid."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from accounting.ar.sender import send_invoice
from accounting.config import get_settings
from accounting.database import session_scope
from accounting.models import InvoiceStatus, OutboundInvoice, utcnow
from accounting.notifier import get_notifier

router = APIRouter(prefix="/invoices", tags=["invoices"])


def db_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_name: str
    client_email: str
    description: str
    amount: float
    issued_date: date
    due_date: date
    status: InvoiceStatus
    pdf_path: str | None
    gmail_thread_id: str | None
    paid_at: datetime | None
    reminder_count: int


class InvoiceCreate(BaseModel):
    client_name: str = Field(min_length=1, max_length=200)
    client_email: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    amount: float = Field(gt=0)
    issued_date: date | None = None
    due_date: date | None = None


@router.get("", response_model=list[InvoiceOut])
def list_invoices(
    status: InvoiceStatus | None = None,
    session: Session = Depends(db_session),
) -> list[OutboundInvoice]:
    stmt = select(OutboundInvoice).order_by(OutboundInvoice.issued_date.desc())
    if status is not None:
        stmt = stmt.where(OutboundInvoice.status == status)
    return list(session.scalars(stmt))


@router.post("", response_model=InvoiceOut, status_code=201)
def create_invoice(
    payload: InvoiceCreate,
    session: Session = Depends(db_session),
) -> OutboundInvoice:
    settings = get_settings()
    issued = payload.issued_date or date.today()
    due = payload.due_date or issued + timedelta(days=settings.payment_terms_days)
    if due < issued:
        raise HTTPException(status_code=422, detail="due_date cannot be before issued_date")
    invoice = OutboundInvoice(
        client_name=payload.client_name,
        client_email=payload.client_email,
        description=payload.description,
        amount=payload.amount,
        issued_date=issued,
        due_date=due,
    )
    session.add(invoice)
    session.flush()
    return invoice


@router.post("/{invoice_id}/send", response_model=InvoiceOut)
def send_invoice_endpoint(
    invoice_id: int,
    session: Session = Depends(db_session),
) -> OutboundInvoice:
    invoice = _get_invoice(session, invoice_id)
    if invoice.status != InvoiceStatus.DRAFT:
        raise HTTPException(
            status_code=409, detail=f"invoice is {invoice.status}, only DRAFT invoices can be sent"
        )
    settings = get_settings()
    send_invoice(invoice, get_notifier(settings), settings)
    return invoice


@router.patch("/{invoice_id}/paid", response_model=InvoiceOut)
def mark_paid(
    invoice_id: int,
    session: Session = Depends(db_session),
) -> OutboundInvoice:
    invoice = _get_invoice(session, invoice_id)
    if invoice.status not in (InvoiceStatus.SENT, InvoiceStatus.OVERDUE):
        raise HTTPException(
            status_code=409,
            detail=f"invoice is {invoice.status}, only SENT or OVERDUE invoices can be marked paid",
        )
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = utcnow()
    return invoice


def _get_invoice(session: Session, invoice_id: int) -> OutboundInvoice:
    invoice = session.get(OutboundInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="invoice not found")
    return invoice
