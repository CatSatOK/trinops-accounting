"""AR sending: generate the PDF (if needed), email it, move DRAFT → SENT."""

from jinja2 import Environment, FileSystemLoader, select_autoescape

from accounting.ar.invoice_generator import generate_invoice_pdf
from accounting.config import Settings
from accounting.logging_conf import get_logger
from accounting.models import InvoiceStatus, OutboundInvoice
from accounting.notifier import Notifier

logger = get_logger(__name__)

_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)


def send_invoice(invoice: OutboundInvoice, notifier: Notifier, settings: Settings) -> None:
    """Email the invoice to the client and mark it SENT."""
    if invoice.pdf_path is None:
        invoice.pdf_path = generate_invoice_pdf(invoice, settings)

    template = _env.get_template("invoice_email.html.j2")
    html = template.render(
        company_name=settings.company_name,
        company_email=settings.company_email,
        client_name=invoice.client_name,
        invoice_number=f"INV-{invoice.id:05d}",
        description=invoice.description,
        due_date=invoice.due_date.isoformat(),
    )
    thread_id = notifier.send(
        to=invoice.client_email,
        subject=f"Invoice INV-{invoice.id:05d} from {settings.company_name}",
        html_body=html,
        attachment=invoice.pdf_path,
    )
    invoice.gmail_thread_id = thread_id
    invoice.status = InvoiceStatus.SENT
    logger.info("invoice %d sent to %s", invoice.id, invoice.client_email)
