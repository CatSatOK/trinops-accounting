"""AP endpoints: expense list, anomaly review, category override, chart data."""

from collections.abc import Iterator
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from accounting.config import get_settings
from accounting.database import session_scope
from accounting.models import InboundInvoice

router = APIRouter(prefix="/expenses", tags=["expenses"])


def db_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vendor: str | None
    invoice_number: str | None
    amount: float | None
    vat_amount: float | None
    invoice_date: date | None
    category: str
    anomaly_flag: str | None
    extraction_method: str
    raw_email_id: str
    raw_text_snippet: str | None
    extracted_at: datetime


class CategoryOverride(BaseModel):
    category: str = Field(min_length=1, max_length=100)


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    anomalies_only: bool = False,
    category: str | None = None,
    session: Session = Depends(db_session),
) -> list[InboundInvoice]:
    stmt = select(InboundInvoice).order_by(InboundInvoice.invoice_date.desc())
    if anomalies_only:
        stmt = stmt.where(InboundInvoice.anomaly_flag.is_not(None))
    if category is not None:
        stmt = stmt.where(InboundInvoice.category == category)
    return list(session.scalars(stmt))


@router.get("/summary")
def spend_summary(months: int = 6, session: Session = Depends(db_session)) -> dict:
    """Monthly spend by category for the Chart.js dashboard."""
    today = date.today()
    keys: list[str] = []
    year, month = today.year, today.month
    for _ in range(months):
        keys.append(f"{year}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    keys.reverse()

    categories = sorted(get_settings().category_keywords) + ["Uncategorised"]
    by_category: dict[str, list[float]] = {c: [0.0] * len(keys) for c in categories}
    anomaly_count = 0
    total_spend = 0.0

    for inv in session.scalars(select(InboundInvoice)):
        if inv.anomaly_flag:
            anomaly_count += 1
        if inv.amount is None or inv.invoice_date is None:
            continue
        key = f"{inv.invoice_date.year}-{inv.invoice_date.month:02d}"
        if key not in keys:
            continue
        series = by_category.setdefault(inv.category, [0.0] * len(keys))
        series[keys.index(key)] = round(series[keys.index(key)] + inv.amount, 2)
        total_spend = round(total_spend + inv.amount, 2)

    return {
        "months": keys,
        "by_category": {c: s for c, s in by_category.items() if any(s)},
        "total_spend": total_spend,
        "anomaly_count": anomaly_count,
    }


@router.patch("/{expense_id}/category", response_model=ExpenseOut)
def override_category(
    expense_id: int,
    payload: CategoryOverride,
    session: Session = Depends(db_session),
) -> InboundInvoice:
    expense = _get_expense(session, expense_id)
    expense.category = payload.category
    return expense


@router.patch("/{expense_id}/clear-anomaly", response_model=ExpenseOut)
def clear_anomaly(
    expense_id: int,
    session: Session = Depends(db_session),
) -> InboundInvoice:
    expense = _get_expense(session, expense_id)
    if expense.anomaly_flag is None:
        raise HTTPException(status_code=409, detail="expense has no anomaly flag")
    expense.anomaly_flag = None
    return expense


def _get_expense(session: Session, expense_id: int) -> InboundInvoice:
    expense = session.get(InboundInvoice, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="expense not found")
    return expense
