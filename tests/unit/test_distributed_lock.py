import logging

import pytest

from jarvis.ingestion.services import distributed_lock


class _FakeRedisReleaseFailure:
    async def set(self, *_args, **_kwargs):
        return True

    async def eval(self, *_args, **_kwargs):
        raise RuntimeError("redis release failed")

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_lock_release_failure_is_logged(monkeypatch, caplog) -> None:
    fake_redis = _FakeRedisReleaseFailure()
    monkeypatch.setattr(distributed_lock.Redis, "from_url", lambda *args, **kwargs: fake_redis)

    with caplog.at_level(logging.WARNING, logger="jarvis.ingestion.services.distributed_lock"):
        async with distributed_lock._acquire_lock("lock:test", ttl_seconds=30) as acquired:
            assert acquired is True

    assert "lock_release_failed" in caplog.text
    assert "redis release failed" in caplog.text
