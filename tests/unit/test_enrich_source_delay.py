from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from jarvis.ingestion.services import enrich_source as service


class _FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@asynccontextmanager
async def _fake_acquired_lock(_source_id: int):
    yield True


@pytest.mark.asyncio
async def test_enrich_source_pending_respects_crawl_delay(monkeypatch) -> None:
    source = SimpleNamespace(
        id=13,
        name="BFM.ru",
        crawl_delay=2.5,
        config={"full_text_method": "html_trafilatura"},
    )
    pending_articles = [
        SimpleNamespace(id=101, url="https://example.com/1", snippet_lead="a"),
        SimpleNamespace(id=102, url="https://example.com/2", snippet_lead="b"),
    ]
    sleep_calls: list[float] = []

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "_load_pending_articles", lambda source_id, limit: pending_articles)
    monkeypatch.setattr(service, "_start_run", lambda source_id: 71)
    monkeypatch.setattr(service, "acquire_enrichment_lock", _fake_acquired_lock)
    monkeypatch.setattr(service, "clear_enrichment_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda *args, **kwargs: _FakeAsyncClient())
    monkeypatch.setattr(
        service,
        "_enrich_single_article",
        lambda **kwargs: _async_pair(True, False),
    )
    monkeypatch.setattr(service.asyncio, "sleep", lambda seconds: _async_sleep(sleep_calls, seconds))
    monkeypatch.setattr(service, "_finalize_run", lambda **kwargs: None)
    monkeypatch.setattr(service, "consume_enrichment_rerun", lambda source_id: _async_false())
    monkeypatch.setattr(service, "_has_pending_articles", lambda source_id: False)
    monkeypatch.setattr(service, "_schedule_followup_enrichment", lambda source, limit: _async_true())

    result = await service.enrich_source_pending_once("BFM.ru", limit=2)

    assert result["items_enriched"] == 2
    assert sleep_calls == [2.5]


async def test_enrich_source_pending_returns_skipped_locked_without_run(monkeypatch) -> None:
    source = SimpleNamespace(
        id=13,
        name="BFM.ru",
        crawl_delay=1.0,
        config={"full_text_method": "html_trafilatura"},
    )

    @asynccontextmanager
    async def _fake_locked(_source_id: int):
        yield False

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "acquire_enrichment_lock", _fake_locked)
    monkeypatch.setattr(service, "clear_enrichment_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service, "_start_run", lambda source_id: (_ for _ in ()).throw(AssertionError("run must not start")))

    result = await service.enrich_source_pending_once("BFM.ru", limit=2)

    assert result == {
        "source": "BFM.ru",
        "status": "skipped_locked",
        "run_id": None,
    }


@pytest.mark.asyncio
async def test_enrich_single_article_marks_recall_as_partial(monkeypatch) -> None:
    article = SimpleNamespace(id=201, url="https://example.com/article", snippet_lead="lead")
    source = SimpleNamespace(
        id=13,
        name="BFM.ru",
        config={"full_text_method": "html_trafilatura", "postprocess_rules": []},
    )
    persisted: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200
        text = "<html><body><article>stub</article></body></html>"
        content = text.encode("utf-8")
        headers = {}
        url = "https://example.com/article"

    class _FakeHttpClientSingle:
        async def get(self, *_args, **_kwargs):
            return _FakeResponse()

    monkeypatch.setattr(service, "extract_with_precision", lambda html: None)
    monkeypatch.setattr(service, "extract_with_recall", lambda html: "Recovered content from recall path.")
    monkeypatch.setattr(service, "apply_pre_extraction_rules", lambda html, rules: html)
    monkeypatch.setattr(service, "apply_postprocess_rules", lambda **kwargs: (kwargs["content"], kwargs["snippet_lead"]))
    monkeypatch.setattr(service, "_persist_enrichment", lambda **kwargs: persisted.update(kwargs))
    monkeypatch.setattr(service, "_log_extraction_error", lambda **kwargs: None)

    success, failed = await service._enrich_single_article(
        article=article,
        source=source,
        http_client=_FakeHttpClientSingle(),
        run_id=99,
    )

    assert (success, failed) == (True, False)
    assert persisted["content_status"] == "partial"
    assert persisted["extraction_method"] == "trafilatura_recall"
    assert persisted["content"] == "Recovered content from recall path."


@pytest.mark.asyncio
async def test_enrich_source_pending_schedules_followup_when_more_work_appears(monkeypatch) -> None:
    source = SimpleNamespace(
        id=13,
        name="BFM.ru",
        crawl_delay=1.0,
        config={"full_text_method": "html_trafilatura"},
    )
    pending_articles = [SimpleNamespace(id=101, url="https://example.com/1", snippet_lead="a")]
    followup_calls: list[tuple[str, int]] = []

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "_load_pending_articles", lambda source_id, limit: pending_articles)
    monkeypatch.setattr(service, "_start_run", lambda source_id: 72)
    monkeypatch.setattr(service, "acquire_enrichment_lock", _fake_acquired_lock)
    monkeypatch.setattr(service, "clear_enrichment_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda *args, **kwargs: _FakeAsyncClient())
    monkeypatch.setattr(service, "_enrich_single_article", lambda **kwargs: _async_pair(True, False))
    monkeypatch.setattr(service, "_finalize_run", lambda **kwargs: None)
    monkeypatch.setattr(service, "consume_enrichment_rerun", lambda source_id: _async_true())
    monkeypatch.setattr(service, "_has_pending_articles", lambda source_id: True)
    monkeypatch.setattr(service, "_schedule_followup_enrichment", lambda source, limit: _async_followup(followup_calls, source.name, limit))

    result = await service.enrich_source_pending_once("BFM.ru", limit=1)

    assert result["followup_needed"] is True
    assert followup_calls == [("BFM.ru", 1)]


@pytest.mark.asyncio
async def test_enrich_source_pending_logs_followup_enqueue_failure(monkeypatch) -> None:
    source = SimpleNamespace(
        id=13,
        name="BFM.ru",
        crawl_delay=1.0,
        config={"full_text_method": "html_trafilatura"},
    )
    pending_articles = [SimpleNamespace(id=101, url="https://example.com/1", snippet_lead="a")]
    enqueue_errors: list[dict] = []

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "_load_pending_articles", lambda source_id, limit: pending_articles)
    monkeypatch.setattr(service, "_start_run", lambda source_id: 73)
    monkeypatch.setattr(service, "acquire_enrichment_lock", _fake_acquired_lock)
    monkeypatch.setattr(service, "clear_enrichment_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda *args, **kwargs: _FakeAsyncClient())
    monkeypatch.setattr(service, "_enrich_single_article", lambda **kwargs: _async_pair(True, False))
    monkeypatch.setattr(service, "_finalize_run", lambda **kwargs: None)
    monkeypatch.setattr(service, "consume_enrichment_rerun", lambda source_id: _async_true())
    monkeypatch.setattr(service, "_has_pending_articles", lambda source_id: True)
    monkeypatch.setattr(service, "_schedule_followup_enrichment", lambda source, limit: _async_raise(RuntimeError("broker down")))
    monkeypatch.setattr(service, "_log_enrichment_enqueue_error", lambda **kwargs: enqueue_errors.append(kwargs))

    result = await service.enrich_source_pending_once("BFM.ru", limit=1)

    assert result["followup_needed"] is True
    assert enqueue_errors == [
        {
            "run_id": 73,
            "source_id": 13,
            "source_name": "BFM.ru",
            "error_message": "broker down",
        }
    ]


async def _async_pair(first, second):
    return first, second


async def _async_sleep(store: list[float], seconds: float):
    store.append(seconds)


async def _async_none():
    return None


async def _async_false():
    return False


async def _async_true():
    return True


async def _async_followup(store: list[tuple[str, int]], source_name: str, limit: int):
    store.append((source_name, limit))
    return True


async def _async_raise(exc: Exception):
    raise exc
