import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from accounting.config import Settings
from accounting.models import Base

REPO_ROOT = Path(__file__).resolve().parent.parent

# Jinja templates are loaded relative to the repo root
os.chdir(REPO_ROOT)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        demo_mode=True,
        anthropic_api_key="",
        invoice_dir=str(tmp_path / "invoices"),
        inbound_dir=str(tmp_path / "inbound"),
        report_dir=str(tmp_path / "reports"),
        outbox_dir=str(tmp_path / "outbox"),
        database_url=f"sqlite:///{tmp_path}/test.db",
    )


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
