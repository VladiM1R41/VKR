"""Redis Pub/Sub publishers for Layer 1 routing signals."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from redis.asyncio import Redis

from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings


NEW_ARTICLES_READY_CHANNEL = "new_articles_ready"
BREAKING_EVENTS_CHANNEL = "breaking_events"

logger = logging.getLogger(__name__)


def _get_redis() -> Redis:
    settings = get_settings()
    return Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


async def publish_new_articles_ready(source_id: int, news_ids: list[int]) -> str | None:
    """Publish a batch-ready signal for newly inserted articles."""
    if not news_ids:
        return None

    batch_id = str(uuid4())
    payload = {
        "batch_id": batch_id,
        "count": len(news_ids),
        "source_id": source_id,
    }

    redis = _get_redis()
    try:
        await redis.publish(
            NEW_ARTICLES_READY_CHANNEL,
            json.dumps(payload, ensure_ascii=False),
        )
    finally:
        await redis.aclose()

    log_event(
        logger,
        logging.INFO,
        "new_articles_ready_published",
        source_id=source_id,
        batch_id=batch_id,
        count=len(news_ids),
    )
    return batch_id


async def publish_breaking_event(
    *,
    news_id: int,
    event_cluster_id: int | None,
    urgency: str,
) -> None:
    """Publish a fast-path signal for a breaking article."""
    payload = {
        "news_id": news_id,
        "event_cluster_id": event_cluster_id or news_id,
        "urgency": urgency,
    }

    redis = _get_redis()
    try:
        await redis.publish(
            BREAKING_EVENTS_CHANNEL,
            json.dumps(payload, ensure_ascii=False),
        )
    finally:
        await redis.aclose()

    log_event(
        logger,
        logging.INFO,
        "breaking_event_published",
        news_id=news_id,
        event_cluster_id=payload["event_cluster_id"],
        urgency=urgency,
    )
