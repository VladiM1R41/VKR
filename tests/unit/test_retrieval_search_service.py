"""Tests for Layer 3 search service orchestration."""

from datetime import datetime, timezone

from jarvis.retrieval.models.search_models import SearchRequest
from jarvis.retrieval.services.intent_classifier import IntentResult
from jarvis.retrieval.services.qdrant_search import SearchResult
from jarvis.retrieval.services.query_autocorrect import AutocorrectResult
from jarvis.retrieval.services.query_preprocessing import QueryContext
from jarvis.retrieval.services.reranking import RerankedResult
from jarvis.retrieval.services.search_service import SearchService


def test_search_service_uses_expansions_corrected_query_and_urgent_cache(monkeypatch) -> None:
    service = SearchService()

    class FakeCache:
        def __init__(self):
            self.set_calls = []

        def get(self, query, filters_hash=""):
            return None

        def set(self, query, filters_hash, result, information_type="daily"):
            self.set_calls.append(
                {
                    "query": query,
                    "filters_hash": filters_hash,
                    "result": result,
                    "information_type": information_type,
                }
            )

    class FakeQdrant:
        def __init__(self):
            self.calls = []

        def search(self, **kwargs):
            self.calls.append(kwargs)
            published_at = datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc)
            return [
                SearchResult(
                    point_id="chunk-1",
                    news_id=101,
                    source_id=7,
                    source_name="RBK",
                    title="Ключевая ставка",
                    text="Ключевая ставка сохранена.",
                    score=0.8,
                    zone="title",
                    topics=["economy"],
                    entities=["ЦБ"],
                    published_at=published_at,
                    trust_score=0.85,
                    content_grade=2,
                    information_type="breaking",
                    snippet_lead="Ключевая ставка осталась неизменной.",
                ),
                SearchResult(
                    point_id="chunk-2",
                    news_id=101,
                    source_id=7,
                    source_name="RBK",
                    title="Ключевая ставка",
                    text="Второй чанк той же статьи.",
                    score=0.7,
                    zone="body",
                    topics=["economy"],
                    entities=["ЦБ"],
                    published_at=published_at,
                    trust_score=0.85,
                    content_grade=2,
                    information_type="breaking",
                    snippet_lead="Ключевая ставка осталась неизменной.",
                ),
            ]

    class FakeReranker:
        def __init__(self):
            self.calls = []

        def rerank(self, query, candidates):
            self.calls.append({"query": query, "candidates": candidates})
            return [
                RerankedResult(result=candidates[0], rerank_score=0.91),
                RerankedResult(result=candidates[1], rerank_score=0.32),
            ]

    class FakeLogger:
        def __init__(self):
            self.calls = []

        def log_search(self, **kwargs):
            self.calls.append(kwargs)

    fake_cache = FakeCache()
    fake_qdrant = FakeQdrant()
    fake_reranker = FakeReranker()
    fake_logger = FakeLogger()

    service._cache = fake_cache
    service._qdrant = fake_qdrant
    service._reranker = fake_reranker
    service._logger = fake_logger
    monkeypatch.setattr(service._rate_limiter, "is_allowed", lambda user_id: True)

    monkeypatch.setattr(
        "jarvis.retrieval.services.search_service.autocorrect_query",
        lambda query: AutocorrectResult(
            original=query,
            corrected="ключевая ставка",
            was_corrected=True,
        ),
    )
    monkeypatch.setattr(
        "jarvis.retrieval.services.search_service.preprocess_query",
        lambda query: QueryContext(
            original=query,
            lemma="ключевая ставка",
            intent=IntentResult(intent="FACTUAL", confidence=0.9, method="rule-based"),
            dense_vector=[0.1, 0.2],
            sparse_indices=[7],
            sparse_values=[0.8],
        ),
    )
    monkeypatch.setattr(
        "jarvis.retrieval.services.search_service.expand_query_with_collocations",
        lambda lemma: ["ставка цб"],
    )
    monkeypatch.setattr(
        "jarvis.retrieval.services.search_service._build_additional_query_vectors",
        lambda expansions: [([0.9], [12], [0.4])],
    )

    response = service.search(SearchRequest(query="клюечвая ставк", limit=5), user_id="user-1")

    assert response.corrected_query == "ключевая ставка"
    assert response.intent == "FACTUAL"
    assert response.total == 1
    assert response.results[0].news_id == 101
    assert response.results[0].snippet.startswith("Ключевая ставка")

    assert fake_qdrant.calls[0]["additional_queries"] == [([0.9], [12], [0.4])]
    assert fake_reranker.calls[0]["query"] == "ключевая ставка"
    assert fake_cache.set_calls[0]["information_type"] == "breaking"
    assert fake_logger.calls[0]["resolved_query"] == "ключевая ставка"
