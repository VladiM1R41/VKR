"""Redis-backed response cache for identical non-chat Layer 5 calls."""

from __future__ import annotations

import hashlib
import json
import logging

from jarvis.core.settings import get_settings


logger = logging.getLogger(__name__)


class ResponseCache:
    """Cache non-chat generation responses by normalized request signature."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            from redis import Redis

            self._redis = Redis.from_url(
                self._settings.redis_url,
                decode_responses=True,
            )
        return self._redis

    @staticmethod
    def _normalize_query(query: str) -> str:
        return " ".join(query.lower().strip().split())

    def _cache_key(
        self,
        *,
        mode: str,
        rag_mode: str = "standard",
        query: str,
        document_ids: list[int],
    ) -> str:
        # rag_mode включён в ключ чтобы standard/crag/self_rag не делили один бакет
        raw = f"{mode}|{rag_mode}|{self._normalize_query(query)}|{','.join(str(doc_id) for doc_id in document_ids)}"
        return f"generation:{hashlib.md5(raw.encode()).hexdigest()}"

    def get(
        self,
        *,
        mode: str,
        rag_mode: str = "standard",
        query: str,
        document_ids: list[int],
    ) -> dict | None:
        if not self._settings.jarvis_rag_enable_cache:
            return None
        try:
            key = self._cache_key(mode=mode, rag_mode=rag_mode, query=query, document_ids=document_ids)
            data = self._get_redis().get(key)
            if not data:
                return None
            return json.loads(data)
        except Exception as exc:
            logger.warning("generation_cache_get_failed: %s", exc)
            return None

    def set(
        self,
        *,
        mode: str,
        rag_mode: str = "standard",
        query: str,
        document_ids: list[int],
        result: dict,
        ttl_seconds: int = 300,
    ) -> None:
        if not self._settings.jarvis_rag_enable_cache:
            return
        try:
            key = self._cache_key(mode=mode, rag_mode=rag_mode, query=query, document_ids=document_ids)
            self._get_redis().setex(key, ttl_seconds, json.dumps(result, default=str))
        except Exception as exc:
            logger.warning("generation_cache_set_failed: %s", exc)

