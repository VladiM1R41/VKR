"""Redis-based locks and pending markers for Layer 1 task orchestration."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from uuid import uuid4

from redis.asyncio import Redis

from jarvis.core.settings import get_settings

logger = logging.getLogger(__name__)

_LOCK_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

_COLLECTION_PENDING_PREFIX = "pending:collect:"
_ENRICHMENT_PENDING_PREFIX = "pending:enrich:"
_ENRICHMENT_RERUN_PREFIX = "pending:enrich_rerun:"


@asynccontextmanager
async def _acquire_lock(key: str, ttl_seconds: int):
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    token = uuid4().hex
    acquired = bool(await redis.set(key, token, ex=ttl_seconds, nx=True))

    try:
        yield acquired
    finally:
        if acquired:
            try:
                await redis.eval(_LOCK_RELEASE_SCRIPT, 1, key, token)
            except Exception as exc:
                logger.warning(
                    "lock_release_failed key=%s error=%s",
                    key,
                    exc,
                    extra={"lock_key": key, "error_message": str(exc)},
                )
        await redis.aclose()


async def _mark_pending(prefix: str, source_id: int, ttl_seconds: int) -> bool:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        return bool(await redis.set(f"{prefix}{source_id}", "1", ex=ttl_seconds, nx=True))
    finally:
        await redis.aclose()


async def _clear_pending(prefix: str, source_id: int) -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        await redis.delete(f"{prefix}{source_id}")
    finally:
        await redis.aclose()


async def _consume_pending(prefix: str, source_id: int) -> bool:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        return bool(await redis.delete(f"{prefix}{source_id}"))
    finally:
        await redis.aclose()


async def _is_locked(key: str) -> bool:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        return bool(await redis.exists(key))
    finally:
        await redis.aclose()


@asynccontextmanager
async def acquire_collection_lock(source_id: int):
    """Acquire and release a per-source distributed lock for discovery."""

    settings = get_settings()
    async with _acquire_lock(f"lock:collect:{source_id}", settings.source_lock_ttl_seconds) as acquired:
        yield acquired


@asynccontextmanager
async def acquire_enrichment_lock(source_id: int):
    """Acquire and release a per-source distributed lock for HTML enrichment."""

    settings = get_settings()
    async with _acquire_lock(f"lock:enrich:{source_id}", settings.source_lock_ttl_seconds) as acquired:
        yield acquired


async def mark_collection_pending(source_id: int, ttl_seconds: int) -> bool:
    """Mark a source as already queued for discovery."""

    return await _mark_pending(_COLLECTION_PENDING_PREFIX, source_id, ttl_seconds)


async def mark_enrichment_pending(source_id: int, ttl_seconds: int) -> bool:
    """Mark a source as already queued for enrichment."""

    return await _mark_pending(_ENRICHMENT_PENDING_PREFIX, source_id, ttl_seconds)


async def clear_collection_pending(source_id: int) -> None:
    """Clear queued discovery marker once task has started or finished."""

    await _clear_pending(_COLLECTION_PENDING_PREFIX, source_id)


async def clear_enrichment_pending(source_id: int) -> None:
    """Clear queued enrichment marker once task has started or finished."""

    await _clear_pending(_ENRICHMENT_PENDING_PREFIX, source_id)


async def request_enrichment_rerun(source_id: int, ttl_seconds: int) -> bool:
    """Mark that one follow-up enrichment cycle is needed for this source."""

    return await _mark_pending(_ENRICHMENT_RERUN_PREFIX, source_id, ttl_seconds)


async def consume_enrichment_rerun(source_id: int) -> bool:
    """Consume and clear a pending follow-up enrichment request."""

    return await _consume_pending(_ENRICHMENT_RERUN_PREFIX, source_id)


async def is_collection_locked(source_id: int) -> bool:
    """Return whether a discovery lock is currently held."""

    return await _is_locked(f"lock:collect:{source_id}")


async def is_enrichment_locked(source_id: int) -> bool:
    """Return whether an enrichment lock is currently held."""

    return await _is_locked(f"lock:enrich:{source_id}")
