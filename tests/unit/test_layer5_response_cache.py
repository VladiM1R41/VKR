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


def test_response_cache_separates_prompt_model_provider_versions() -> None:
    cache = ResponseCache()
    fake = _FakeRedis()
    cache._redis = fake

    cache.set(
        mode="factual",
        rag_mode="standard",
        query="Ставка ЦБ",
        document_ids=[1],
        prompt_version="v1",
        provider_key="gigachat",
        model_key="gigachat-max",
        result={"answer": "old"},
    )

    assert cache.get(
        mode="factual",
        rag_mode="standard",
        query="Ставка ЦБ",
        document_ids=[1],
        prompt_version="v1",
        provider_key="gigachat",
        model_key="gigachat-max",
    ) == {"answer": "old"}

    assert cache.get(
        mode="factual",
        rag_mode="standard",
        query="Ставка ЦБ",
        document_ids=[1],
        prompt_version="v2",
        provider_key="gigachat",
        model_key="gigachat-max",
    ) is None
