from types import SimpleNamespace

from bs4 import BeautifulSoup

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
        config=config,
        default_info_type="daily",
        default_content_type="news",
    )


def test_rss_collector_parses_top_level_link_not_related_link() -> None:
    raw = """
    <item>
      <title>Основная статья</title>
      <link>https://example.com/main-story</link>
      <pubDate>Tue, 07 Apr 2026 19:25:28 +0300</pubDate>
      <description><![CDATA[<p>Короткий лид.</p>]]></description>
      <yandex:related>
        <link url="https://example.com/related-story">Связанная статья</link>
      </yandex:related>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(_build_source(), http_client=None)

    article = collector._parse_item(item)

    assert article is not None
    assert article.url == "https://example.com/main-story"
    assert article.canonical_url == "https://example.com/main-story"
    assert article.title == "Основная статья"


def test_rss_collector_uses_pdalink_when_configured() -> None:
    raw = """
    <item>
      <title>ТАСС материал</title>
      <link>https://example.com/wrong-link</link>
      <pdalink>https://example.com/right-link</pdalink>
      <pubDate>Tue, 07 Apr 2026 19:25:28 +0300</pubDate>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(_build_source(url_source_field="pdalink"), http_client=None)

    article = collector._parse_item(item)

    assert article is not None
    assert article.url == "https://example.com/right-link"


def test_rss_collector_builds_snippet_from_content_when_description_empty() -> None:
    raw = """
    <rss><channel>
      <item>
        <title>iXBT test</title>
        <link>https://www.ixbt.com/news/test.html</link>
        <description><![CDATA[]]></description>
        <encoded><![CDATA[<p>Это достаточно длинный первый абзац для snippet fallback.</p><p>Второй абзац.</p>]]></encoded>
      </item>
    </channel></rss>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(
        _build_source(
            full_text_method="rss_description_html",
            full_text_tag="encoded",
        ),
        http_client=None,
    )
    collector.source.name = "iXBT.com"
    collector.source.id = 14

    article = collector._parse_item(item)

    assert article is not None
    assert article.content is not None
    assert article.snippet_lead == "Это достаточно длинный первый абзац для snippet fallback."
