"""Redis Pub/Sub cache invalidation hooks for Layer 3."""

from __future__ import annotations

import json
import logging

from jarvis.core.logging import log_event
from jarvis.retrieval.services.cache import SearchCache


logger = logging.getLogger(__name__)

LAYER_CACHE_INVALIDATION_CHANNELS = ("new_articles_ready", "articles_processed")


def handle_cache_invalidation_message(message: str | bytes | dict) -> int:
    """Invalidate exact search cache from a Layer 1/2 event payload."""
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    if isinstance(message, str):
        payload = json.loads(message)
    else:
        payload = message

    deleted = SearchCache().invalidate_for_layer_event(payload)
    log_event(logger, logging.INFO, "search_cache_invalidated_from_pubsub", deleted=deleted)
    return deleted
