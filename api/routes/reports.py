"""Report endpoints: trigger the monthly spend summary on demand."""

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from accounting.config import get_settings
from accounting.database import session_scope
from accounting.notifier import get_notifier
from accounting.reports.monthly import send_monthly_report

router = APIRouter(prefix="/reports", tags=["reports"])


def db_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


@router.post("/monthly")
def run_monthly_report(
    year: int | None = None,
    month: int | None = None,
    session: Session = Depends(db_session),
) -> dict:
    if (year is None) != (month is None):
        raise HTTPException(status_code=422, detail="supply both year and month, or neither")
    if month is not None and not 1 <= month <= 12:
        raise HTTPException(status_code=422, detail="month must be 1-12")
    settings = get_settings()
    pdf_path = send_monthly_report(session, settings, get_notifier(settings), year, month)
    return {"pdf_path": pdf_path, "recipients": settings.report_recipients}
