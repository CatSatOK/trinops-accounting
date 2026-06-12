"""APScheduler jobs: AP inbox poll, AR reminder check, monthly report.

- poll_inbox: every POLL_INTERVAL_MINUTES — fetch supplier invoices, parse, store
- reminder_check: every REMINDER_CHECK_HOURS — mark overdue, send due reminders
- monthly_report: 1st of each month at 06:00 — email previous month's summary

Both recurring jobs also run once at startup so the demo shows results
immediately.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from accounting.ap.email_watcher import get_inbox_source
from accounting.ap.pipeline import process_inbox
from accounting.ar.reminder import run_reminder_check
from accounting.config import get_settings
from accounting.database import session_scope
from accounting.logging_conf import get_logger
from accounting.notifier import get_notifier
from accounting.reports.monthly import send_monthly_report

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None
_inbox_source = None  # kept module-level so the seed source remembers processed ids


def poll_inbox() -> None:
    global _inbox_source
    settings = get_settings()
    if _inbox_source is None:
        _inbox_source = get_inbox_source(settings)
    try:
        with session_scope() as session:
            process_inbox(session, settings, _inbox_source)
    except Exception:
        logger.exception("inbox poll failed")


def reminder_check() -> None:
    settings = get_settings()
    notifier = get_notifier(settings)
    try:
        with session_scope() as session:
            run_reminder_check(session, settings, notifier)
    except Exception:
        logger.exception("reminder check failed")


def monthly_report() -> None:
    settings = get_settings()
    notifier = get_notifier(settings)
    try:
        with session_scope() as session:
            send_monthly_report(session, settings, notifier)
    except Exception:
        logger.exception("monthly report failed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    settings = get_settings()
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        poll_inbox,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        id="poll_inbox",
        coalesce=True,
        max_instances=1,
    )
    _scheduler.add_job(
        reminder_check,
        trigger="interval",
        hours=settings.reminder_check_hours,
        id="reminder_check",
        coalesce=True,
        max_instances=1,
    )
    _scheduler.add_job(
        monthly_report,
        trigger=CronTrigger(day=1, hour=6),
        id="monthly_report",
        coalesce=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info(
        "scheduler started: inbox every %d min, reminders every %d h, report monthly",
        settings.poll_interval_minutes,
        settings.reminder_check_hours,
    )
    # process anything already waiting (and the seed data in demo mode)
    poll_inbox()
    reminder_check()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
