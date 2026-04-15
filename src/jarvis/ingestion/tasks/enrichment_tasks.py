"""Celery tasks for deferred HTML enrichment."""

from __future__ import annotations

import asyncio

from celery.exceptions import SoftTimeLimitExceeded

from jarvis.ingestion.services.enrich_source import enrich_source_pending_once
from jarvis.ingestion.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="jarvis.ingestion.enrich_source_pending",
    queue="enrichment_queue",
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def enrich_source_pending_task(self, source_name: str, limit: int = 10) -> dict:
    """Run HTML enrichment for pending articles of one source."""

    try:
        result = asyncio.run(enrich_source_pending_once(source_name=source_name, limit=limit))
        if "enriched_news_ids" not in result:
            return result

        enriched_news_ids = list(result.get("enriched_news_ids") or [])
        compact_result = dict(result)
        compact_result["enriched_count"] = len(enriched_news_ids)
        compact_result["enriched_news_ids_preview"] = enriched_news_ids[:10]
        compact_result.pop("enriched_news_ids", None)
        return compact_result
    except SoftTimeLimitExceeded:
        raise self.retry(countdown=60)
