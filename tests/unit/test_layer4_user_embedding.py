from __future__ import annotations

from datetime import UTC, datetime
import uuid

from jarvis.db.models.user import User
from jarvis.db.models.user_embedding import UserEmbedding
from jarvis.personalization.services.user_embedding_service import (
    UserEmbeddingService,
    _deserialize_float32_vector,
    _serialize_float32_vector,
)


class ScalarRows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class FakeVectorFetcher:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def fetch_dense_vectors(self, point_ids: list[str]) -> dict[str, list[float]]:
        return {point_id: self.vectors[point_id] for point_id in point_ids if point_id in self.vectors}


class FailingVectorFetcher:
    def fetch_dense_vectors(self, point_ids: list[str]) -> dict[str, list[float]]:
        raise RuntimeError("qdrant is unavailable")


class FakeSession:
    def __init__(self) -> None:
        self.users = {
            1: User(id=1, username="alice", settings={}, created_at=datetime.now(UTC)),
        }
        self.user_embeddings: dict[int, UserEmbedding] = {}
        self.interactions = [
            type("InteractionStub", (), {"news_id": 11, "action": "like", "created_at": datetime.now(UTC)})(),
            type("InteractionStub", (), {"news_id": 12, "action": "save", "created_at": datetime.now(UTC)})(),
        ]
        self.chunk_rows = [
            (11, uuid.UUID("00000000-0000-0000-0000-000000000011"), "title"),
            (12, uuid.UUID("00000000-0000-0000-0000-000000000012"), "title"),
        ]
        self.distinct_user_ids = [1]
        self.added = []
        self.committed = False

    def get(self, model, key):
        name = model.__name__
        if name == "User":
            return self.users.get(key)
        if name == "UserEmbedding":
            return self.user_embeddings.get(key)
        return None

    def scalars(self, stmt):
        text = str(stmt)
        if "FROM user_interactions" in text:
            if "DISTINCT" in text:
                return ScalarRows(self.distinct_user_ids)
            return ScalarRows(self.interactions)
        raise AssertionError(text)

    def execute(self, stmt):
        text = str(stmt)
        if "FROM chunks" in text:
            return ScalarRows(self.chunk_rows)
        raise AssertionError(text)

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, UserEmbedding):
            self.user_embeddings[obj.user_id] = obj

    def commit(self):
        self.committed = True


def test_vector_serialization_roundtrip() -> None:
    original = [0.1, -0.25, 0.9]
    payload = _serialize_float32_vector(original)
    restored = _deserialize_float32_vector(payload)
    assert len(restored) == 3
    assert round(restored[0], 5) == 0.1
    assert round(restored[1], 5) == -0.25
    assert round(restored[2], 5) == 0.9


def test_rebuild_user_embedding_creates_centroid() -> None:
    session = FakeSession()
    fetcher = FakeVectorFetcher(
        {
            "00000000-0000-0000-0000-000000000011": [1.0, 0.0],
            "00000000-0000-0000-0000-000000000012": [0.0, 1.0],
        }
    )
    service = UserEmbeddingService(vector_fetcher=fetcher)

    result = service.rebuild_user_embedding(session, 1)

    assert result.updated is True
    assert result.article_count == 2
    vector = service.load_user_embedding(session, 1)
    assert vector is not None
    assert round(vector[0], 5) == round(1.0 / 1.8, 5)
    assert round(vector[1], 5) == round(0.8 / 1.8, 5)
    assert session.committed is True


def test_rebuild_user_embedding_returns_not_updated_when_no_vectors() -> None:
    session = FakeSession()
    service = UserEmbeddingService(vector_fetcher=FakeVectorFetcher({}))

    result = service.rebuild_user_embedding(session, 1)

    assert result.updated is False
    assert result.article_count == 0


def test_rebuild_user_embedding_degrades_when_qdrant_unavailable() -> None:
    session = FakeSession()
    service = UserEmbeddingService(vector_fetcher=FailingVectorFetcher())  # type: ignore[arg-type]

    result = service.rebuild_user_embedding(session, 1)

    assert result.updated is False
    assert result.article_count == 0
    assert session.committed is False


def test_rebuild_recent_user_embeddings_runs_for_active_users() -> None:
    session = FakeSession()
    fetcher = FakeVectorFetcher(
        {
            "00000000-0000-0000-0000-000000000011": [1.0, 0.0],
            "00000000-0000-0000-0000-000000000012": [0.0, 1.0],
        }
    )
    service = UserEmbeddingService(vector_fetcher=fetcher)

    results = service.rebuild_recent_user_embeddings(session, limit_users=10, per_user_limit=10)

    assert len(results) == 1
    assert results[0].updated is True
