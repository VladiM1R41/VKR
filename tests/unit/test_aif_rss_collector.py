from types import SimpleNamespace

from bs4 import BeautifulSoup

from jarvis.ingestion.collectors.rss import RSSCollector


def _build_source(**config_overrides):
    config = {
        "source_key": "aif_news",
        "url_source_field": "link",
        "canonical_keep_params": [],
        "full_text_method": "rss_turbo_structured",
        "full_text_tag": "turbo:content",
        "fallback_full_text_tag": "yandex:full-text",
        "read_theme_tags": True,
        "read_related_links": True,
        "postprocess_rules": [],
    }
    config.update(config_overrides)
    return SimpleNamespace(
        id=17,
        name="AIF News",
        config=config,
        default_info_type="daily",
        default_content_type="news",
    )


def test_aif_collector_reads_related_links_and_theme_tags() -> None:
    raw = """
    <item>
      <title>AIF story</title>
      <link>https://aif.ru/politics/story</link>
      <description><![CDATA[Lead]]></description>
      <pubDate>Tue, 07 Apr 2026 19:25:28 +0300</pubDate>
      <yandex:theme_tags>story-5281</yandex:theme_tags>
      <yandex:related type="infinity">
        <link url="https://aif.ru/related-1" img="https://aif.ru/image-1.jpg">Related one</link>
        <link url="https://aif.ru/related-2">Related two</link>
      </yandex:related>
      <yandex:full-text><![CDATA[<p>Fallback paragraph.</p>]]></yandex:full-text>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(_build_source(), http_client=None)

    article = collector._parse_item(item)

    assert article is not None
    assert article.extra["yandex_story_tag"] == "story-5281"
    assert article.extra["source_related_urls"] == [
        "https://aif.ru/related-1",
        "https://aif.ru/related-2",
    ]
    assert article.extra["source_related_titles"] == [
        "Related one",
        "Related two",
    ]
