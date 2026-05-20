import json

import pytest

from jarvis.ingestion.services import pubsub


class _FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.closed = False

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_publish_new_articles_ready_uses_documented_channel_and_payload(monkeypatch) -> None:
    fake_redis = _FakeRedis()

    monkeypatch.setattr(pubsub, "_get_redis", lambda: fake_redis)

    batch_id = await pubsub.publish_new_articles_ready(source_id=7, news_ids=[101, 102, 103])

    assert batch_id is not None
    assert fake_redis.closed is True
    assert len(fake_redis.published) == 1

    channel, message = fake_redis.published[0]
    payload = json.loads(message)

    assert channel == "new_articles_ready"
    assert payload["batch_id"] == batch_id
    assert payload["count"] == 3
    assert payload["source_id"] == 7


@pytest.mark.asyncio
async def test_publish_breaking_event_uses_documented_channel_and_payload(monkeypatch) -> None:
    fake_redis = _FakeRedis()

    monkeypatch.setattr(pubsub, "_get_redis", lambda: fake_redis)

    await pubsub.publish_breaking_event(news_id=42, event_cluster_id=42, urgency="high")

    assert fake_redis.closed is True
    assert len(fake_redis.published) == 1

    channel, message = fake_redis.published[0]
    payload = json.loads(message)

    assert channel == "breaking_events"
    assert payload == {
        "news_id": 42,
        "event_cluster_id": 42,
        "urgency": "high",
    }


@pytest.mark.asyncio
async def test_publish_breaking_event_falls_back_to_news_id_when_cluster_missing(monkeypatch) -> None:
    fake_redis = _FakeRedis()

    monkeypatch.setattr(pubsub, "_get_redis", lambda: fake_redis)

    await pubsub.publish_breaking_event(news_id=77, event_cluster_id=None, urgency="critical")

    _, message = fake_redis.published[0]
    payload = json.loads(message)

    assert payload["news_id"] == 77
    assert payload["event_cluster_id"] == 77
    assert payload["urgency"] == "critical"
