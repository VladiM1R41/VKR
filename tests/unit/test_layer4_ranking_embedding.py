from __future__ import annotations

from datetime import UTC, datetime
import struct
import uuid

from jarvis.db.models.user import User
from jarvis.db.models.user_embedding import UserEmbedding
from jarvis.personalization.services.profile_update_service import SessionProfileStore
from jarvis.personalization.services.ranking_service import PersonalizedRankingService
from jarvis.retrieval.models.search_models import SearchResponse, SearchResult


class FakeSeenHistory:
    def get_seen_news_ids(
        self,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
        limit: int = 200,
    ) -> list[int]:
        return []


class FakeSessionStore(SessionProfileStore):
    def load(self, user_id: int) -> dict:  # type: ignore[override]
        return {
            "recent_news_ids": [],
            "recent_topic_ids": [],
            "recent_entity_ids": [],
            "last_updated_at": datetime.now(UTC).isoformat(),
        }


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


class FakeSession:
    def __init__(self) -> None:
        self.user = User(id=1, username="alice", settings={}, created_at=datetime.now(UTC))
        self.user_embedding = UserEmbedding(
            user_id=1,
            embedding=struct.pack("<2f", 1.0, 0.0),
        )
        self.chunk_rows = [
            (1, uuid.UUID("00000000-0000-0000-0000-000000000001"), "title"),
            (2, uuid.UUID("00000000-0000-0000-0000-000000000002"), "title"),
        ]

    def get(self, model, key):
        if model.__name__ == "User":
            return self.user
        if model.__name__ == "UserEmbedding":
            return self.user_embedding
        return None

    def scalars(self, stmt):
        text = str(stmt)
        if "FROM user_topic_weights" in text:
            return ScalarRows([])
        if "FROM user_entity_weights" in text:
            return ScalarRows([])
        if "FROM user_entity_subscriptions" in text:
            return ScalarRows([])
        if "FROM user_source_preferences" in text:
            return ScalarRows([])
        if "FROM topics" in text:
            return ScalarRows([])
        if "FROM entities" in text:
            return ScalarRows([])
        raise AssertionError(text)

    def execute(self, stmt):
        text = str(stmt)
        if "FROM chunks" in text:
            return ScalarRows(self.chunk_rows)
        raise AssertionError(text)


def test_personalized_ranking_uses_user_embedding_signal() -> None:
    session = FakeSession()
    ranking = PersonalizedRankingService(
        seen_history=FakeSeenHistory(),
        session_profile_store=FakeSessionStore(),
        vector_fetcher=FakeVectorFetcher(
            {
                "00000000-0000-0000-0000-000000000001": [1.0, 0.0],
                "00000000-0000-0000-0000-000000000002": [0.0, 1.0],
            }
        ),
    )
    response = SearchResponse(
        query="test",
        corrected_query=None,
        intent="FACTUAL",
        total=2,
        search_time_ms=10.0,
        results=[
            SearchResult(
                chunk_id="a",
                news_id=1,
                source_id=300,
                source_name="A",
                title="A",
                snippet="A",
                score=0.7,
                topics=[],
                entities=[],
            ),
            SearchResult(
                chunk_id="b",
                news_id=2,
                source_id=301,
                source_name="B",
                title="B",
                snippet="B",
                score=0.7,
                topics=[],
                entities=[],
            ),
        ],
    )

    ranked = ranking.rerank(session, 1, response)

    assert ranked.results[0].news_id == 1
    assert "embedding_match" in ranked.results[0].personalization_reasons
