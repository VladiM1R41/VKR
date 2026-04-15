from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from jarvis.ingestion.services import collect_source as service


class _FakeCollector:
    def __init__(self):
        self.last_was_not_modified = True
        self.last_http_status = 304
        self.last_response_bytes = 0
        self.last_items_total = 0
        self.last_parse_errors = 0
        self.last_sent_etag = '"etag-v1"'
        self.last_sent_if_modified_since = "Sat, 11 Apr 2026 09:00:00 GMT"
        self.last_received_etag = '"etag-v1"'
        self.last_received_last_modified = "Sat, 11 Apr 2026 10:00:00 GMT"

    async def collect(self):
        return []


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FreshCollector:
    def __init__(self):
        self.last_was_not_modified = False
        self.last_http_status = 200
        self.last_response_bytes = 1024
        self.last_items_total = 1
        self.last_parse_errors = 0
        self.last_item_errors = []
        self.last_item_failures = 0
        self.last_sent_etag = None
        self.last_sent_if_modified_since = None
        self.last_received_etag = None
        self.last_received_last_modified = None

    async def collect(self):
        return ["article-1"]


class _SameBuildDateCollector:
    def __init__(self):
        self.last_was_not_modified = False
        self.last_was_same_build_date = True
        self.last_http_status = 200
        self.last_response_bytes = 2048
        self.last_items_total = 0
        self.last_parse_errors = 0
        self.last_item_errors = []
        self.last_item_failures = 0
        self.last_sent_etag = None
        self.last_sent_if_modified_since = None
        self.last_received_etag = None
        self.last_received_last_modified = None
        self.last_received_last_build_date = "Sat, 11 Apr 2026 10:00:00 GMT"

    async def collect(self):
        return []


@asynccontextmanager
async def _fake_acquired_lock(_source_id: int):
    yield True


@pytest.mark.asyncio
async def test_collect_source_once_returns_skipped_304(monkeypatch) -> None:
    source = SimpleNamespace(
        id=12,
        name="CNews",
        type="rss",
        priority="periodic",
        trust_score=0.8,
        config={"source_key": "cnews"},
    )
    finalized = {}

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "_check_backpressure", lambda _source: None)
    monkeypatch.setattr(service, "_start_run", lambda source_id: 77)
    monkeypatch.setattr(service, "_load_known_canonical_urls", lambda source_id: set())
    monkeypatch.setattr(service, "acquire_collection_lock", _fake_acquired_lock)
    monkeypatch.setattr(service, "clear_collection_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        service.CollectorDispatcher,
        "get_collector",
        lambda source, client, known_canonical_urls=None: _FakeCollector(),
    )

    def _fake_finalize_run(**kwargs):
        finalized.update(kwargs)

    monkeypatch.setattr(service, "_finalize_run", _fake_finalize_run)

    result = await service.collect_source_once("CNews")

    assert result["status"] == "skipped_304"
    assert result["run_id"] == 77
    assert finalized["status"] == "skipped_304"
    assert finalized["http_status"] == 304
    assert finalized["sent_etag"] == '"etag-v1"'
    assert finalized["received_last_modified"] == "Sat, 11 Apr 2026 10:00:00 GMT"


@pytest.mark.asyncio
async def test_collect_source_once_enqueues_deferred_html_enrichment(monkeypatch) -> None:
    source = SimpleNamespace(
        id=13,
        name="BFM.ru",
        type="rss",
        priority="periodic",
        trust_score=0.8,
        config={"source_key": "bfm", "full_text_method": "html_trafilatura"},
    )
    finalized = {}
    enqueue_calls: list[tuple[str, int]] = []

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "_check_backpressure", lambda _source: None)
    monkeypatch.setattr(service, "_start_run", lambda source_id: 88)
    monkeypatch.setattr(service, "_load_known_canonical_urls", lambda source_id: set())
    monkeypatch.setattr(service, "acquire_collection_lock", _fake_acquired_lock)
    monkeypatch.setattr(service, "clear_collection_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        service.CollectorDispatcher,
        "get_collector",
        lambda source, client, known_canonical_urls=None: _FreshCollector(),
    )
    monkeypatch.setattr(service, "_persist_articles", lambda run_id, source_id, articles: ([901], 0, 0))
    monkeypatch.setattr(service, "_enqueue_html_enrichment", lambda source, limit: _async_enqueue(enqueue_calls, source.name, limit))

    def _fake_finalize_run(**kwargs):
        finalized.update(kwargs)

    monkeypatch.setattr(service, "_finalize_run", _fake_finalize_run)

    result = await service.collect_source_once("BFM.ru")

    assert result["status"] == "success"
    assert result["items_new"] == 1
    assert enqueue_calls == [("BFM.ru", 1)]
    assert finalized["status"] == "success"


@pytest.mark.asyncio
async def test_enqueue_html_enrichment_requests_rerun_when_pending_exists(monkeypatch) -> None:
    source = SimpleNamespace(id=13, name="BFM.ru")
    rerun_calls: list[tuple[int, int]] = []

    monkeypatch.setattr(service, "mark_enrichment_pending", lambda source_id, ttl: _async_false())
    monkeypatch.setattr(service, "request_enrichment_rerun", lambda source_id, ttl: _async_record(rerun_calls, source_id, ttl))

    scheduled = await service._enqueue_html_enrichment(source, limit=5)

    assert scheduled is False
    assert rerun_calls


