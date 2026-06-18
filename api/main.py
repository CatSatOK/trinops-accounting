"""FastAPI app: AR/AP API + static dashboard."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from accounting.config import get_settings
from accounting.database import init_db, session_scope
from accounting.logging_conf import setup_logging
from accounting.scheduler import start_scheduler, stop_scheduler
from accounting.seed_loader import load_seed_outbound
from api.routes.expenses import router as expenses_router
from api.routes.invoices import router as invoices_router
from api.routes.reports import router as reports_router
from api.auth import require_admin
from api.security import SecurityHeadersMiddleware

# Strict policy. script-src allows the jsdelivr CDN because the dashboard pulls
# Chart.js from there; everything else stays same-origin and un-framed.
CSP = (
    "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    with session_scope() as session:
        load_seed_outbound(session, get_settings())
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Trinops Accounting", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware, csp=CSP)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(invoices_router, dependencies=[Depends(require_admin)])
app.include_router(expenses_router, dependencies=[Depends(require_admin)])
app.include_router(reports_router, dependencies=[Depends(require_admin)])
app.mount("/", StaticFiles(directory="frontend", html=True), name="dashboard")
