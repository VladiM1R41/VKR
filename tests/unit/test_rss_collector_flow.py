from types import SimpleNamespace

import pytest

from jarvis.ingestion.collectors.rss import RSSCollector


def _build_source(**config_overrides):
    config = {
        "url_source_field": "link",
        "canonical_keep_params": [],
    }
    config.update(config_overrides)
    return SimpleNamespace(
        id=1,
        name="Test Source",
        url="https://example.com/rss.xml",
        config=config,
        default_info_type="daily",
        default_content_type="news",
    )


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200, headers: dict | None = None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        return None


class _FakeHttpClient:
    def __init__(self, xml: str, *, status_code: int = 200, headers: dict | None = None):
        self._content = xml.encode("utf-8")
        self._status_code = status_code
        self._headers = headers or {}
        self.last_headers = None

    async def get(self, *_args, **kwargs):
        self.last_headers = kwargs.get("headers") or {}
        return _FakeResponse(self._content, status_code=self._status_code, headers=self._headers)


@pytest.mark.asyncio
async def test_rss_collector_stops_early_on_known_canonical_url() -> None:
    xml = """
    <rss><channel>
      <item>
        <title>Known story</title>
        <link>https://example.com/known</link>
      </item>
      <item>
        <title>New story</title>
        <link>https://example.com/new</link>
      </item>
    </channel></rss>
    """
    collector = RSSCollector(
        _build_source(stop_early_on_known=True),
        http_client=_FakeHttpClient(xml),
        known_canonical_urls={"https://example.com/known"},
    )

    articles = await collector.collect()

    assert articles == []
    assert collector.last_items_total == 2


@pytest.mark.asyncio
async def test_rss_collector_isolates_item_level_parse_failures() -> None:
    xml = """
    <rss><channel>
      <item>
        <title>Broken</title>
        <link>https://example.com/broken</link>
      </item>
      <item>
        <title>Healthy</title>
        <link>https://example.com/healthy</link>
      </item>
    </channel></rss>
    """
    collector = RSSCollector(
        _build_source(),
        http_client=_FakeHttpClient(xml),
    )

    original_parse_item = collector._parse_item

    def flaky_parse_item(item):
        title = item.find("title", recursive=False).get_text(strip=True)
        if title == "Broken":
            raise ValueError("synthetic parse failure")
        return original_parse_item(item)

    collector._parse_item = flaky_parse_item  # type: ignore[method-assign]

    articles = await collector.collect()

    assert len(articles) == 1
    assert articles[0].title == "Healthy"
    assert collector.last_parse_errors == 1


@pytest.mark.asyncio
async def test_rss_collector_sends_conditional_headers_when_available() -> None:
    xml = "<rss><channel></channel></rss>"
    http_client = _FakeHttpClient(
        xml,
        headers={"ETag": '"etag-v2"', "Last-Modified": "Sat, 11 Apr 2026 10:00:00 GMT"},
    )
    collector = RSSCollector(
        _build_source(
            supports_etag=True,
            supports_last_modified=True,
            etag_value='"etag-v1"',
            last_modified_value="Sat, 11 Apr 2026 09:00:00 GMT",
        ),
        http_client=http_client,
    )

    articles = await collector.collect()

    assert articles == []
    assert http_client.last_headers["If-None-Match"] == '"etag-v1"'
    assert http_client.last_headers["If-Modified-Since"] == "Sat, 11 Apr 2026 09:00:00 GMT"
    assert collector.last_received_etag == '"etag-v2"'
    assert collector.last_received_last_modified == "Sat, 11 Apr 2026 10:00:00 GMT"


@pytest.mark.asyncio
async def test_rss_collector_returns_empty_on_304_not_modified() -> None:
    xml = "<rss><channel><item><title>Ignored</title></item></channel></rss>"
    http_client = _FakeHttpClient(
        xml,
        status_code=304,
        headers={"ETag": '"etag-v1"', "Last-Modified": "Sat, 11 Apr 2026 10:00:00 GMT"},
    )
    collector = RSSCollector(
        _build_source(
            supports_etag=True,
            etag_value='"etag-v1"',
        ),
        http_client=http_client,
    )

    articles = await collector.collect()

    assert articles == []
    assert collector.last_was_not_modified is True
    assert collector.last_http_status == 304
    assert collector.last_response_bytes == 0
    assert collector.last_items_total == 0


@pytest.mark.asyncio
async def test_rss_collector_returns_empty_on_same_last_build_date() -> None:
    xml = """
    <rss><channel>
      <lastBuildDate>Sat, 11 Apr 2026 10:00:00 GMT</lastBuildDate>
      <item>
        <title>Ignored</title>
        <link>https://example.com/ignored</link>
      </item>
    </channel></rss>
    """
    collector = RSSCollector(
        _build_source(
            has_last_build_date=True,
            last_build_date_value="Sat, 11 Apr 2026 10:00:00 GMT",
        ),
        http_client=_FakeHttpClient(xml),
    )

    articles = await collector.collect()

    assert articles == []
    assert collector.last_was_same_build_date is True
    assert collector.last_received_last_build_date == "Sat, 11 Apr 2026 10:00:00 GMT"
    assert collector.last_items_total == 0


@pytest.mark.asyncio
async def test_rss_collector_sorts_items_before_stop_early_on_known() -> None:
    xml = """
    <rss><channel>
      <item>
        <title>Known older</title>
        <link>https://example.com/known</link>
        <pubDate>Sat, 11 Apr 2026 09:00:00 GMT</pubDate>
      </item>
      <item>
        <title>Newer story</title>
        <link>https://example.com/new</link>
        <pubDate>Sat, 11 Apr 2026 10:00:00 GMT</pubDate>
      </item>
    </channel></rss>
    """
    collector = RSSCollector(
        _build_source(stop_early_on_known=True),
        http_client=_FakeHttpClient(xml),
        known_canonical_urls={"https://example.com/known"},
    )

    articles = await collector.collect()

    assert len(articles) == 1
    assert articles[0].canonical_url == "https://example.com/new"


@pytest.mark.asyncio
async def test_rss_collector_logs_data_missing_item_errors() -> None:
    xml = """
    <rss><channel>
      <item>
        <description>No title and link</description>
      </item>
    </channel></rss>
    """
    collector = RSSCollector(
        _build_source(),
        http_client=_FakeHttpClient(xml),
    )

    articles = await collector.collect()

    assert articles == []
    assert collector.last_item_failures == 1
    assert collector.last_item_errors[0]["error_type"] == "data_missing"


@pytest.mark.asyncio
async def test_rss_collector_logs_date_parse_without_dropping_article() -> None:
    xml = """
    <rss><channel>
      <item>
        <title>Date issue</title>
        <link>https://example.com/date-issue</link>
        <pubDate>not-a-real-date</pubDate>
      </item>
    </channel></rss>
    """
    collector = RSSCollector(
        _build_source(),
        http_client=_FakeHttpClient(xml),
    )

    articles = await collector.collect()

    assert len(articles) == 1
    assert articles[0].published_at is None
    assert articles[0].date_inferred is True
    assert collector.last_date_parse_warnings == 1
    assert collector.last_item_errors[0]["error_type"] == "date_parse"
