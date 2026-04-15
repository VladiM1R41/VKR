"""Global Redis lock for Layer 2 batch processing."""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from redis.asyncio import Redis

from jarvis.core.settings import get_settings


_LOCK_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


@asynccontextmanager
async def acquire_processing_lock():
    """Ensure only one processing batch worker runs at a time in MVP."""

    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    token = uuid4().hex
    acquired = bool(
        await redis.set(
            "lock:process:batch",
            token,
            ex=settings.processing_lock_ttl_seconds,
            nx=True,
        )
    )
    try:
        yield acquired
    finally:
        if acquired:
            try:
                await redis.eval(_LOCK_RELEASE_SCRIPT, 1, "lock:process:batch", token)
            except Exception:
                pass
        await redis.aclose()