@pytest.mark.asyncio
async def test_collect_source_once_returns_success_on_same_last_build_date(monkeypatch) -> None:
    source = SimpleNamespace(
        id=10,
        name="МК",
        type="rss",
        priority="periodic",
        trust_score=0.78,
        config={"source_key": "mk", "has_last_build_date": True},
    )
    finalized = {}

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "_check_backpressure", lambda _source: None)
    monkeypatch.setattr(service, "_start_run", lambda source_id: 99)
    monkeypatch.setattr(service, "_load_known_canonical_urls", lambda source_id: set())
    monkeypatch.setattr(service, "acquire_collection_lock", _fake_acquired_lock)
    monkeypatch.setattr(service, "clear_collection_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        service.CollectorDispatcher,
        "get_collector",
        lambda source, client, known_canonical_urls=None: _SameBuildDateCollector(),
    )

    def _fake_finalize_run(**kwargs):
        finalized.update(kwargs)

    monkeypatch.setattr(service, "_finalize_run", _fake_finalize_run)

    result = await service.collect_source_once("МК")

    assert result["status"] == "success"
    assert result["run_id"] == 99
    assert result["items_total"] == 0
    assert finalized["status"] == "success"
    assert finalized["received_last_build_date"] == "Sat, 11 Apr 2026 10:00:00 GMT"


async def _async_enqueue(store: list[tuple[str, int]], source_name: str, limit: int):
    store.append((source_name, limit))


async def _async_none():
    return None


async def _async_false():
    return False


async def _async_record(store: list[tuple[int, int]], source_id: int, ttl: int):
    store.append((source_id, ttl))
    return True


def test_persist_articles_counts_duplicate_and_sets_tentative_event_cluster(monkeypatch) -> None:
    duplicate_article = SimpleNamespace(
        url="https://example.com/duplicate",
        canonical_url="https://example.com/duplicate",
        title="Duplicate article",
        content=None,
        snippet_lead="lead",
        published_at=None,
        source_id=13,
        channel_type="RSS",
        information_type="daily",
        content_type="news",
        language="ru",
        title_hash="hash-1",
        urgency="normal",
        is_uncertain=False,
        content_status="ok",
        extraction_method=None,
        raw_pub_date=None,
        parser_version="rsscollector-v1",
        date_inferred=False,
        extra={},
        raw_content=None,
        raw_format="html",
    )
    new_article = SimpleNamespace(
        url="https://example.com/new",
        canonical_url="https://example.com/new",
        title="New article",
        content="Full content",
        snippet_lead="lead",
        published_at=None,
        source_id=13,
        channel_type="RSS",
        information_type="daily",
        content_type="news",
        language="ru",
        title_hash="hash-2",
        urgency="normal",
        is_uncertain=False,
        content_status="ok",
        extraction_method="rss_yandex_fulltext",
        raw_pub_date=None,
        parser_version="rsscollector-v1",
        date_inferred=False,
        extra={"foo": "bar"},
        raw_content="<p>Full content</p>",
        raw_format="html",
    )

    insert_calls: list[tuple[object, dict]] = []
    update_calls: list[dict] = []
    raw_upserts: list[dict] = []
    log_calls: list[tuple] = []

    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeStatement:
        def __init__(self, kind: str, model: object):
            self.kind = kind
            self.model = model
            self.payload: dict = {}
            self.index_elements = None

        def values(self, **kwargs):
            self.payload = dict(kwargs)
            return self

        def on_conflict_do_nothing(self, **kwargs):
            self.index_elements = kwargs.get("index_elements")
            return self

        def on_conflict_do_update(self, **kwargs):
            self.index_elements = kwargs.get("index_elements")
            self.payload.update(kwargs.get("set_", {}))
            return self

        def returning(self, *_args, **_kwargs):
            return self

        def where(self, *_args, **_kwargs):
            return self

    def _fake_insert(model):
        return _FakeStatement("insert", model)

    def _fake_update(model):
        return _FakeStatement("update", model)

    class _FakeSession:
        def __init__(self):
            self.news_insert_returns = iter([None, 501])

        def execute(self, stmt):
            if stmt.kind == "insert" and stmt.model is service.News:
                insert_calls.append((stmt.model, dict(stmt.payload)))
                return _FakeResult(next(self.news_insert_returns))
            if stmt.kind == "update" and stmt.model is service.News:
                update_calls.append(dict(stmt.payload))
                return _FakeResult(None)
            if stmt.kind == "insert" and stmt.model is service.NewsRaw:
                raw_upserts.append(dict(stmt.payload))
                return _FakeResult(None)
            raise AssertionError(f"Unexpected statement: {stmt.kind} {stmt.model}")

        def commit(self):
            return None

        def rollback(self):
            return None

    class _FakeSessionContext:
        def __enter__(self):
            return _FakeSession()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(service, "insert", _fake_insert)
    monkeypatch.setattr(service, "update", _fake_update)
    monkeypatch.setattr(service, "SyncSessionLocal", _FakeSessionContext)
    monkeypatch.setattr(service, "_log_run_error", lambda *args, **kwargs: log_calls.append((args, kwargs)))

    inserted_ids, duplicates, failures = service._persist_articles(
        run_id=77,
        source_id=13,
        articles=[duplicate_article, new_article],
    )

    assert inserted_ids == [501]
    assert duplicates == 1
    assert failures == 0
    assert log_calls == []
    assert len(insert_calls) == 2
    assert update_calls == [{"event_cluster_id": 501}]
    assert raw_upserts == [
        {
            "news_id": 501,
            "raw_content": "<p>Full content</p>",
            "raw_format": "html",
            "parser_version": "rsscollector-v1",
        }
    ]
