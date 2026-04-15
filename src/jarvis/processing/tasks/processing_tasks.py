"""Celery tasks for Layer 2 processing."""

from __future__ import annotations

import asyncio

from celery.exceptions import SoftTimeLimitExceeded

from jarvis.core.settings import get_settings
from jarvis.ingestion.tasks.celery_app import celery_app
from jarvis.processing.services.process_batch import process_pending_news_batch
from jarvis.processing.services.processing_lock import acquire_processing_lock


async def _run_locked_batch(limit: int) -> dict[str, object]:
    async with acquire_processing_lock() as acquired:
        if not acquired:
            return {
                "status": "locked",
                "selected_count": 0,
                "processed_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "processed_news_ids": [],
                "failed_news_ids": [],
            }

        result = process_pending_news_batch(limit=limit)
        payload = result.to_dict()
        payload["status"] = "completed"
        return payload


@celery_app.task(
    bind=True,
    name="jarvis.processing.process_pending_batch",
    queue="processing_queue",
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def process_pending_news_batch_task(self, limit: int | None = None) -> dict[str, object]:
    """Process one locked batch of pending news for Layer 2."""

    settings = get_settings()
    batch_limit = limit or settings.processing_batch_size
    try:
        return asyncio.run(_run_locked_batch(batch_limit))
    except SoftTimeLimitExceeded:
        raise self.retry(countdown=60)
