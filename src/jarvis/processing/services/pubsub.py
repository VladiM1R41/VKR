"""Redis Pub/Sub signals emitted by Layer 2."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any

from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings


logger = logging.getLogger(__name__)

ARTICLES_PROCESSED_CHANNEL = "articles_processed"


def publish_articles_processed(
    *,
    news_ids: list[int],
    chunk_count: int,
    event_cluster_ids: list[int],
) -> bool:
    """Publish a best-effort signal after successful Layer 2 processing."""

    if not news_ids:
        return False

    payload: dict[str, Any] = {
        "type": ARTICLES_PROCESSED_CHANNEL,
        "news_ids": news_ids,
        "chunk_count": chunk_count,
        "event_cluster_ids": sorted(set(event_cluster_ids)),
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.publish(ARTICLES_PROCESSED_CHANNEL, json.dumps(payload, ensure_ascii=False))
        return True
    except Exception as exc:
        log_event(
            logger,
            logging.WARNING,
            "processing_pubsub_publish_failed",
            channel=ARTICLES_PROCESSED_CHANNEL,
            error=str(exc),
        )
        return False
