"""Tests for Qdrant indexing runtime optimizations."""

from __future__ import annotations

from types import SimpleNamespace
import sys

from jarvis.processing.services.qdrant_index import QdrantIndexer


def test_qdrant_client_is_cached_per_indexer(monkeypatch) -> None:
    created_clients: list[object] = []

    class FakeQdrantClient:
        def __init__(self, *, url: str) -> None:
            self.url = url
            created_clients.append(self)

    monkeypatch.setitem(
        sys.modules,
        "qdrant_client",
        SimpleNamespace(QdrantClient=FakeQdrantClient),
    )

    indexer = QdrantIndexer()

    assert indexer._client() is indexer._client()
    assert len(created_clients) == 1


def test_ensure_collection_checks_existing_collection_once(monkeypatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.get_collections_calls = 0
            self.create_collection_calls = 0

        def get_collections(self):
            self.get_collections_calls += 1
            return SimpleNamespace(
                collections=[SimpleNamespace(name="news_chunks")],
            )

        def create_collection(self, **_kwargs) -> None:
            self.create_collection_calls += 1

    fake_client = FakeClient()
    indexer = QdrantIndexer()
    monkeypatch.setitem(
        sys.modules,
        "qdrant_client",
        SimpleNamespace(models=SimpleNamespace()),
    )
    monkeypatch.setattr(indexer, "_client", lambda: fake_client)

    indexer.ensure_collection()
    indexer.ensure_collection()

    assert fake_client.get_collections_calls == 1
    assert fake_client.create_collection_calls == 0
