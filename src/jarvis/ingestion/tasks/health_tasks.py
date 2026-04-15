"""Monitoring and health-check Celery tasks for Layer 1."""

from __future__ import annotations

from jarvis.ingestion.services.monitoring import run_daily_health_check, run_date_audit
from jarvis.ingestion.tasks.celery_app import celery_app


@celery_app.task(
    name="jarvis.ingestion.audit_dates",
    queue="collector_queue",
)
def audit_dates_task() -> dict:
    """Daily date-audit task for publication timestamps."""

    return run_date_audit()


@celery_app.task(
    name="jarvis.ingestion.daily_health_check",
    queue="collector_queue",
)
def daily_health_check_task() -> dict:
    """Daily heavy health-check and cleanup task."""

    return run_daily_health_check()
