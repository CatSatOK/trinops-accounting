"""AP inbox monitoring: collect supplier invoice attachments (PDF).

Two sources behind one interface:
- SeedInboxSource (DEMO_MODE=true): renders supplier invoices from
  `seed/supplier_invoices.json` into real PDFs, so the pdfplumber parsing
  path downstream is exercised end-to-end without a mailbox.
- GmailInboxSource (DEMO_MODE=false): polls the Gmail API and downloads
  PDF attachments.
"""

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from accounting.config import Settings
from accounting.logging_conf import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class InboundAttachment:
    email_id: str
    sender: str
    subject: str
    pdf_path: str  # attachment saved to disk


class InboxSource(Protocol):
    def fetch_unread(self) -> list[InboundAttachment]: ...
    def mark_processed(self, email_id: str) -> None: ...


class SeedInboxSource:
    """Demo source: renders seed supplier invoices to PDF on first fetch."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path = Path(settings.seed_supplier_file)
        self._processed: set[str] = set()

    def fetch_unread(self) -> list[InboundAttachment]:
        if not self._path.exists():
            logger.warning("seed file %s not found", self._path)
            return []
        records = json.loads(self._path.read_text(encoding="utf-8"))
        attachments = [
            InboundAttachment(
                email_id=r["email_id"],
                sender=r["sender"],
                subject=r["subject"],
                pdf_path=self._render_pdf(r),
            )
            for r in records
            if r["email_id"] not in self._processed
        ]
        logger.info("seed inbox returned %d unread attachment(s)", len(attachments))
        return attachments

    def mark_processed(self, email_id: str) -> None:
        self._processed.add(email_id)

    def _render_pdf(self, record: dict) -> str:
        from datetime import date, timedelta

        from jinja2 import Environment, FileSystemLoader, select_autoescape
        from weasyprint import HTML  # heavy native deps — imported lazily

        env = Environment(
            loader=FileSystemLoader("templates"),
            autoescape=select_autoescape(["html"]),
        )
        # seed dates are day offsets so the demo stays current whenever it runs
        invoice_date = date.today() - timedelta(days=record["invoice"]["days_ago"])
        html = env.get_template("supplier_invoice.html.j2").render(
            invoice_date=invoice_date.isoformat(), **record["invoice"]
        )
        out_dir = Path(self._settings.inbound_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{record['email_id']}.pdf"
        if not path.exists():
            HTML(string=html).write_pdf(str(path))
            logger.info("rendered seed supplier invoice %s", path.name)
        return str(path)


class GmailInboxSource:
    """Real source: Gmail API. Requires OAuth credentials (see README)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = None

    def _client(self):
        if self._service is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_authorized_user_file(
                self._settings.google_token_file,
                scopes=["https://www.googleapis.com/auth/gmail.modify"],
            )
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    def fetch_unread(self) -> list[InboundAttachment]:
        service = self._client()
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=self._settings.gmail_query, maxResults=25)
            .execute()
        )
        attachments: list[InboundAttachment] = []
        for ref in resp.get("messages", []):
            msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            for part in msg["payload"].get("parts", []):
                filename = part.get("filename", "")
                if not filename.lower().endswith(".pdf"):
                    continue
                att_id = part["body"].get("attachmentId")
                if not att_id:
                    continue
                att = (
                    service.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=ref["id"], id=att_id)
                    .execute()
                )
                data = base64.urlsafe_b64decode(att["data"])
                out_dir = Path(self._settings.inbound_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / f"{ref['id']}_{filename}"
                path.write_bytes(data)
                attachments.append(
                    InboundAttachment(
                        email_id=ref["id"],
                        sender=headers.get("from", ""),
                        subject=headers.get("subject", ""),
                        pdf_path=str(path),
                    )
                )
        logger.info("gmail returned %d unread attachment(s)", len(attachments))
        return attachments

    def mark_processed(self, email_id: str) -> None:
        service = self._client()
        service.users().messages().modify(
            userId="me", id=email_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()


def get_inbox_source(settings: Settings) -> InboxSource:
    return SeedInboxSource(settings) if settings.demo_mode else GmailInboxSource(settings)
