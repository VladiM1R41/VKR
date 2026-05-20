"""Regression tests for fixed Layer 1 bugs.

Each test protects a concrete bug from `docs/LAYER_1_EXECUTION_PLAN_AND_HANDOFF.md`.
The goal is not broad unit coverage, but a compact anti-regression safety net.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from types import SimpleNamespace

import pytest

from jarvis.ingestion.collectors.rss import RSSCollector
from jarvis.ingestion.parsing.dates import parse_feed_datetime
from jarvis.ingestion.parsing.urls import canonicalize_url
from jarvis.ingestion.services import collect_source
from jarvis.ingestion.services import distributed_lock
from jarvis.ingestion.services import enrich_source
from jarvis.ingestion.services import health
from jarvis.ingestion.services.monitoring import _refresh_sources_for_report


class _FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeResponse:
    status_code = 200
    headers: dict[str, str] = {}
    url = "https://example.com/feed.xml"

    def __init__(self, text: str):
        self.text = text
        self.content = text.encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class _FreshCollector:
    last_was_not_modified = False
    last_was_same_build_date = False
    last_http_status = 200
    last_response_bytes = 1024
    last_items_total = 7
    last_parse_errors = 0
    last_item_errors: list[dict] = []
    last_item_failures = 0
    last_sent_etag = None
    last_sent_if_modified_since = None
    last_received_etag = None
    last_received_last_modified = None
    last_received_last_build_date = None
    last_known_duplicates_skipped = 5

    async def collect(self):
        return ["article-1"]


class _SameBuildDateCollector:
    last_was_not_modified = False
    last_was_same_build_date = True
    last_http_status = 200
    last_response_bytes = 2048
    last_items_total = 0
    last_parse_errors = 0
    last_item_errors: list[dict] = []
    last_item_failures = 0
    last_sent_etag = None
    last_sent_if_modified_since = None
    last_received_etag = None
    last_received_last_modified = None
    last_received_last_build_date = "Thu, 23 Apr 2026 10:00:00 GMT"

    async def collect(self):
        return []


@asynccontextmanager
async def _fake_acquired_lock(_source_id: int):
    yield True


async def _async_none(*_args, **_kwargs):
    return None


async def _async_raise(exc: Exception):
    raise exc


def _patch_collect_common(monkeypatch: pytest.MonkeyPatch, source: SimpleNamespace, collector) -> None:
    monkeypatch.setattr(collect_source, "_load_source_by_name", lambda _name: source)
    monkeypatch.setattr(collect_source, "_check_backpressure", lambda _source: None)
    monkeypatch.setattr(collect_source, "_start_run", lambda _source_id: 501)
    monkeypatch.setattr(collect_source, "_load_known_canonical_urls", lambda _source_id: set())
    monkeypatch.setattr(collect_source, "acquire_collection_lock", _fake_acquired_lock)
    monkeypatch.setattr(collect_source, "clear_collection_pending", _async_none)
    monkeypatch.setattr(collect_source.httpx, "AsyncClient", lambda *args, **kwargs: _FakeAsyncClient())
    monkeypatch.setattr(
        collect_source.CollectorDispatcher,
        "get_collector",
        lambda source, client, known_canonical_urls=None: collector,
    )
    monkeypatch.setattr(collect_source, "_publish_inserted_article_signals", lambda **_kwargs: _async_none())


@pytest.mark.asyncio
async def test_regression_trafilatura_recall_is_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    """C/A1: fallback recall extraction must not be marked as full-quality `ok`."""

    article = SimpleNamespace(id=201, url="https://example.com/article", snippet_lead="lead")
    source = SimpleNamespace(
        id=13,
        name="BFM.ru",
        config={"full_text_method": "html_trafilatura", "postprocess_rules": []},
    )
    persisted: dict[str, object] = {}

    class _ArticleClient:
        async def get(self, *_args, **_kwargs):
            return _FakeResponse("<html><body><article>stub</article></body></html>")

    monkeypatch.setattr(enrich_source, "extract_with_precision", lambda _html: None)
    monkeypatch.setattr(enrich_source, "extract_with_recall", lambda _html: "Recovered via recall.")
    monkeypatch.setattr(enrich_source, "apply_pre_extraction_rules", lambda html, _rules: html)
    monkeypatch.setattr(
        enrich_source,
        "apply_postprocess_rules",
        lambda **kwargs: (kwargs["content"], kwargs["snippet_lead"]),
    )
    monkeypatch.setattr(enrich_source, "_persist_enrichment", lambda **kwargs: persisted.update(kwargs))
    monkeypatch.setattr(enrich_source, "_log_extraction_error", lambda **_kwargs: None)

    success, failed = await enrich_source._enrich_single_article(
        article=article,
        source=source,
        http_client=_ArticleClient(),
        run_id=99,
    )

    assert (success, failed) == (True, False)
    assert persisted["content_status"] == "partial"
    assert persisted["extraction_method"] == "trafilatura_recall"


@pytest.mark.asyncio
async def test_regression_backpressure_warn_is_logged_and_collection_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C/A5: warn-level backpressure is observable but does not skip the source."""

    source = SimpleNamespace(
        id=14,
        name="Test source",
        type="rss",
        priority="periodic",
        trust_score=0.9,
        config={"source_key": "test"},
    )
    events: list[tuple[str, dict]] = []
    finalized: dict[str, object] = {}
    _patch_collect_common(monkeypatch, source, _SameBuildDateCollector())
    monkeypatch.setattr(
        collect_source,
        "_check_backpressure",
        lambda _source: {"decision": "warn", "unprocessed_count": 1234},
    )
    monkeypatch.setattr(
        collect_source,
        "log_event",
        lambda _logger, _level, event, **kwargs: events.append((event, kwargs)),
    )
    monkeypatch.setattr(collect_source, "_finalize_run", lambda **kwargs: finalized.update(kwargs))

    result = await collect_source.collect_source_once("Test source")

    assert result["status"] == "success"
    assert finalized["status"] == "success"
    assert ("source_run_backpressure_warn", {"source_id": 14, "source_name": "Test source", "unprocessed_count": 1234}) in events


