from __future__ import annotations

from datetime import UTC, datetime

from jarvis.db.models.news import News
from jarvis.db.models.user import User
from jarvis.db.models.user_entity_weight import UserEntityWeight
from jarvis.db.models.user_source_preference import UserSourcePreference
from jarvis.db.models.user_topic_weight import UserTopicWeight
from jarvis.personalization.services.profile_update_service import (
    ProfileUpdateService,
    SessionProfileStore,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value


class FakeSessionProfileStore(SessionProfileStore):
    def __init__(self) -> None:
        super().__init__(ttl_seconds=60)
        self.fake = FakeRedis()

    def _get_redis(self):  # type: ignore[override]
        return self.fake


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class FakeSession:
    def __init__(self) -> None:
        self.users = {
            1: User(id=1, username="alice", settings={}, created_at=datetime.now(UTC)),
        }
        self.news = {
            2: News(id=2, source_id=5, title="x", canonical_url="u", published_at=datetime.now(UTC)),
        }
        self.interactions = {
            10: type(
                "InteractionStub",
                (),
                {
                    "id": 10,
                    "user_id": 1,
                    "news_id": 2,
                    "action": "like",
                    "dwell_time_sec": None,
                },
            )()
        }
        self.topic_weights: dict[tuple[int, int], UserTopicWeight] = {}
        self.entity_weights: dict[tuple[int, int], UserEntityWeight] = {}
        self.source_preferences: dict[tuple[int, int], UserSourcePreference] = {}
        self.topic_ids = [101, 102]
        self.entity_ids = [201]
        self.added = []
        self.committed = False

    def get(self, model, key):
        name = model.__name__
        if name == "UserInteraction":
            return self.interactions.get(key)
        if name == "User":
            return self.users.get(key)
        if name == "News":
            return self.news.get(key)
        if name == "UserTopicWeight":
            return self.topic_weights.get((key["user_id"], key["topic_id"]))
        if name == "UserEntityWeight":
            return self.entity_weights.get((key["user_id"], key["entity_id"]))
        if name == "UserSourcePreference":
            return self.source_preferences.get((key["user_id"], key["source_id"]))
        return None

    def scalars(self, stmt):
        text = str(stmt)
        if "news_topics.topic_id" in text:
            return FakeScalarResult(self.topic_ids)
        if "news_entities.entity_id" in text:
            return FakeScalarResult(self.entity_ids)
        raise AssertionError(text)

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, UserTopicWeight):
            self.topic_weights[(obj.user_id, obj.topic_id)] = obj
        elif isinstance(obj, UserEntityWeight):
            self.entity_weights[(obj.user_id, obj.entity_id)] = obj
        elif isinstance(obj, UserSourcePreference):
            self.source_preferences[(obj.user_id, obj.source_id)] = obj

    def commit(self):
        self.committed = True


def test_apply_signal_moves_weight_towards_signal_target() -> None:
    service = ProfileUpdateService(session_store=FakeSessionProfileStore(), alpha=0.25)
    assert service._apply_signal(0.5, 1.0) == 0.625
    assert service._apply_signal(0.5, -1.0) == 0.375


def test_update_from_interaction_updates_weights_and_session_profile() -> None:
    session = FakeSession()
    store = FakeSessionProfileStore()
    service = ProfileUpdateService(session_store=store, alpha=0.25)

    result = service.update_from_interaction(session, 10)

    assert result.user_id == 1
    assert result.news_id == 2
    assert result.signal == 1.0
    assert result.updated_topics == 2
    assert result.updated_entities == 1
    assert session.topic_weights[(1, 101)].weight == 0.625
    assert session.entity_weights[(1, 201)].weight == 0.625
    assert session.source_preferences[(1, 5)].preference == "neutral"
    assert session.users[1].settings["source_affinity_scores"]["5"] == 0.625
    assert service.get_session_profile(1)["recent_news_ids"] == [2]
    assert service.get_session_profile(1)["recent_topic_ids"] == [102, 101]
    assert service.get_session_profile(1)["recent_entity_ids"] == [201]
    assert session.committed is True


def test_negative_signal_can_block_source() -> None:
    session = FakeSession()
    session.interactions[10].action = "dislike"
    session.users[1].settings = {"source_affinity_scores": {"5": 0.05}}
    store = FakeSessionProfileStore()
    service = ProfileUpdateService(session_store=store, alpha=0.25)

    service.update_from_interaction(session, 10)

    assert session.source_preferences[(1, 5)].preference == "blocked"
