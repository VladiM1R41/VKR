from __future__ import annotations

from jarvis.generation.services.response_cache import ResponseCache


class _FakeRedis:
    def __init__(self) -> None:
        self.storage = {}

    def get(self, key: str):
        return self.storage.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.storage[key] = value


def test_response_cache_round_trip() -> None:
    cache = ResponseCache()
    fake = _FakeRedis()
    cache._redis = fake

    cache.set(
        mode="factual",
        query="Ставка ЦБ",
        document_ids=[1, 2],
        result={"answer": "ok"},
    )

    result = cache.get(
        mode="factual",
        query="  ставка   цб ",
        document_ids=[1, 2],
    )

    assert result == {"answer": "ok"}

