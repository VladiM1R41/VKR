"""Tests for Layer 3 reranking service."""

import pytest

from jarvis.retrieval.services.qdrant_search import SearchResult
from jarvis.retrieval.services.reranking import (
    RerankingService,
    RerankedResult,
    _load_reranker,
)


class TestRerankerLoad:
    """Тесты загрузки reranker модели."""

    def test_reranker_loads(self):
        """Reranker должен загрузиться (если sentence-transformers установлен)."""
        model = _load_reranker()
        # Может быть None если модель ещё не скачана
        if model is not None:
            assert hasattr(model, "predict")


class TestRerankingService:
    """Тесты сервиса reranking."""

    def test_init(self):
        service = RerankingService()
        assert service is not None

    def test_rerank_returns_results_when_model_unavailable(self, monkeypatch):
        """Если модель недоступна — graceful degradation."""
        monkeypatch.setattr("jarvis.retrieval.services.reranking._load_reranker", lambda: None)
        service = RerankingService()
        candidates = [
            SearchResult(
                point_id="1", news_id=1, source_id=1, source_name="Test",
                title="T", text="T", score=0.8, zone="body",
            ),
            SearchResult(
                point_id="2", news_id=2, source_id=1, source_name="Test",
                title="T", text="T", score=0.6, zone="body",
            ),
        ]
        results = service.rerank("test query", candidates)
        assert len(results) == 2
        # Neutral score when unavailable
        assert results[0].rerank_score == 0.5
        assert results[1].rerank_score == 0.5

    def test_reranked_result_is_dataclass(self):
        result = SearchResult(
            point_id="1", news_id=1, source_id=1, source_name="Test",
            title="T", text="T", score=0.8, zone="body",
        )
        rr = RerankedResult(result=result, rerank_score=0.75)
        assert isinstance(rr, RerankedResult)
        assert rr.rerank_score == 0.75
