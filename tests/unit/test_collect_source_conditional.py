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
async def test_collect_source_once_records_enqueue_failure_without_failing_run(monkeypatch) -> None:
    source = SimpleNamespace(
        id=17,
        name="BFM.ru",
        type="rss",
        priority="periodic",
        trust_score=0.8,
        config={"source_key": "bfm", "full_text_method": "html_trafilatura"},
    )
    finalized = {}
    logged_errors: list[tuple[tuple, dict]] = []

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "_check_backpressure", lambda _source: None)
    monkeypatch.setattr(service, "_start_run", lambda source_id: 108)
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
    monkeypatch.setattr(service, "_publish_inserted_article_signals", lambda **kwargs: _async_none())
    monkeypatch.setattr(service, "_enqueue_html_enrichment", lambda source, limit: _async_raise(RuntimeError("broker down")))
    monkeypatch.setattr(service, "_log_run_error", lambda *args, **kwargs: logged_errors.append((args, kwargs)))

    def _fake_finalize_run(**kwargs):
        finalized.update(kwargs)

    monkeypatch.setattr(service, "_finalize_run", _fake_finalize_run)

    result = await service.collect_source_once("BFM.ru")

    assert result["status"] == "partial"
    assert finalized["status"] == "partial"
    assert logged_errors[0][0][2] == "enqueue_failed"
    assert "enqueue_failed" in logged_errors[0][0][3]
    assert logged_errors[0][1]["mark_run_failed"] is False


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


@pytest.mark.asyncio
async def test_collect_source_once_logs_backpressure_warn_and_continues(monkeypatch) -> None:
    source = SimpleNamespace(
        id=14,
        name="Test source",
        type="rss",
        priority="periodic",
        trust_score=0.9,
        config={"source_key": "test"},
    )
    events: list[tuple[int, str, dict]] = []

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(
        service,
        "_check_backpressure",
        lambda _source: {"decision": "warn", "unprocessed_count": 1234},
    )
    monkeypatch.setattr(service, "_start_run", lambda source_id: 101)
    monkeypatch.setattr(service, "_load_known_canonical_urls", lambda source_id: set())
    monkeypatch.setattr(service, "acquire_collection_lock", _fake_acquired_lock)
    monkeypatch.setattr(service, "clear_collection_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        service.CollectorDispatcher,
        "get_collector",
        lambda source, client, known_canonical_urls=None: _SameBuildDateCollector(),
    )
    monkeypatch.setattr(
        service,
        "log_event",
        lambda logger, level, event, **kwargs: events.append((level, event, kwargs)),
    )
    monkeypatch.setattr(service, "_finalize_run", lambda **kwargs: None)

    result = await service.collect_source_once("Test source")

    assert result["status"] == "success"
    assert "source_run_backpressure_warn" in [event for _, event, _ in events]
    warn_event = next(item for item in events if item[1] == "source_run_backpressure_warn")
    assert warn_event[2]["unprocessed_count"] == 1234


@pytest.mark.asyncio
async def test_collect_source_once_persists_backpressure_skip_run(monkeypatch) -> None:
    source = SimpleNamespace(
        id=145,
        name="Test source",
        type="rss",
        priority="periodic",
        trust_score=0.7,
        config={"source_key": "test"},
    )
    finalized: dict = {}
    events: list[tuple[int, str, dict]] = []

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(
        service,
        "_check_backpressure",
        lambda _source: {
            "decision": "skip",
            "unprocessed_count": 12000,
            "reason": "circuit_breaker_open",
        },
    )
    monkeypatch.setattr(service, "_start_run", lambda source_id: 202)
    monkeypatch.setattr(service, "acquire_collection_lock", _fake_acquired_lock)
    monkeypatch.setattr(service, "clear_collection_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service, "_finalize_run", lambda **kwargs: finalized.update(kwargs))
    monkeypatch.setattr(
        service,
        "log_event",
        lambda logger, level, event, **kwargs: events.append((level, event, kwargs)),
    )

    result = await service.collect_source_once("Test source")

    assert result == {
        "source": "Test source",
        "status": "skipped_backpressure",
        "reason": "circuit_breaker_open",
        "run_id": 202,
        "unprocessed_count": 12000,
    }
    assert finalized["run_id"] == 202
    assert finalized["status"] == "skipped_backpressure"
    assert finalized["items_total"] == 0
    assert finalized["items_new"] == 0
    skip_event = next(item for item in events if item[1] == "source_run_skipped_backpressure")
    assert skip_event[2]["run_id"] == 202
    assert skip_event[2]["reason"] == "circuit_breaker_open"


@pytest.mark.asyncio
async def test_collect_source_once_publishes_inserted_article_signals(monkeypatch) -> None:
    source = SimpleNamespace(
        id=15,
        name="Test source",
        type="rss",
        priority="periodic",
        trust_score=0.9,
        config={"source_key": "test"},
    )
    published_calls: list[tuple[int, int, list[int]]] = []

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "_check_backpressure", lambda _source: None)
    monkeypatch.setattr(service, "_start_run", lambda source_id: 102)
    monkeypatch.setattr(service, "_load_known_canonical_urls", lambda source_id: set())
    monkeypatch.setattr(service, "acquire_collection_lock", _fake_acquired_lock)
    monkeypatch.setattr(service, "clear_collection_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        service.CollectorDispatcher,
        "get_collector",
        lambda source, client, known_canonical_urls=None: _FreshCollector(),
    )
    monkeypatch.setattr(service, "_persist_articles", lambda run_id, source_id, articles: ([901, 902], 0, 0))
    monkeypatch.setattr(
        service,
        "_publish_inserted_article_signals",
        lambda *, source_id, run_id, inserted_ids: _async_publish(published_calls, source_id, run_id, inserted_ids),
    )
    monkeypatch.setattr(service, "_finalize_run", lambda **kwargs: None)

    result = await service.collect_source_once("Test source")

    assert result["status"] == "success"
    assert published_calls == [(15, 102, [901, 902])]


