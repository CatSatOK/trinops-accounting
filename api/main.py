"""FastAPI app: AR/AP API + static dashboard."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from accounting.config import get_settings
from accounting.database import init_db, session_scope
from accounting.logging_conf import setup_logging
from accounting.scheduler import start_scheduler, stop_scheduler
from accounting.seed_loader import load_seed_outbound
from api.routes.expenses import router as expenses_router
from api.routes.invoices import router as invoices_router
from api.routes.reports import router as reports_router


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
app.include_router(invoices_router)
app.include_router(expenses_router)
app.include_router(reports_router)
app.mount("/", StaticFiles(directory="frontend", html=True), name="dashboard")
