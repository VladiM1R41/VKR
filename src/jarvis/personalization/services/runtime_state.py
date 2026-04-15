"""Runtime state helpers for production-like Layer 4 flows."""

from __future__ import annotations

from redis import Redis

from jarvis.core.settings import get_settings


class AlertRateLimiter:
    """Redis-backed cooldown for alert delivery candidates."""

    def __init__(self, ttl_seconds: int = 60 * 30) -> None:
        self._settings = get_settings()
        self._ttl_seconds = ttl_seconds
        self._redis: Redis | None = None

    def _get_redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(
                self._settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    @staticmethod
    def _key(user_id: int, alert_type: str, news_id: int) -> str:
        return f"ratelimit:alerts:{user_id}:{alert_type}:{news_id}"

    def is_allowed(self, *, user_id: int, alert_type: str, news_id: int) -> bool:
        """Return whether alert can be emitted now."""
        return not bool(self._get_redis().exists(self._key(user_id, alert_type, news_id)))

    def mark_sent(self, *, user_id: int, alert_type: str, news_id: int) -> None:
        """Store alert cooldown marker."""
        self._get_redis().setex(
            self._key(user_id, alert_type, news_id),
            self._ttl_seconds,
            "1",
        )
