"""Extended tests for Layer 3 Qdrant search service."""

from datetime import UTC, datetime
import sys
import types

from jarvis.retrieval.services.qdrant_search import QdrantSearchService


class TestQdrantSearchServiceExtended:
    """Contract tests for hybrid retrieval integration."""

    def test_search_uses_payload_fallbacks_and_additional_queries(self, monkeypatch):
        service = QdrantSearchService()

        class FakeModels:
            class MatchValue:
                def __init__(self, value):
                    self.value = value

            class MatchAny:
                def __init__(self, any):
                    self.any = any

            class Range:
                def __init__(self, gte=None, lte=None):
                    self.gte = gte
                    self.lte = lte

            class DatetimeRange:
                def __init__(self, gte=None, lte=None):
                    self.gte = gte
                    self.lte = lte

            class FieldCondition:
                def __init__(self, key, match=None, range=None):
                    self.key = key
                    self.match = match
                    self.range = range

            class Filter:
                def __init__(self, must):
                    self.must = must

            class SparseVector:
                def __init__(self, indices, values):
                    self.indices = indices
                    self.values = values

            class Prefetch:
                def __init__(self, query, using, limit):
                    self.query = query
                    self.using = using
                    self.limit = limit

            class Fusion:
                RRF = "rrf"

            class FusionQuery:
                def __init__(self, fusion):
                    self.fusion = fusion

        fake_module = types.ModuleType("qdrant_client")
        fake_module.models = FakeModels
        monkeypatch.setitem(sys.modules, "qdrant_client", fake_module)

        class FakeClient:
            def __init__(self):
                self.calls = []

            def query_points(self, **kwargs):
                self.calls.append(kwargs)
                return types.SimpleNamespace(
                    points=[
                        types.SimpleNamespace(
                            id="point-1",
                            score=0.91,
                            payload={
                                "news_id": 77,
                                "source_id": 4,
                                "source_name": "RBC",
                                "text_content": "normalized chunk text",
                                "snippet_lead": "Fallback title",
                                "zone": "body",
                                "topics": ["economy"],
                                "entities": ["CBR"],
                                "published_at": "2026-04-14T12:00:00",
                                "trust_score": 0.8,
                                "content_grade": 2,
                                "information_type": "breaking",
                                "chunk_index": 1,
                                "total_chunks": 3,
                                "url": "https://example.com/news/77",
                            },
                        )
                    ]
                )

        fake_client = FakeClient()
        monkeypatch.setattr(service, "_client", lambda: fake_client)

        date_from = datetime(2026, 4, 14, tzinfo=UTC)
        results = service.search(
            dense_vector=[0.1, 0.2],
            sparse_indices=[1, 2],
            sparse_values=[0.4, 0.6],
            limit=5,
            date_from=date_from,
            topics=["economy"],
            additional_queries=[([0.3, 0.4], [5], [0.9])],
        )

        assert len(fake_client.calls) == 1
        call = fake_client.calls[0]
        assert call["collection_name"] == service._settings.qdrant_collection_alias
        assert len(call["prefetch"]) == 4
        assert len(call["query_filter"].must) == 3
        assert call["query_filter"].must[1].key == "published_at"
        assert call["query_filter"].must[1].range.gte == date_from

        assert len(results) == 1
        assert results[0].title == "Fallback title"
        assert results[0].text == "normalized chunk text"
        assert results[0].information_type == "breaking"
        assert results[0].published_at == datetime.fromisoformat("2026-04-14T12:00:00")
        assert results[0].url == "https://example.com/news/77"

    def test_search_returns_empty_on_qdrant_failure(self, monkeypatch):
        service = QdrantSearchService()

        class FakeModels:
            class MatchValue:
                def __init__(self, value):
                    self.value = value

            class FieldCondition:
                def __init__(self, key, match=None, range=None):
                    self.key = key
                    self.match = match
                    self.range = range

            class Filter:
                def __init__(self, must):
                    self.must = must

            class Prefetch:
                def __init__(self, query, using, limit):
                    self.query = query
                    self.using = using
                    self.limit = limit

            class Fusion:
                RRF = "rrf"

            class FusionQuery:
                def __init__(self, fusion):
                    self.fusion = fusion

        fake_module = types.ModuleType("qdrant_client")
        fake_module.models = FakeModels
        monkeypatch.setitem(sys.modules, "qdrant_client", fake_module)

        class FailingClient:
            def query_points(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(service, "_client", lambda: FailingClient())

        results = service.search(
            dense_vector=[0.1],
            sparse_indices=[],
            sparse_values=[],
        )

        assert results == []