def test_regression_extraction_success_counts_partial() -> None:
    """C/A6: `partial` extraction is successful-but-lower-quality, not a failure."""

    assert health.SUCCESSFUL_EXTRACTION_STATUSES == ("ok", "partial")
    assert health._calculate_extraction_success_rate(successful_items=2, total_items=3) == pytest.approx(2 / 3)


def test_regression_staleness_yellow_starts_after_three_x() -> None:
    """C/B3: staleness yellow threshold is `>3x`, not the old `>4x`."""

    assert (
        health.determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=1.0,
            staleness_ratio=3.0,
        )
        == "green"
    )
    assert (
        health.determine_health_status(
            consecutive_failures=0,
            parse_success_rate=1.0,
            extraction_success_rate=1.0,
            staleness_ratio=3.1,
        )
        == "yellow"
    )


def test_regression_daily_health_dry_run_does_not_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    """C/A9: dry-run health refresh must call refresh with `persist=False`."""

    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr("jarvis.ingestion.services.monitoring._list_active_source_ids", lambda: [1, 2])

    def _fake_refresh(source_id: int, *, persist: bool = True):
        calls.append((source_id, persist))
        return {"source_id": source_id, "health_status": "green"}

    monkeypatch.setattr("jarvis.ingestion.services.monitoring.refresh_source_health", _fake_refresh)

    assert _refresh_sources_for_report(dry_run=True) == [
        {"source_id": 1, "health_status": "green"},
        {"source_id": 2, "health_status": "green"},
    ]
    assert calls == [(1, False), (2, False)]


def test_regression_naive_rss_datetime_is_marked_inferred() -> None:
    """C/B5: RSS datetimes without timezone are UTC-normalized and marked inferred."""

    parsed, inferred = parse_feed_datetime("Thu, 23 Apr 2026 14:00:00")

    assert parsed is not None
    assert parsed.isoformat() == "2026-04-23T14:00:00+00:00"
    assert inferred is True


def test_regression_www_prefix_normalization_is_exact() -> None:
    """C/D1: only exact `www.` prefix is stripped during canonicalization."""

    assert canonicalize_url("HTTPS://www.Example.com/path/?utm_source=x&a=1") == "https://example.com/path?a=1"
    assert canonicalize_url("https://www2.example.com/path") == "https://www2.example.com/path"


