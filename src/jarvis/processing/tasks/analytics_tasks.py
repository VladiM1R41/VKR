"""Celery tasks for Layer 2 batch analytics."""

from __future__ import annotations

from dataclasses import asdict
import logging

from jarvis.core.logging import log_event
from jarvis.ingestion.tasks.celery_app import celery_app
from jarvis.processing.services.batch_analytics import (
    update_collocations,
    update_term_vocabulary,
)
from jarvis.processing.services.entity_profiles import update_entity_profiles


logger = logging.getLogger(__name__)


@celery_app.task(
    name="jarvis.processing.update_term_vocabulary",
    queue="analytics_queue",
    bind=True,
    soft_time_limit=600,
)
def update_term_vocabulary_task(self) -> dict:
    """Periodic task: rebuild term vocabulary from processed chunks."""
    try:
        result = update_term_vocabulary()
        from jarvis.retrieval.services.query_autocorrect import clear_vocabulary_cache

        clear_vocabulary_cache()
        return asdict(result)
    except Exception as exc:
        log_event(logger, logging.ERROR, "term_vocabulary_task_failed", error=str(exc))
        raise


@celery_app.task(
    name="jarvis.processing.update_collocations",
    queue="analytics_queue",
    bind=True,
    soft_time_limit=600,
)
def update_collocations_task(self) -> dict:
    """Periodic task: rebuild collocations from processed chunks."""
    try:
        result = update_collocations()
        from jarvis.retrieval.services.query_expansion import clear_collocation_cache

        clear_collocation_cache()
        return asdict(result)
    except Exception as exc:
        log_event(logger, logging.ERROR, "collocations_task_failed", error=str(exc))
        raise


@celery_app.task(
    name="jarvis.processing.update_entity_profiles",
    queue="analytics_queue",
    bind=True,
    soft_time_limit=600,
)
def update_entity_profiles_task(self) -> dict:
    """Periodic task: refresh entity trend profiles."""
    try:
        result = update_entity_profiles()
        return asdict(result)
    except Exception as exc:
        log_event(logger, logging.ERROR, "entity_profiles_task_failed", error=str(exc))
        raise
