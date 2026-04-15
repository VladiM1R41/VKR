"""Celery tasks for Layer 2 batch analytics."""

from __future__ import annotations

import logging

from jarvis.core.logging import log_event
from jarvis.ingestion.tasks.celery_app import celery_app
from jarvis.processing.services.batch_analytics import (
    update_collocations,
    update_term_vocabulary,
)


logger = logging.getLogger(__name__)


@celery_app.task(
    name="jarvis.processing.update_term_vocabulary",
    queue="processing_queue",
    bind=True,
    soft_time_limit=600,
)
def update_term_vocabulary_task(self) -> dict:
    """Periodic task: rebuild term vocabulary from processed chunks."""
    try:
        result = update_term_vocabulary()
        return result.__dict__
    except Exception as exc:
        log_event(logger, logging.ERROR, "term_vocabulary_task_failed", error=str(exc))
        raise


@celery_app.task(
    name="jarvis.processing.update_collocations",
    queue="processing_queue",
    bind=True,
    soft_time_limit=600,
)
def update_collocations_task(self) -> dict:
    """Periodic task: rebuild collocations from processed chunks."""
    try:
        result = update_collocations()
        return result.__dict__
    except Exception as exc:
        log_event(logger, logging.ERROR, "collocations_task_failed", error=str(exc))
        raise
