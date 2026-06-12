"""Monthly spend summary: aggregate AP data, render PDF, email stakeholders."""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from accounting.config import Settings
from accounting.logging_conf import get_logger
from accounting.models import InboundInvoice
from accounting.notifier import Notifier

logger = get_logger(__name__)

_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def build_summary(session: Session, year: int, month: int) -> dict:
    """Aggregate inbound invoices for one month by category."""
    start, end = month_bounds(year, month)
    stmt = select(InboundInvoice).where(
        InboundInvoice.invoice_date >= start,
        InboundInvoice.invoice_date < end,
    )
    invoices = list(session.scalars(stmt))

    by_category: dict[str, dict] = {}
    for inv in invoices:
        entry = by_category.setdefault(inv.category, {"total": 0.0, "count": 0})
        entry["total"] = round(entry["total"] + (inv.amount or 0.0), 2)
        entry["count"] += 1

    return {
        "year": year,
        "month": month,
        "month_label": start.strftime("%B %Y"),
        "invoice_count": len(invoices),
        "total_spend": round(sum(inv.amount or 0.0 for inv in invoices), 2),
        "anomaly_count": sum(1 for inv in invoices if inv.anomaly_flag),
        "by_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1]["total"])),
    }


def generate_report_pdf(summary: dict, settings: Settings) -> str:
    from weasyprint import HTML  # heavy native deps — imported lazily

    html = _env.get_template("monthly_report.html.j2").render(
        company_name=settings.company_name, **summary
    )
    out_dir = Path(settings.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"spend-{summary['year']}-{summary['month']:02d}.pdf"
    HTML(string=html).write_pdf(str(path))
    logger.info("generated monthly report %s", path)
    return str(path)


def send_monthly_report(
    session: Session,
    settings: Settings,
    notifier: Notifier,
    year: int | None = None,
    month: int | None = None,
) -> str:
    """Build, render and email the report. Defaults to the previous month."""
    today = date.today()
    if year is None or month is None:
        year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)

    summary = build_summary(session, year, month)
    pdf_path = generate_report_pdf(summary, settings)
    for recipient in settings.report_recipients.split(","):
        notifier.send(
            to=recipient.strip(),
            subject=f"Monthly spend summary — {summary['month_label']}",
            html_body=_env.get_template("monthly_report.html.j2").render(
                company_name=settings.company_name, **summary
            ),
            attachment=pdf_path,
        )
    logger.info("monthly report for %s emailed to %s", summary["month_label"], settings.report_recipients)
    return pdf_path
