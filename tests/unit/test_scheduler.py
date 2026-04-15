from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from jarvis.ingestion.services import scheduler


def _build_source(**overrides):
    base = {
        "id": 13,
        "name": "BFM.ru",
        "is_active": True,
        "delivery_mode": "pull",
        "priority": "periodic",
        "crawl_interval": 30,
        "last_crawled": datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_compute_source_jitter_seconds_is_stable_for_same_cycle() -> None:
    source = _build_source()

    first = scheduler.compute_source_jitter_seconds(source)
    second = scheduler.compute_source_jitter_seconds(source)

    assert first == second


def test_is_source_due_false_when_before_next_due() -> None:
    source = _build_source()
    now = source.last_crawled + timedelta(minutes=10)

    assert scheduler.is_source_due(source, now=now) is False


def test_is_source_due_true_when_never_crawled() -> None:
    source = _build_source(last_crawled=None)

    assert scheduler.is_source_due(source) is True


@pytest.mark.asyncio
async def test_dispatch_due_sources_dry_run_does_not_enqueue(monkeypatch) -> None:
    source = _build_source(last_crawled=None)
    enqueue_calls: list[str] = []

    monkeypatch.setattr(scheduler, "_load_active_sources", lambda source_name=None: [source])
    monkeypatch.setattr(scheduler, "is_collection_locked", lambda source_id: _async_result(False))
    monkeypatch.setattr(scheduler, "mark_collection_pending", lambda source_id, ttl_seconds: _async_result(True))
    monkeypatch.setattr(scheduler, "_enqueue_collect_source", lambda source_name: enqueue_calls.append(source_name))

    result = await scheduler.dispatch_due_sources_once(dry_run=True)

    assert result["due_sources"] == 1
    assert result["scheduled_count"] == 0
    assert result["entries"][0]["reason"] == "dry_run"
    assert enqueue_calls == []


@pytest.mark.asyncio
async def test_dispatch_due_sources_skips_locked_source(monkeypatch) -> None:
    source = _build_source(last_crawled=None)
    enqueue_calls: list[str] = []

    monkeypatch.setattr(scheduler, "_load_active_sources", lambda source_name=None: [source])
    monkeypatch.setattr(scheduler, "is_collection_locked", lambda source_id: _async_result(True))
    monkeypatch.setattr(scheduler, "_enqueue_collect_source", lambda source_name: enqueue_calls.append(source_name))

    result = await scheduler.dispatch_due_sources_once()

    assert result["scheduled_count"] == 0
    assert result["entries"][0]["reason"] == "locked"
    assert enqueue_calls == []


@pytest.mark.asyncio
async def test_dispatch_due_sources_enqueues_due_source(monkeypatch) -> None:
    source = _build_source(last_crawled=None)
    enqueue_calls: list[str] = []

    monkeypatch.setattr(scheduler, "_load_active_sources", lambda source_name=None: [source])
    monkeypatch.setattr(scheduler, "is_collection_locked", lambda source_id: _async_result(False))
    monkeypatch.setattr(scheduler, "mark_collection_pending", lambda source_id, ttl_seconds: _async_result(True))
    monkeypatch.setattr(scheduler, "_enqueue_collect_source", lambda source_name: enqueue_calls.append(source_name))

    result = await scheduler.dispatch_due_sources_once()

    assert result["scheduled_count"] == 1
    assert result["entries"][0]["reason"] == "enqueued"
    assert enqueue_calls == [source.name]


async def _async_result(value):
    return value
