from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from jarvis.db.models.news import News
from jarvis.db.models.user import User
from jarvis.personalization.models.interaction_models import InteractionEventRequest
from jarvis.personalization.services.interaction_service import (
    InteractionLoggingService,
    SessionSeenHistory,
)


class FakeRedis:
    def __init__(self) -> None:
        self.storage: dict[str, list[str]] = {}

    def lpush(self, key: str, value: str) -> None:
        self.storage.setdefault(key, [])
        self.storage[key].insert(0, value)

    def ltrim(self, key: str, start: int, stop: int) -> None:
        if key not in self.storage:
            return
        self.storage[key] = self.storage[key][start: stop + 1]

    def expire(self, key: str, ttl: int) -> None:
        return None

    def lrange(self, key: str, start: int, stop: int) -> list[str]:
        if key not in self.storage:
            return []
        return self.storage[key][start: stop + 1]

    def delete(self, key: str) -> int:
        return 1 if self.storage.pop(key, None) is not None else 0


class FakeSeenHistory(SessionSeenHistory):
    def __init__(self) -> None:
        super().__init__(ttl_seconds=60)
        self.fake = FakeRedis()

    def _get_redis(self):  # type: ignore[override]
        return self.fake


def test_interaction_request_normalizes_action() -> None:
    event = InteractionEventRequest(user_id=1, news_id=2, action=" LIKE ")
    assert event.action == "like"


def test_seen_history_roundtrip() -> None:
    history = FakeSeenHistory()

    history.mark_seen(10, user_id=1)
    history.mark_seen(11, user_id=1)
    history.mark_seen(10, user_id=1)

    state = history.get_state(user_id=1)
    assert state.news_ids == [10, 11]


def test_log_interaction_persists_and_marks_seen() -> None:
    history = FakeSeenHistory()
    service = InteractionLoggingService(seen_history=history)
    session = Mock()

    user = User(id=1, username="alice", settings={}, created_at=datetime.now(UTC))
    news = News(id=2, source_id=1, title="x", canonical_url="u", published_at=datetime.now(UTC))
    interaction = Mock(id=55, user_id=1, news_id=2, action="like", dwell_time_sec=None, search_log_id=7, created_at=datetime.now(UTC))

    def fake_get(model, key):
        if model.__name__ == "User" and key == 1:
            return user
        if model.__name__ == "News" and key == 2:
            return news
        return None

    session.get.side_effect = fake_get
    session.scalar.return_value = 7
    session.refresh.side_effect = lambda obj: setattr(obj, "id", 55) or setattr(obj, "created_at", interaction.created_at)

    event = InteractionEventRequest(
        user_id=1,
        news_id=2,
        action="like",
        search_log_id=7,
        session_id="abc",
    )

    result = service.log_interaction(session, event)

    assert result.interaction_id == 55
    assert result.stored_action == "like"
    assert result.derived_signal == 1.0
    assert history.get_state(user_id=1).news_ids == [2]
    assert history.get_state(session_id="abc").news_ids == [2]
    session.commit.assert_called_once()


def test_log_interaction_rejects_unknown_search_log() -> None:
    history = FakeSeenHistory()
    service = InteractionLoggingService(seen_history=history)
    session = Mock()

    user = User(id=1, username="alice", settings={}, created_at=datetime.now(UTC))
    news = News(id=2, source_id=1, title="x", canonical_url="u", published_at=datetime.now(UTC))

    def fake_get(model, key):
        if model.__name__ == "User" and key == 1:
            return user
        if model.__name__ == "News" and key == 2:
            return news
        return None

    session.get.side_effect = fake_get
    session.scalar.return_value = None

    with pytest.raises(ValueError, match="Search log 99 not found"):
        service.log_interaction(
            session,
            InteractionEventRequest(user_id=1, news_id=2, action="click", search_log_id=99),
        )


def test_search_log_validation_is_scoped_to_user() -> None:
    session = Mock()
    session.scalar.return_value = None

    with pytest.raises(ValueError, match="Search log 99 not found for user 2"):
        InteractionLoggingService._ensure_search_log(session, search_log_id=99, user_id=2)

    sql = str(session.scalar.call_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "search_logs.id = 99" in sql
    assert "search_logs.user_id = 2" in sql


def test_log_interaction_can_defer_commit() -> None:
    history = FakeSeenHistory()
    service = InteractionLoggingService(seen_history=history)
    session = Mock()

    user = User(id=1, username="alice", settings={}, created_at=datetime.now(UTC))
    news = News(id=2, source_id=1, title="x", canonical_url="u", published_at=datetime.now(UTC))

    def fake_get(model, key):
        if model.__name__ == "User" and key == 1:
            return user
        if model.__name__ == "News" and key == 2:
            return news
        return None

    session.get.side_effect = fake_get
    session.refresh.side_effect = lambda obj: setattr(obj, "id", 56) or setattr(obj, "created_at", datetime.now(UTC))

    result = service.log_interaction(
        session,
        InteractionEventRequest(user_id=1, news_id=2, action="like"),
        commit=False,
    )

    assert result.interaction_id == 56
    session.flush.assert_called_once()
    session.commit.assert_not_called()
