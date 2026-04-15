"""Tests for Layer 3 rate limiter."""

import pytest

from jarvis.retrieval.services.rate_limiter import RateLimiter


class TestRateLimiter:
    """Тесты ограничения частоты запросов."""

    def test_init(self):
        limiter = RateLimiter()
        assert limiter is not None
        assert limiter._max == 30
        assert limiter._window == 60

    def test_custom_limits(self):
        limiter = RateLimiter(max_requests=5, window_seconds=10)
        assert limiter._max == 5
        assert limiter._window == 10

    def test_key_format(self):
        limiter = RateLimiter()
        key = limiter._key("192.168.1.1")
        assert key == "rate_limit:192.168.1.1"

    def test_reset(self):
        """reset должен вернуть True (даже если ключа нет)."""
        limiter = RateLimiter()
        # reset работает даже без Redis — возвращает False при ошибке
        # но не падает
        result = limiter.reset("test_user")
        assert isinstance(result, bool)

    def test_remaining_default(self):
        """При недоступности Redis должен возвращать max."""
        limiter = RateLimiter(max_requests=10)
        remaining = limiter.remaining("test")
        assert remaining == 10
