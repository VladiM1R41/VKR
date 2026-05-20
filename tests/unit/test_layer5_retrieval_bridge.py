from __future__ import annotations

from datetime import datetime, timezone

from jarvis.generation.services.retrieval_bridge import RetrievalBridge
from jarvis.retrieval.models.search_models import SearchResponse, SearchResult


class _FakeSearchService:
    def search(self, request):
        return SearchResponse(
            query=request.query,
            intent="FACTUAL",
            total=1,
            search_time_ms=12.0,
            results=[
                SearchResult(
                    chunk_id="point-1",
                    news_id=42,
                    source_id=7,
                    source_name="ТАСС",
                    title="Тестовая новость",
                    snippet="Короткий фрагмент",
                    score=0.91,
                    rerank_score=0.82,
                    topics=["economy"],
                    entities=["ЦБ"],
                    published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                    trust_score=0.88,
                    content_grade=2,
                    information_type="breaking",
                    urgency="critical",
                    event_cluster_id=40,
                )
            ],
        )


def test_retrieval_bridge_preserves_layer2_metadata(monkeypatch) -> None:
    captured = {}

    def _fake_enrich_with_db_data(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "jarvis.generation.services.retrieval_bridge.enrich_with_db_data",
        _fake_enrich_with_db_data,
    )

    bridge = RetrievalBridge(search_service=_FakeSearchService())
    bridge.retrieve_news_context(query="ЦБ ставка", limit=1)

    assert captured["trust_map"] == {42: 0.88}
    assert captured["grade_map"] == {42: 2}
    assert captured["info_type_map"] == {42: "breaking"}
    assert captured["urgency_map"] == {42: "critical"}
    assert captured["cluster_map"] == {42: 40}