@pytest.mark.asyncio
async def test_regression_lock_release_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C/B7: Redis lock release failures must be visible in logs."""

    class _RedisWithBrokenRelease:
        async def set(self, *_args, **_kwargs):
            return True

        async def eval(self, *_args, **_kwargs):
            raise RuntimeError("redis eval failed")

        async def aclose(self):
            return None

    monkeypatch.setattr(distributed_lock.Redis, "from_url", lambda *_args, **_kwargs: _RedisWithBrokenRelease())

    with caplog.at_level(logging.WARNING):
        async with distributed_lock._acquire_lock("lock:test", ttl_seconds=10) as acquired:
            assert acquired is True

    assert "lock_release_failed" in caplog.text
    assert "redis eval failed" in caplog.text


@pytest.mark.asyncio
async def test_regression_enqueue_failure_is_structured_and_run_is_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C/B8: deferred enrichment enqueue failure is structured and degrades run to partial."""

    source = SimpleNamespace(
        id=17,
        name="BFM.ru",
        type="rss",
        priority="periodic",
        trust_score=0.8,
        config={"source_key": "bfm", "full_text_method": "html_trafilatura"},
    )
    finalized: dict[str, object] = {}
    logged_errors: list[tuple[tuple, dict]] = []
    _patch_collect_common(monkeypatch, source, _FreshCollector())
    monkeypatch.setattr(collect_source, "_persist_articles", lambda _run_id, _source_id, _articles: ([901], 0, 0))
    monkeypatch.setattr(
        collect_source,
        "_enqueue_html_enrichment",
        lambda _source, _limit: _async_raise(RuntimeError("broker down")),
    )
    monkeypatch.setattr(collect_source, "_log_run_error", lambda *args, **kwargs: logged_errors.append((args, kwargs)))
    monkeypatch.setattr(collect_source, "_finalize_run", lambda **kwargs: finalized.update(kwargs))

    result = await collect_source.collect_source_once("BFM.ru")

    assert result["status"] == "partial"
    assert finalized["status"] == "partial"
    assert logged_errors[0][0][2] == "enqueue_failed"
    assert logged_errors[0][1]["mark_run_failed"] is False


@pytest.mark.asyncio
async def test_regression_breaking_preclassifier_sets_high_urgency(monkeypatch: pytest.MonkeyPatch) -> None:
    """C/B6: explicit breaking marker must set both `information_type` and `urgency`."""

    rss = """
    <rss><channel>
      <item>
        <title>СРОЧНО: важная новость</title>
        <link>https://example.com/breaking</link>
        <description>Краткий текст новости</description>
        <pubDate>Thu, 23 Apr 2026 14:00:00 +0300</pubDate>
      </item>
    </channel></rss>
    """
    source = SimpleNamespace(
        id=1,
        url="https://example.com/rss",
        default_info_type="daily",
        default_content_type="news",
        config={"source_key": "test", "feed_url": "https://example.com/rss"},
    )

    async def _fake_fetch(*_args, **_kwargs):
        return _FakeResponse(rss)

    monkeypatch.setattr("jarvis.ingestion.collectors.rss.fetch_with_retry", _fake_fetch)
    monkeypatch.setattr("jarvis.ingestion.collectors.rss.ensure_lxml_available", lambda: None)

    articles = await RSSCollector(source, _FakeAsyncClient()).collect()

    assert articles[0].information_type == "breaking"
    assert articles[0].urgency == "high"
    assert articles[0].extra["urgency"] == "high"
    assert articles[0].extra["information_type_override"] == "pre_classifier_breaking"


@pytest.mark.asyncio
async def test_regression_repeat_run_duplicate_metric_includes_known_fast_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C/A7: `items_duplicate` includes known URL skips, not only DB conflicts."""

    source = SimpleNamespace(
        id=20,
        name="ТАСС",
        type="rss",
        priority="continuous",
        trust_score=0.95,
        config={"source_key": "tass"},
    )
    finalized: dict[str, object] = {}
    _patch_collect_common(monkeypatch, source, _FreshCollector())
    monkeypatch.setattr(collect_source, "_persist_articles", lambda _run_id, _source_id, _articles: ([901], 2, 0))
    monkeypatch.setattr(collect_source, "_finalize_run", lambda **kwargs: finalized.update(kwargs))

    result = await collect_source.collect_source_once("ТАСС")

    assert result["items_duplicate"] == 7
    assert finalized["items_duplicate"] == 7


def test_regression_backpressure_skip_is_parse_neutral_but_health_degrading() -> None:
    """C/B9-addendum: backpressure skip is not parser failure, but remains yellow signal."""

    summary = health._summarize_run_window(
        [
            SimpleNamespace(status="skipped_backpressure", http_errors_count=0),
            SimpleNamespace(status="success", http_errors_count=0),
            SimpleNamespace(status="skipped_backpressure", http_errors_count=0),
        ]
    )

    assert summary["attempted_runs_count"] == 1
    assert summary["parse_success_rate"] == 1.0
    assert summary["backpressure_skips_count"] == 2
    assert (
        health.determine_health_status(
            consecutive_failures=0,
            parse_success_rate=summary["parse_success_rate"],
            extraction_success_rate=1.0,
            backpressure_skips_count=summary["backpressure_skips_count"],
        )
        == "yellow"
    )
