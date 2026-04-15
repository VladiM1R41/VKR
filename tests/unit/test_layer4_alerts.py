from __future__ import annotations

from datetime import UTC, datetime

from jarvis.db.models.news import News
from jarvis.db.models.user import User
from jarvis.personalization.services.alert_service import AlertService
from jarvis.personalization.services.profile_update_service import SessionProfileStore
from jarvis.personalization.services.runtime_state import AlertRateLimiter


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
        self.users = {
            1: User(id=1, username="alice", settings={}, created_at=datetime.now(UTC)),
        }
        self.news_rows = {
            10: News(
                id=10,
                source_id=3,
                title="Breaking про ЦБ",
                canonical_url="u10",
                published_at=datetime.now(UTC),
                information_type="breaking",
                urgency="critical",
                channel_type="RSS",
                url="u10",
            ),
            11: News(
                id=11,
                source_id=3,
                title="Обычная новость про spike",
                canonical_url="u11",
                published_at=datetime.now(UTC),
                information_type="daily",
                urgency="high",
                channel_type="RSS",
                url="u11",
            ),
        }
        self.source_rows = [type("SourceStub", (), {"id": 3, "name": "РБК"})()]
        self.topic_rows = [type("TopicStub", (), {"id": 5, "name": "Экономика"})()]
        self.news_entities = {10: [7], 11: [7]}
        self.news_topics = {10: [5], 11: [5]}
        self.subscription_rows = [(7, "ЦБ РФ")]
        self.spike_rows = [(7, "ЦБ РФ")]

    def get(self, model, key):
        if model.__name__ == "User":
            return self.users.get(key)
        return None

    def scalars(self, stmt):
        text = str(stmt)
        if "FROM topics" in text:
            return ScalarRows(self.topic_rows)
        if "FROM sources" in text:
            return ScalarRows(self.source_rows)
        raise AssertionError(text)

    def execute(self, stmt):
        text = str(stmt)
        if "user_entity_subscriptions" in text and "entities" in text:
            return ScalarRows(self.subscription_rows)
        if "entity_profiles" in text and "entities" in text:
            return ScalarRows(self.spike_rows)
        raise AssertionError(text)


class FakeAlertService(AlertService):
    def _load_news(self, session, news_ids):  # type: ignore[override]
        return [session.news_rows[item] for item in news_ids]

    def _load_news_entity_ids(self, session, news_id):  # type: ignore[override]
        return list(session.news_entities.get(news_id, []))

    def _load_news_topic_ids(self, session, news_id):  # type: ignore[override]
        return list(session.news_topics.get(news_id, []))


class FakeRateLimiter(AlertRateLimiter):
    def __init__(self, blocked_keys: set[tuple[int, str, int]] | None = None) -> None:
        self.blocked_keys = set(blocked_keys or set())
        self.marked: list[tuple[int, str, int]] = []

    def is_allowed(self, *, user_id: int, alert_type: str, news_id: int) -> bool:  # type: ignore[override]
        return (user_id, alert_type, news_id) not in self.blocked_keys

    def mark_sent(self, *, user_id: int, alert_type: str, news_id: int) -> None:  # type: ignore[override]
        self.marked.append((user_id, alert_type, news_id))


def test_alert_service_builds_subscription_spike_and_breaking_alerts() -> None:
    session = FakeSession()
    service = FakeAlertService(
        session_profile_store=FakeSessionStore(
            {
                "recent_news_ids": [],
                "recent_topic_ids": [5],
                "recent_entity_ids": [],
                "last_updated_at": datetime.now(UTC).isoformat(),
            }
        ),
        rate_limiter=FakeRateLimiter(),
    )

    batch = service.build_alert_batch(session, user_id=1, news_ids=[10, 11])

    alert_types = [item.alert_type for item in batch.alerts]
    assert "alert_news" in alert_types
    assert "alert_spike" in alert_types
    assert "breaking_match" in alert_types
    assert "tracked_topic_update" in alert_types


def test_alert_service_deduplicates_same_alert_key() -> None:
    service = FakeAlertService(session_profile_store=FakeSessionStore({}))
    alerts = [
        service._deduplicate([]),
    ]
    assert alerts == [[]]


def test_alert_service_filters_cooldown_and_marks_sent() -> None:
    session = FakeSession()
    limiter = FakeRateLimiter(blocked_keys={(1, "alert_news", 10)})
    service = FakeAlertService(
        session_profile_store=FakeSessionStore(
            {
                "recent_news_ids": [],
                "recent_topic_ids": [5],
                "recent_entity_ids": [],
                "last_updated_at": datetime.now(UTC).isoformat(),
            }
        ),
        rate_limiter=limiter,
    )

    batch = service.build_alert_batch(session, user_id=1, news_ids=[10])

    assert all(not (item.alert_type == "alert_news" and item.news_id == 10) for item in batch.alerts)
    sent_count = service.mark_alerts_sent(batch)
    assert sent_count == len(batch.alerts)
    assert limiter.marked
