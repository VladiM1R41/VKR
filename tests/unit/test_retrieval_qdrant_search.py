"""Tests for Layer 3 Qdrant search service."""

import pytest

from jarvis.retrieval.services.qdrant_search import SearchResult, QdrantSearchService


class TestSearchResult:
    """Тесты модели SearchResult."""

    def test_search_result_creation(self):
        result = SearchResult(
            point_id="abc123",
            news_id=42,
            source_id=1,
            source_name="ТАСС",
            title="Test title",
            text="Test text",
            score=0.85,
            zone="title",
        )
        assert result.news_id == 42
        assert result.source_name == "ТАСС"
        assert result.score == 0.85
        assert result.zone == "title"

    def test_search_result_defaults(self):
        result = SearchResult(
            point_id="x",
            news_id=1,
            source_id=1,
            source_name="Test",
            title="T",
            text="T",
            score=0.5,
            zone="body",
        )
        assert result.topics == []
        assert result.entities == []
        assert result.published_at is None
        assert result.trust_score == 0.5
        assert result.content_grade == 6
        assert result.snippet_lead == ""


class TestQdrantSearchService:
    """Тесты QdrantSearchService."""

    def test_init(self):
        service = QdrantSearchService()
        assert service is not None
