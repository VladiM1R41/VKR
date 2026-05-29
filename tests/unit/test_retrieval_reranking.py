"""Tests for Layer 3 reranking service."""

import pytest

from jarvis.retrieval.services.qdrant_search import SearchResult
from jarvis.retrieval.services.reranking import (
    RerankingService,
    RerankedResult,
    _build_rerank_document,
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
        monkeypatch.setattr("jarvis.retrieval.services.reranking._load_reranker", lambda *args: None)
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

    def test_rerank_can_be_disabled_by_settings(self, monkeypatch):
        class FakeSettings:
            reranker_enabled = False
            reranker_model = "test-model"
            reranker_device = "cpu"
            reranker_max_length = 0
            reranker_max_doc_chars = 0
            reranker_batch_size = 0
            reranker_passage_mode = "best"

        monkeypatch.setattr("jarvis.retrieval.services.reranking.get_settings", lambda: FakeSettings())
        monkeypatch.setattr(
            "jarvis.retrieval.services.reranking._load_reranker",
            lambda *args: (_ for _ in ()).throw(AssertionError("model should not load")),
        )
        service = RerankingService()
        candidates = [
            SearchResult(
                point_id="1", news_id=1, source_id=1, source_name="Test",
                title="T", text="T", score=0.8, zone="body",
            )
        ]

        results = service.rerank("query", candidates)

        assert results[0].rerank_score == 0.5

    def test_rerank_uses_safe_runtime_settings(self, monkeypatch):
        captured = {}

        class FakeSettings:
            reranker_enabled = True
            reranker_model = "test-model"
            reranker_device = "cuda"
            reranker_max_length = 256
            reranker_max_doc_chars = 20
            reranker_batch_size = 4
            reranker_passage_mode = "best"

        class FakeModel:
            def predict(self, pairs, **kwargs):
                captured["pairs"] = pairs
                captured["kwargs"] = kwargs
                return [2.0]

        def fake_load(model, device, max_length):
            captured["load_args"] = (model, device, max_length)
            return FakeModel()

        monkeypatch.setattr("jarvis.retrieval.services.reranking.get_settings", lambda: FakeSettings())
        monkeypatch.setattr(
            "jarvis.retrieval.services.reranking._load_reranker",
            fake_load,
        )
        service = RerankingService()
        candidates = [
            SearchResult(
                point_id="1",
                news_id=1,
                source_id=1,
                source_name="Test",
                title="Relevant title",
                text="x" * 200,
                score=0.8,
                zone="body",
                snippet_lead="Short snippet",
            )
        ]

        results = service.rerank("query", candidates)

        assert captured["load_args"] == ("test-model", "cuda", 256)
        assert captured["kwargs"] == {"show_progress_bar": False, "batch_size": 4}
        assert len(captured["pairs"][0][1]) == 20
        assert results[0].rerank_score > 0.5

    def test_rerank_falls_back_on_cuda_oom(self, monkeypatch):
        class FakeSettings:
            reranker_enabled = True
            reranker_model = "test-model"
            reranker_device = "cuda"
            reranker_max_length = 256
            reranker_max_doc_chars = 100
            reranker_batch_size = 4
            reranker_passage_mode = "best"

        class FakeModel:
            def predict(self, pairs, **kwargs):
                raise RuntimeError("CUDA out of memory")

        monkeypatch.setattr("jarvis.retrieval.services.reranking.get_settings", lambda: FakeSettings())
        monkeypatch.setattr(
            "jarvis.retrieval.services.reranking._load_reranker",
            lambda *args: FakeModel(),
        )
        monkeypatch.setattr("jarvis.retrieval.services.reranking._empty_cuda_cache", lambda: None)
        service = RerankingService()
        candidates = [
            SearchResult(
                point_id="1", news_id=1, source_id=1, source_name="Test",
                title="T", text="T", score=0.8, zone="body",
            )
        ]

        results = service.rerank("query", candidates)

        assert results[0].rerank_score == 0.5

    def test_build_rerank_document_selects_matching_passage(self):
        candidate = SearchResult(
            point_id="1",
            news_id=1,
            source_id=1,
            source_name="Test",
            title="Market overview",
            text=(
                "The first paragraph is unrelated. "
                "Central bank rate decision changed the market outlook. "
                "Another unrelated paragraph follows."
            ),
            score=0.8,
            zone="body",
        )

        document = _build_rerank_document("central bank rate", candidate, max_doc_chars=120)

        assert "Central bank rate decision" in document

    def test_build_rerank_document_can_use_prefix_mode(self):
        candidate = SearchResult(
            point_id="1",
            news_id=1,
            source_id=1,
            source_name="Test",
            title="Market overview",
            text=(
                "The first paragraph is unrelated. "
                "Central bank rate decision changed the market outlook."
            ),
            score=0.8,
            zone="body",
        )

        document = _build_rerank_document(
            "central bank rate",
            candidate,
            max_doc_chars=45,
            passage_mode="prefix",
        )

        assert document.startswith("Market overview")
        assert "Central bank rate decision" not in document