@pytest.mark.asyncio
async def test_collect_source_once_adds_known_duplicate_skips_to_duplicate_metric(monkeypatch) -> None:
    source = SimpleNamespace(
        id=16,
        name="Repeat source",
        type="rss",
        priority="periodic",
        trust_score=0.9,
        config={"source_key": "test"},
    )
    finalized = {}

    class _CollectorWithKnownDuplicates(_FreshCollector):
        def __init__(self):
            super().__init__()
            self.last_item_errors = []
            self.last_known_duplicates_skipped = 4

        async def collect(self):
            return ["article-1"]

    monkeypatch.setattr(service, "_load_source_by_name", lambda name: source)
    monkeypatch.setattr(service, "_check_backpressure", lambda _source: None)
    monkeypatch.setattr(service, "_start_run", lambda source_id: 103)
    monkeypatch.setattr(service, "_load_known_canonical_urls", lambda source_id: {"https://example.com/known"})
    monkeypatch.setattr(service, "acquire_collection_lock", _fake_acquired_lock)
    monkeypatch.setattr(service, "clear_collection_pending", lambda source_id: _async_none())
    monkeypatch.setattr(service.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        service.CollectorDispatcher,
        "get_collector",
        lambda source, client, known_canonical_urls=None: _CollectorWithKnownDuplicates(),
    )
    monkeypatch.setattr(service, "_persist_articles", lambda run_id, source_id, articles: ([901], 1, 0))
    monkeypatch.setattr(service, "_publish_inserted_article_signals", lambda **kwargs: _async_none())

    def _fake_finalize_run(**kwargs):
        finalized.update(kwargs)

    monkeypatch.setattr(service, "_finalize_run", _fake_finalize_run)

    result = await service.collect_source_once("Repeat source")

    assert result["status"] == "success"
    assert result["items_new"] == 1
    assert result["items_duplicate"] == 5
    assert finalized["items_duplicate"] == 5


@pytest.mark.asyncio
async def test_publish_inserted_article_signals_emits_batch_and_breaking_only(monkeypatch) -> None:
    batch_calls: list[tuple[int, list[int]]] = []
    breaking_calls: list[tuple[int, int | None, str]] = []

    monkeypatch.setattr(
        service,
        "_load_inserted_news_metadata",
        lambda inserted_ids: [
            {"news_id": 901, "event_cluster_id": 901, "urgency": "high"},
            {"news_id": 902, "event_cluster_id": 902, "urgency": "normal"},
            {"news_id": 903, "event_cluster_id": 903, "urgency": "critical"},
        ],
    )
    monkeypatch.setattr(
        service,
        "publish_new_articles_ready",
        lambda source_id, news_ids: _async_record_batch(batch_calls, source_id, news_ids),
    )
    monkeypatch.setattr(
        service,
        "publish_breaking_event",
        lambda *, news_id, event_cluster_id, urgency: _async_record_breaking(
            breaking_calls,
            news_id,
            event_cluster_id,
            urgency,
        ),
    )

    await service._publish_inserted_article_signals(
        source_id=15,
        run_id=102,
        inserted_ids=[901, 902, 903],
    )

    assert batch_calls == [(15, [901, 902, 903])]
    assert breaking_calls == [
        (901, 901, "high"),
        (903, 903, "critical"),
    ]


async def _async_enqueue(store: list[tuple[str, int]], source_name: str, limit: int):
    store.append((source_name, limit))


async def _async_publish(
    store: list[tuple[int, int, list[int]]],
    source_id: int,
    run_id: int,
    inserted_ids: list[int],
):
    store.append((source_id, run_id, inserted_ids))


async def _async_none():
    return None


async def _async_raise(exc: Exception):
    raise exc


async def _async_false():
    return False


async def _async_record(store: list[tuple[int, int]], source_id: int, ttl: int):
    store.append((source_id, ttl))
    return True


async def _async_record_batch(
    store: list[tuple[int, list[int]]],
    source_id: int,
    news_ids: list[int],
):
    store.append((source_id, news_ids))
    return "batch-123"


async def _async_record_breaking(
    store: list[tuple[int, int | None, str]],
    news_id: int,
    event_cluster_id: int | None,
    urgency: str,
):
    store.append((news_id, event_cluster_id, urgency))


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
