"""AR PDF invoice generation: Jinja2 template rendered to PDF by WeasyPrint."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from accounting.config import Settings
from accounting.logging_conf import get_logger
from accounting.models import OutboundInvoice

logger = get_logger(__name__)

_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)


def render_invoice_html(invoice: OutboundInvoice, settings: Settings) -> str:
    net = invoice.amount
    vat = round(net * settings.vat_rate, 2)
    template = _env.get_template("outbound_invoice.html.j2")
    return template.render(
        invoice_number=f"INV-{invoice.id:05d}",
        issue_date=invoice.issued_date.isoformat(),
        due_date=invoice.due_date.isoformat(),
        company_name=settings.company_name,
        company_email=settings.company_email,
        company_address=settings.company_address,
        client_name=invoice.client_name,
        client_email=invoice.client_email,
        description=invoice.description,
        net=f"{net:.2f}",
        vat=f"{vat:.2f}",
        vat_pct=f"{settings.vat_rate * 100:.0f}",
        total=f"{net + vat:.2f}",
    )


def generate_invoice_pdf(invoice: OutboundInvoice, settings: Settings) -> str:
    """Render the invoice PDF and return its file path."""
    from weasyprint import HTML  # heavy native deps — imported lazily

    html = render_invoice_html(invoice, settings)
    out_dir = Path(settings.invoice_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"INV-{invoice.id:05d}.pdf"
    HTML(string=html).write_pdf(str(path))
    logger.info("generated invoice %s for %s", path, invoice.client_name)
    return str(path)
