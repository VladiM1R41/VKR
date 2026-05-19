"""Redis cache for Layer 3 search results.

Caches search results to avoid repeated expensive retrievals.
- Exact cache: MD5(normalized_query + filters)
- TTL: 2 min for breaking, 5 min for normal, 30 min for analytics
- Invalidation: on new_articles_ready via Redis Pub/Sub
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings


logger = logging.getLogger(__name__)
_CACHE_VERSION = "l3-v5"


class SearchCache:
    """Redis-based cache for search results."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._redis = None

    def _get_redis(self):
        """Lazy-init Redis connection."""
        if self._redis is None:
            from redis import Redis
            self._redis = Redis.from_url(
                self._settings.redis_url,
                decode_responses=True,
            )
        return self._redis

    def _cache_key(self, query: str, filters_hash: str) -> str:
        """Generate cache key from query and filters."""
        normalized = " ".join(query.lower().strip().split())
        raw = f"{_CACHE_VERSION}|{normalized}|{filters_hash}"
        return f"search:{hashlib.md5(raw.encode()).hexdigest()}"

    def get(self, query: str, filters_hash: str = "") -> Optional[dict]:
        """Get cached search result.

        Args:
            query: User query.
            filters_hash: Hash of filter parameters.

        Returns:
            Cached result dict or None.
        """
        try:
            redis = self._get_redis()
            key = self._cache_key(query, filters_hash)
            data = redis.get(key)
            if data:
                log_event(
                    logger,
                    logging.DEBUG,
                    "cache_hit",
                    query=query[:50],
                )
                return json.loads(data)
        except Exception as exc:
            logger.warning("cache_get_failed: %s", exc)
        return None

    def set(
        self,
        query: str,
        filters_hash: str,
        result: dict,
        information_type: str = "daily",
    ) -> None:
        """Cache search result with TTL based on information type.

        Args:
            query: User query.
            filters_hash: Hash of filter parameters.
            result: Search response dict.
            information_type: breaking/daily/analytics → affects TTL.
        """
        try:
            redis = self._get_redis()
            key = self._cache_key(query, filters_hash)

            # TTL depends on information freshness
            ttl_map = {
                "breaking": 120,       # 2 min
                "daily": 300,          # 5 min
                "analytics": 1800,     # 30 min
                "reference": 3600,     # 1 hour
            }
            ttl = ttl_map.get(information_type, 300)

            redis.setex(key, ttl, json.dumps(result, default=str))
            log_event(
                logger,
                logging.DEBUG,
                "cache_set",
                query=query[:50],
                ttl=ttl,
            )
        except Exception as exc:
            logger.warning("cache_set_failed: %s", exc)

    def invalidate(self, query: str, filters_hash: str = "") -> bool:
        """Invalidate cached result.

        Args:
            query: User query.
            filters_hash: Hash of filter parameters.

        Returns:
            True if key was deleted.
        """
        try:
            redis = self._get_redis()
            key = self._cache_key(query, filters_hash)
            return bool(redis.delete(key))
        except Exception as exc:
            logger.warning("cache_invalidate_failed: %s", exc)
            return False

    def invalidate_by_topic(self, topic: str) -> int:
        """Invalidate all cached results for a topic.

        Uses SCAN to find matching keys (not KEYS — safe for production).

        Args:
            topic: Topic name to invalidate.

        Returns:
            Number of keys deleted.
        """
        try:
            redis = self._get_redis()
            deleted = 0
            cursor = 0
            while True:
                cursor, keys = redis.scan(cursor, match="search:*", count=100)
                if keys:
                    for key in keys:
                        data = redis.get(key)
                        if data:
                            result = json.loads(data)
                            cached_results = result.get("results", [])
                            if any(topic in (entry.get("topics") or []) for entry in cached_results):
                                redis.delete(key)
                                deleted += 1
                if cursor == 0:
                    break
            if deleted > 0:
                log_event(
                    logger,
                    logging.INFO,
                    "cache_invalidate_by_topic",
                    topic=topic,
                    deleted=deleted,
                )
            return deleted
        except Exception as exc:
            logger.warning("cache_invalidate_by_topic_failed: %s", exc)
            return 0

    def invalidate_all(self) -> int:
        """Invalidate all exact search cache entries."""
        try:
            redis = self._get_redis()
            deleted = 0
            cursor = 0
            while True:
                cursor, keys = redis.scan(cursor, match="search:*", count=100)
                if keys:
                    deleted += int(redis.delete(*keys))
                if cursor == 0:
                    break
            if deleted:
                log_event(logger, logging.INFO, "search_cache_invalidate_all", deleted=deleted)
            return deleted
        except Exception as exc:
            logger.warning("cache_invalidate_all_failed: %s", exc)
            return 0

    def invalidate_by_news_ids(self, news_ids: list[int]) -> int:
        """Invalidate cached result sets containing any of the given news ids."""
        target_ids = set(news_ids)
        if not target_ids:
            return 0
        return self._invalidate_by_result_predicate(
            lambda entry: int(entry.get("news_id") or 0) in target_ids,
            event_name="cache_invalidate_by_news_ids",
        )

    def invalidate_by_source_ids(self, source_ids: list[int]) -> int:
        """Invalidate cached result sets containing any of the given source ids."""
        target_ids = set(source_ids)
        if not target_ids:
            return 0
        return self._invalidate_by_result_predicate(
            lambda entry: int(entry.get("source_id") or 0) in target_ids,
            event_name="cache_invalidate_by_source_ids",
        )

    def _invalidate_by_result_predicate(self, predicate, *, event_name: str) -> int:
        try:
            redis = self._get_redis()
            deleted = 0
            cursor = 0
            while True:
                cursor, keys = redis.scan(cursor, match="search:*", count=100)
                for key in keys or []:
                    data = redis.get(key)
                    if not data:
                        continue
                    result = json.loads(data)
                    if any(predicate(entry) for entry in result.get("results", [])):
                        redis.delete(key)
                        deleted += 1
                if cursor == 0:
                    break
            if deleted:
                log_event(logger, logging.INFO, event_name, deleted=deleted)
            return deleted
        except Exception as exc:
            logger.warning("%s_failed: %s", event_name, exc)
            return 0

    def invalidate_for_layer_event(self, event: dict) -> int:
        """Invalidate cache from Layer 1/2 Pub/Sub payloads.

        Accepted keys: news_ids, source_ids, topics. If the event shape is
        unknown, all exact search cache entries are invalidated conservatively.
        """
        deleted = 0
        handled = False
        if event.get("news_ids"):
            handled = True
            deleted += self.invalidate_by_news_ids([int(item) for item in event["news_ids"]])
        if event.get("source_ids"):
            handled = True
            deleted += self.invalidate_by_source_ids([int(item) for item in event["source_ids"]])
        for topic in event.get("topics") or []:
            handled = True
            deleted += self.invalidate_by_topic(str(topic))
        return deleted if handled else self.invalidate_all()
