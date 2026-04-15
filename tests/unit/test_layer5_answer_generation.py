from __future__ import annotations

from dataclasses import dataclass

from jarvis.generation.models.generation_models import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    ProviderConfig,
)
from jarvis.generation.services.answer_generation_service import (
    AnswerGenerationService,
    GenerationConfig,
)
from jarvis.generation.services.chat_memory_service import ChatMemoryService
from jarvis.generation.services.context_assembler import NewsWithContext
from jarvis.generation.services.providers.base import LLMProvider


class _AsyncFakeProvider(LLMProvider):
    def __init__(self, content: str) -> None:
        super().__init__(ProviderConfig(provider_name="fake", model_name="fake-model"))
        self._content = content

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        return LLMGenerationResponse(
            provider_name="fake",
            model_name="fake-model",
            content=self._content,
            input_tokens=100,
            output_tokens=20,
            latency_ms=5,
        )


class _NeverCalledProvider(_AsyncFakeProvider):
    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        raise AssertionError("Provider should not be called on cache hit")


def _make_news_item(
    *,
    news_id: int,
    source_name: str,
    title: str,
    content: str,
    score: float = 0.9,
    personalized_score: float | None = None,
    event_cluster_id: int | None = None,
) -> NewsWithContext:
    return NewsWithContext(
        news_id=news_id,
        source_id=1,
        source_name=source_name,
        title=title,
        content=content,
        snippet_lead=content[:50],
        score=score,
        rerank_score=score,
        personalized_score=personalized_score,
        topics=["economy"],
        entities=["цб"],
        published_at_str="2026-04-15",
        trust_score=0.9,
        content_grade=2,
        information_type="daily",
        urgency="normal",
        event_cluster_id=event_cluster_id,
    )


def test_generate_answer_works_with_async_provider() -> None:
    service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Ставка выросла (ТАСС)."),
        config=GenerationConfig(enable_logging=False),
    )

    result = service.generate_answer(
        user_query="Что со ставкой?",
        news_items=[
            _make_news_item(
                news_id=101,
                source_name="ТАСС",
                title="ЦБ повысил ставку",
                content="ЦБ повысил ставку на заседании.",
            )
        ],
        intent="FACTUAL",
    )

    assert result.answer_text == "Ставка выросла (ТАСС)."
    assert result.model_name == "fake-model"
    assert result.sources[0].news_id == 101
    assert result.citation_valid is True


def test_generate_digest_logs_real_news_ids(monkeypatch) -> None:
    captured = {}

    def _fake_save_generation_log(entry):
        captured["entry"] = entry

        @dataclass
        class _Result:
            log_id: int = 77

        return _Result()

    monkeypatch.setattr(
        "jarvis.generation.services.answer_generation_service.save_generation_log",
        _fake_save_generation_log,
    )

    service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Дайджест дня (ТАСС)."),
        config=GenerationConfig(enable_logging=True),
    )

    result = service.generate_digest(
        news_items=[
            _make_news_item(
                news_id=501,
                source_name="ТАСС",
                title="Главное событие",
                content="Произошло главное событие дня.",
                personalized_score=0.95,
                event_cluster_id=11,
            )
        ],
        user_id=1,
    )

    assert result.generation_log_id == 77
    assert captured["entry"].documents_used[0]["news_id"] == 501


def test_generate_answer_uses_response_cache(monkeypatch) -> None:
    service = AnswerGenerationService(
        provider=_NeverCalledProvider("unused"),
        config=GenerationConfig(enable_logging=False),
    )

    class _FakeCache:
        def get(self, *, mode, query, document_ids):
            return {
                "answer_text": "Кэшированный ответ",
                "rag_mode": "factual",
                "model_name": "cache-model",
                "confidence": "HIGH",
                "input_tokens": 10,
                "output_tokens": 5,
                "citation_valid": True,
                "groundedness_score": 1.0,
                "has_unsupported_claims": False,
            }

        def set(self, **kwargs):
            raise AssertionError("Cache set should not be called on cache hit")

    service._response_cache = _FakeCache()

    result = service.generate_answer(
        user_query="Что со ставкой?",
        news_items=[
            _make_news_item(
                news_id=101,
                source_name="ТАСС",
                title="ЦБ повысил ставку",
                content="ЦБ повысил ставку на заседании.",
            )
        ],
    )

    assert result.answer_text == "Кэшированный ответ"
    assert result.model_name == "cache-model"
    assert result.latency_ms == 0
