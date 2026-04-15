"""Celery tasks for source discovery collection."""

from __future__ import annotations

import asyncio

from celery.exceptions import SoftTimeLimitExceeded

from jarvis.ingestion.services.collect_source import collect_source_once
from jarvis.ingestion.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="jarvis.ingestion.collect_source",
    queue="collector_queue",
    autoretry_for=(TimeoutError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def collect_source_task(self, source_name: str) -> dict:
    """Run one source discovery cycle inside Celery."""

    try:
        return asyncio.run(collect_source_once(source_name))
    except SoftTimeLimitExceeded:
        raise self.retry(countdown=60)
