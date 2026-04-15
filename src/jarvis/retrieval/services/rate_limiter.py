"""Rate limiting for Layer 3 search.

Prevents abuse by limiting requests per IP/user.
Uses Redis atomic counters with sliding window.
"""

from __future__ import annotations

import logging
import time

from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings


logger = logging.getLogger(__name__)

_DEFAULT_MAX_REQUESTS = 30  # per window
_DEFAULT_WINDOW_SECONDS = 60


class RateLimiter:
    """Token bucket rate limiter using Redis."""

    def __init__(
        self,
        max_requests: int = _DEFAULT_MAX_REQUESTS,
        window_seconds: int = _DEFAULT_WINDOW_SECONDS,
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
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

    def _key(self, identifier: str) -> str:
        return f"rate_limit:{identifier}"

    def is_allowed(self, identifier: str) -> bool:
        """Check if request is allowed.

        Uses atomic INCR + EXPIRE pattern in Redis.

        Args:
            identifier: User identifier (IP, user_id, session).

        Returns:
            True if request is allowed, False if rate limited.
        """
        try:
            redis = self._get_redis()
            key = self._key(identifier)

            # Atomic increment
            count = redis.incr(key)
            if count == 1:
                # First request in window — set expiry
                redis.expire(key, self._window)

            if count > self._max:
                log_event(
                    logger,
                    logging.WARNING,
                    "rate_limit_exceeded",
                    identifier=identifier[:50],
                    count=count,
                    max=self._max,
                )
                return False

            return True

        except Exception as exc:
            # Fail open: allow request if Redis unavailable
            logger.warning("rate_limit_check_failed: %s", exc)
            return True

    def remaining(self, identifier: str) -> int:
        """Get remaining requests in current window."""
        try:
            redis = self._get_redis()
            key = self._key(identifier)
            count = int(redis.get(key) or 0)
            return max(0, self._max - count)
        except Exception:
            return self._max

    def reset(self, identifier: str) -> bool:
        """Reset rate limit for identifier."""
        try:
            redis = self._get_redis()
            key = self._key(identifier)
            return bool(redis.delete(key))
        except Exception:
            return False
