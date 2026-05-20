from __future__ import annotations

from jarvis.generation.models.generation_models import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    ProviderConfig,
)
from jarvis.generation.services.answer_generation_service import (
    AnswerGenerationService,
    GenerationConfig,
)
from jarvis.generation.services.context_assembler import NewsWithContext
from jarvis.generation.services.providers.base import LLMProvider
from jarvis.generation.services.rag_modes import CRAGService, SelfRAGLightService


class _AsyncFakeProvider(LLMProvider):
    def __init__(self, content: str) -> None:
        super().__init__(ProviderConfig(provider_name="fake", model_name="fake-model"))
        self._content = content

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        return LLMGenerationResponse(
            provider_name="fake",
            model_name="fake-model",
            content=self._content,
            input_tokens=50,
            output_tokens=20,
            latency_ms=5,
        )


def _item(
    *,
    news_id: int,
    title: str,
    content: str,
    source_name: str = "ТАСС",
    trust_score: float = 0.9,
    content_grade: int = 2,
) -> NewsWithContext:
    return NewsWithContext(
        news_id=news_id,
        source_id=1,
        source_name=source_name,
        title=title,
        content=content,
        snippet_lead=content[:80],
        score=0.9,
        rerank_score=0.9,
        personalized_score=0.9,
        topics=["economy"],
        entities=["ставка"],
        published_at_str="2026-04-15",
        trust_score=trust_score,
        content_grade=content_grade,
        information_type="daily",
        urgency="normal",
        event_cluster_id=None,
    )


def test_crag_retries_when_context_is_weak() -> None:
    answer_service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Ответ по улучшенному контексту (ТАСС)."),
        config=GenerationConfig(enable_logging=False),
    )
    crag = CRAGService()

    weak_items = [_item(news_id=1, title="Слабая новость", content="Коротко", trust_score=0.2, content_grade=6)]
    strong_items = [_item(news_id=2, title="ЦБ повысил ставку", content="ЦБ повысил ключевую ставку.", trust_score=0.95, content_grade=1)]

    result = crag.generate(
        answer_service=answer_service,
        user_query="Что со ставкой ЦБ?",
        news_items=weak_items,
        retrieval_fn=lambda query: strong_items,
    )

    assert result.decision.should_retry is True
    assert result.decision.used_retry is True
    assert result.answer.rag_mode == "crag"


def test_self_rag_uses_existing_relevant_context() -> None:
    answer_service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Ответ по текущему контексту (ТАСС)."),
        config=GenerationConfig(enable_logging=False),
    )
    service = SelfRAGLightService()

    items = [_item(news_id=1, title="ЦБ повысил ставку", content="ЦБ повысил ключевую ставку на заседании.")]
    result = service.generate(
        answer_service=answer_service,
        user_query="Что со ставкой ЦБ?",
        news_items=items,
    )

    assert result.decision.retrieve_needed is False
    assert result.decision.used_existing_context is True
    assert result.answer.rag_mode == "self_rag"


def test_self_rag_tokenizes_russian_words() -> None:
    service = SelfRAGLightService()
    items = [
        _item(
            news_id=1,
            title="ЦБ повысил ставку",
            content="Банк России сообщил о решении по ключевой ставке.",
        )
    ]

    assert service.filter_relevant_documents("ставка ЦБ", items) == items


def test_self_rag_triggers_retrieval_for_missing_relevance() -> None:
    answer_service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Ответ после retrieval (ТАСС)."),
        config=GenerationConfig(enable_logging=False),
    )
    service = SelfRAGLightService()

    irrelevant_items = [_item(news_id=1, title="Погода", content="Сегодня солнечно.")]
    relevant_items = [_item(news_id=2, title="Инфляция выросла", content="Инфляция в стране растёт.")]

    result = service.generate(
        answer_service=answer_service,
        user_query="Что с инфляцией?",
        news_items=irrelevant_items,
        retrieval_fn=lambda query: relevant_items,
    )

    assert result.decision.retrieve_needed is True
    assert result.decision.used_retrieval is True
    assert result.answer.rag_mode == "self_rag"
