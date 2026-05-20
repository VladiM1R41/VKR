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
    def __init__(self, news_ids: list[int] | None = None) -> None:
        self._news_ids = list(news_ids or [])

    def get_seen_news_ids(self, *, user_id: int | None = None, session_id: str | None = None, limit: int = 200) -> list[int]:
        return list(self._news_ids)


class FakeSessionStore(SessionProfileStore):
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def load(self, user_id: int) -> dict:  # type: ignore[override]
        return dict(self._payload)


class ScalarRows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class FakeSession:
    def __init__(self) -> None:
        self.user = User(
            id=1,
            username="alice",
            settings={"diversity_slider": 0.8},
            created_at=datetime.now(UTC),
        )
        self.topic_weights = [
            type("TopicWeight", (), {"topic_id": 1, "weight": 0.9})(),
        ]
        self.entity_weights = [
            type("EntityWeight", (), {"entity_id": 10, "weight": 0.95})(),
        ]
        self.entity_subscriptions = [10]
        self.source_preferences = [
            type("SourcePref", (), {"source_id": 100, "preference": "preferred"})(),
            type("SourcePref", (), {"source_id": 200, "preference": "blocked"})(),
        ]
        self.topics = [type("Topic", (), {"id": 1, "name": "Экономика"})()]
        self.entities = [type("Entity", (), {"id": 10, "name": "ЦБ РФ"})()]
        self.news_quality = [(1, 2, False), (2, 2, False), (3, 2, False)]

    def get(self, model, key):
        if model.__name__ == "User" and key == 1:
            return self.user
        return None

    def scalars(self, stmt):
        text = str(stmt)
        if "FROM user_topic_weights" in text:
            return ScalarRows(self.topic_weights)
        if "FROM user_entity_weights" in text:
            return ScalarRows(self.entity_weights)
        if "FROM user_entity_subscriptions" in text:
            return ScalarRows(self.entity_subscriptions)
        if "FROM user_source_preferences" in text:
            return ScalarRows(self.source_preferences)
        if "FROM topics" in text:
            return ScalarRows(self.topics)
        if "FROM entities" in text:
            return ScalarRows(self.entities)
        raise AssertionError(text)

    def execute(self, stmt):
        text = str(stmt)
        if "FROM news" in text:
            return ScalarRows(self.news_quality)
        raise AssertionError(text)


def test_personalized_ranking_applies_profile_signals() -> None:
    session = FakeSession()
    ranking = PersonalizedRankingService(
        seen_history=FakeSeenHistory(news_ids=[2]),
        session_profile_store=FakeSessionStore(
            {
                "recent_news_ids": [99],
                "recent_topic_ids": [1],
                "recent_entity_ids": [10],
                "last_updated_at": datetime.now(UTC).isoformat(),
            }
        ),
    )
    response = SearchResponse(
        query="цб",
        corrected_query=None,
        intent="FACTUAL",
        total=2,
        search_time_ms=12.0,
        results=[
            SearchResult(
                chunk_id="a",
                news_id=1,
                source_id=100,
                source_name="РБК",
                title="Новость 1",
                snippet="x",
                score=0.6,
                topics=["Экономика"],
                entities=["ЦБ РФ"],
            ),
            SearchResult(
                chunk_id="b",
                news_id=2,
                source_id=200,
                source_name="Плохой источник",
                title="Новость 2",
                snippet="y",
                score=0.75,
                topics=["Экономика"],
                entities=["ЦБ РФ"],
            ),
        ],
    )

    ranked = ranking.rerank(session, 1, response)

    assert ranked.results[0].news_id == 1
    assert "preferred_source: РБК" in ranked.results[0].personalization_reasons
    assert "entity_subscription: ЦБ РФ" in ranked.results[0].personalization_reasons
    assert "session_interest: Экономика" in ranked.results[0].personalization_reasons
    assert "seen_penalty_applied" in ranked.results[1].personalization_reasons


def test_personalized_ranking_respects_blocked_source() -> None:
    session = FakeSession()
    ranking = PersonalizedRankingService(
        seen_history=FakeSeenHistory(),
        session_profile_store=FakeSessionStore(
            {
                "recent_news_ids": [],
                "recent_topic_ids": [],
                "recent_entity_ids": [],
                "last_updated_at": None,
            }
        ),
    )
    response = SearchResponse(
        query="тест",
        corrected_query=None,
        intent="FACTUAL",
        total=2,
        search_time_ms=10.0,
        results=[
            SearchResult(
                chunk_id="ok",
                news_id=1,
                source_id=100,
                source_name="РБК",
                title="ok",
                snippet="ok",
                score=0.61,
                topics=[],
                entities=[],
            ),
            SearchResult(
                chunk_id="bad",
                news_id=2,
                source_id=200,
                source_name="Плохой источник",
                title="bad",
                snippet="bad",
                score=0.95,
                topics=[],
                entities=[],
            ),
        ],
    )

    ranked = ranking.rerank(session, 1, response)
    assert ranked.results[0].source_id == 100
    assert any(reason.startswith("blocked_source:") for reason in ranked.results[1].personalization_reasons)


def test_personalized_ranking_does_not_overtake_strong_relevance_match() -> None:
    session = FakeSession()
    session.source_preferences = [
        type("SourcePref", (), {"source_id": 100, "preference": "neutral"})(),
        type("SourcePref", (), {"source_id": 300, "preference": "preferred"})(),
    ]
    ranking = PersonalizedRankingService(
        seen_history=FakeSeenHistory(),
        session_profile_store=FakeSessionStore(
            {
                "recent_news_ids": [],
                "recent_topic_ids": [1],
                "recent_entity_ids": [10],
                "last_updated_at": datetime.now(UTC).isoformat(),
            }
        ),
    )
    response = SearchResponse(
        query="точный запрос",
        corrected_query=None,
        intent="FACTUAL",
        total=2,
        search_time_ms=10.0,
        results=[
            SearchResult(
                chunk_id="strong",
                news_id=1,
                source_id=100,
                source_name="Нейтральный источник",
                title="Сильный точный результат",
                snippet="strong",
                score=0.92,
                topics=[],
                entities=[],
            ),
            SearchResult(
                chunk_id="personal",
                news_id=3,
                source_id=300,
                source_name="Любимый источник",
                title="Персонально похожий результат",
                snippet="personal",
                score=0.70,
                topics=["Экономика"],
                entities=["ЦБ РФ"],
            ),
        ],
    )

    ranked = ranking.rerank(session, 1, response)

    assert ranked.results[0].news_id == 1
    assert ranked.results[1].news_id == 3
    assert ranked.results[1].personalized_score <= 0.82
