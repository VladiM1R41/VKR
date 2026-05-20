from __future__ import annotations

from jarvis.generation.models.generation_models import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    ProviderConfig,
)
from jarvis.db.models import News, Source
from jarvis.generation.services.answer_generation_service import (
    AnswerGenerationService,
    GenerationConfig,
)
from jarvis.generation.services.context_assembler import NewsWithContext
from jarvis.generation.services.evaluation_service import (
    GenerationEvaluationScenario,
    GenerationEvaluationService,
)
from jarvis.generation.services.providers.base import LLMProvider
from jarvis.generation.services.rag_modes.graph_rag_light import GraphRAGLightService


class _AsyncFakeProvider(LLMProvider):
    def __init__(self, content: str) -> None:
        super().__init__(ProviderConfig(provider_name="fake", model_name="fake-model"))
        self._content = content

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        return LLMGenerationResponse(
            provider_name="fake",
            model_name="fake-model",
            content=self._content,
            input_tokens=40,
            output_tokens=15,
            latency_ms=7,
        )


def _item(news_id: int, title: str, content: str) -> NewsWithContext:
    return NewsWithContext(
        news_id=news_id,
        source_id=1,
        source_name="ТАСС",
        title=title,
        content=content,
        snippet_lead=content[:80],
        score=0.8,
        rerank_score=0.8,
        personalized_score=0.8,
        topics=["economy"],
        entities=["ЦБ"],
        published_at_str="2026-04-15",
        trust_score=0.9,
        content_grade=2,
        information_type="daily",
        urgency="normal",
        event_cluster_id=None,
    )


def test_graph_rag_merge_unique_news_items() -> None:
    service = GraphRAGLightService()
    merged = service.merge_unique_news_items(
        [_item(1, "A", "one"), _item(2, "B", "two")],
        [_item(2, "B", "two"), _item(3, "C", "three")],
        limit=10,
    )
    assert [item.news_id for item in merged] == [1, 2, 3]


def test_graph_rag_generate_uses_graph_mode(monkeypatch) -> None:
    service = GraphRAGLightService()
    answer_service = AnswerGenerationService(
        provider=_AsyncFakeProvider("Graph answer (ТАСС)."),
        config=GenerationConfig(enable_logging=False),
    )

    monkeypatch.setattr(service, "extract_query_entities", lambda session, query, limit=3: [])
    monkeypatch.setattr(service, "load_related_entities", lambda session, seed_entity_ids, limit=5: [])
    monkeypatch.setattr(service, "load_related_news_context", lambda session, entity_ids, exclude_news_ids, limit=5: [])

    result = service.generate(
        session=None,
        answer_service=answer_service,
        user_query="Что с ЦБ?",
        news_items=[_item(1, "ЦБ повысил ставку", "ЦБ повысил ставку.")],
    )

    assert result.answer.rag_mode == "graph_rag"


def test_graph_rag_related_context_uses_db_metadata() -> None:
    service = GraphRAGLightService()
    news = News(
        id=100,
        source_id=10,
        title="ЦБ повысил ставку",
        content="Банк России сообщил о решении.",
        snippet_lead="Банк России сообщил.",
        content_grade=2,
        information_type="breaking",
        urgency="high",
        event_cluster_id=55,
        extra={"trust_score": 0.1, "information_type": "reference", "urgency": "normal"},
    )
    source = Source(id=10, name="ТАСС", trust_score=0.87)

    class _ScalarRows(list):
        def all(self):
            return list(self)

    class _FakeSession:
        def __init__(self) -> None:
            self.calls = 0

        def scalars(self, stmt):
            self.calls += 1
            if self.calls == 1:
                return _ScalarRows([100])
            if self.calls == 2:
                return _ScalarRows([news])
            if self.calls == 3:
                return _ScalarRows([source])
            return _ScalarRows([])

    items = service.load_related_news_context(
        _FakeSession(),
        entity_ids=[1],
        exclude_news_ids=set(),
        limit=5,
    )

    assert len(items) == 1
    assert items[0].source_name == "ТАСС"
    assert items[0].trust_score == 0.87
    assert items[0].information_type == "breaking"
    assert items[0].urgency == "high"
    assert items[0].event_cluster_id == 55


def test_generation_evaluation_compare() -> None:
    eval_service = GenerationEvaluationService()
    base_result = AnswerGenerationService(
        provider=_AsyncFakeProvider("Base"),
        config=GenerationConfig(enable_logging=False),
    ).generate_answer(
        user_query="Что с ЦБ?",
        news_items=[_item(1, "ЦБ повысил ставку", "ЦБ повысил ставку.")],
    )
    candidate_result = AnswerGenerationService(
        provider=_AsyncFakeProvider("Candidate"),
        config=GenerationConfig(enable_logging=False),
    ).generate_answer(
        user_query="Что с ЦБ?",
        news_items=[_item(1, "ЦБ повысил ставку", "ЦБ повысил ставку.")],
        rag_mode_override="crag",
    )

    comparison = eval_service.compare(
        GenerationEvaluationScenario(mode_name="standard", result=base_result),
        GenerationEvaluationScenario(mode_name="crag", result=candidate_result),
    )

    assert comparison.baseline_mode == "standard"
    assert comparison.candidate_mode == "crag"
