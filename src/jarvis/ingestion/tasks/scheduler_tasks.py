"""Celery Beat dispatch tasks for Layer 1 scheduling."""

from __future__ import annotations

from jarvis.ingestion.services.scheduler import run_dispatch_due_sources
from jarvis.ingestion.tasks.celery_app import celery_app


@celery_app.task(
    name="jarvis.ingestion.dispatch_due_sources",
    queue="collector_queue",
)
def dispatch_due_sources_task() -> dict:
    """Beat-triggered dispatch of due sources."""

    return run_dispatch_due_sources()

