"""Application settings.

Every company-specific or environment-specific value lives in `.env`
(see `.env.example`). Nothing client-identifying is hardcoded.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    demo_mode: bool = True

    database_url: str = "sqlite:///./data/accounting.db"

    # AP inbox poll + AR reminder check intervals
    poll_interval_minutes: int = 10
    reminder_check_hours: int = 24

    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"

    google_credentials_file: str = "credentials.json"
    google_token_file: str = "token.json"
    gmail_query: str = "is:unread has:attachment label:supplier-invoices"

    company_name: str = "Company A"
    company_email: str = "accounts@example.com"
    company_address: str = "1 Example Street, Example Town, EX1 2MP"
    vat_rate: float = 0.20

    # AR rules
    payment_terms_days: int = 14
    # Days overdue at which reminder emails are sent
    reminder_days: list[int] = [7, 14, 30]

    # Monthly report recipients (comma-separated)
    report_recipients: str = "finance@example.com"

    invoice_dir: str = "data/invoices"      # generated AR invoice PDFs
    inbound_dir: str = "data/inbound"       # saved AP attachments
    report_dir: str = "data/reports"        # monthly summary PDFs
    outbox_dir: str = "data/outbox"
    seed_outbound_file: str = "seed/outbound_invoices.json"
    seed_supplier_file: str = "seed/supplier_invoices.json"

    # Keyword rules for AP spend categorisation. Override with a JSON object
    # in the env var CATEGORY_KEYWORDS, e.g. {"Travel": ["fuel", "hotel"]}
    category_keywords: dict[str, list[str]] = {
        "Travel": ["travel", "fuel", "mileage", "hotel", "flight", "train", "taxi", "parking"],
        "Materials": ["materials", "supplies", "parts", "timber", "steel", "cement", "fixings"],
        "Software": ["software", "subscription", "licence", "license", "saas", "hosting", "cloud"],
        "Professional Services": ["consulting", "consultancy", "legal", "accounting", "audit", "training"],
        "Utilities": ["electricity", "gas", "water", "broadband", "internet", "phone", "telecom"],
        "Equipment": ["equipment", "machinery", "tools", "hardware", "laptop", "printer"],
    }

    def ensure_dirs(self) -> None:
        for d in (self.invoice_dir, self.inbound_dir, self.report_dir, self.outbox_dir):
            Path(d).mkdir(parents=True, exist_ok=True)
        db_path = self.database_url.removeprefix("sqlite:///")
        if db_path != self.database_url:  # only for sqlite URLs
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
