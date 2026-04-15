from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from jarvis.ingestion.services import collect_source as service


@pytest.mark.asyncio
async def test_collect_source_once_returns_skipped_locked_without_run(monkeypatch) -> None:
    source = SimpleNamespace(
        id=13,
        name="BFM.ru",
        type="rss",
        priority="periodic",
        trust_score=0.8,
        config={"source_key": "bfm"},
    )

    @asynccontextmanager
    async def _fake_lock(_source_id: int):
        yield False

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "acquire_collection_lock", _fake_lock)
    monkeypatch.setattr(service, "_start_run", lambda source_id: (_ for _ in ()).throw(AssertionError("run must not start")))

    result = await service.collect_source_once("BFM.ru")

    assert result == {
        "source": "BFM.ru",
        "status": "skipped_locked",
        "run_id": None,
    }
