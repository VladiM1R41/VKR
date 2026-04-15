from types import SimpleNamespace

from bs4 import BeautifulSoup

from jarvis.ingestion.collectors.rss import RSSCollector


def _build_source(**config_overrides):
    config = {
        "source_key": "test",
        "url_source_field": "link",
        "canonical_keep_params": [],
        "postprocess_rules": [],
    }
    config.update(config_overrides)
    return SimpleNamespace(
        id=1,
        name="Test Source",
        config=config,
        default_info_type="daily",
        default_content_type="news",
    )


def test_rss_collector_uses_source_key_for_rbc_branch() -> None:
    raw = """
    <item>
      <title>РБК статья</title>
      <link>https://rssexport.rbc.ru/wrong</link>
      <pdalink>https://www.rbc.ru/politics/11/04/2026/test</pdalink>
      <rbc_news:type>article</rbc_news:type>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(
        _build_source(
            source_key="rbc",
            url_source_field="pdalink",
        ),
        http_client=None,
    )

    article = collector._parse_item(item)

    assert article is not None
    assert article.canonical_url == "https://rbc.ru/politics/11/04/2026/test"
    assert article.information_type == "daily"
    assert article.content_type == "analysis"


def test_rss_collector_uses_source_key_for_rt_metadata_and_snippet_cleanup() -> None:
    raw = """
    <item>
      <title>RT news</title>
      <link>https://russian.rt.com/world/news/1615698-test?utm_source=rss</link>
      <description><![CDATA[Краткий лид.<br/><a href="https://russian.rt.com/x">Читать далее</a>]]></description>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(
        _build_source(
            source_key="rt",
            postprocess_rules=[
                {
                    "type": "regex_strip_tail",
                    "pattern": "\\s*Читать далее\\.?\\s*$",
                    "fields": ["snippet_lead"],
                }
            ],
        ),
        http_client=None,
    )

    article = collector._parse_item(item)

    assert article is not None
    assert article.snippet_lead == "Краткий лид."
    assert article.extra["rt_section"] == "world"


def test_rss_collector_uses_source_key_for_ixbt_author_cleanup() -> None:
    raw = """
    <item>
      <title>iXBT news</title>
      <link>https://www.ixbt.com/news/test.html</link>
      <author>ivan.petrov@example.com (GameMAG)</author>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(
        _build_source(source_key="ixbt"),
        http_client=None,
    )

    article = collector._parse_item(item)

    assert article is not None
    assert article.extra["author"] == "GameMAG"


def test_rss_collector_marks_breaking_title_via_preclassifier() -> None:
    raw = """
    <item>
      <title>СРОЧНО: важное сообщение</title>
      <link>https://example.com/breaking</link>
      <pubDate>Tue, 07 Apr 2026 19:25:28 +0300</pubDate>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(_build_source(), http_client=None)

    article = collector._parse_item(item)

    assert article is not None
    assert article.information_type == "breaking"
    assert article.extra["information_type_override"] == "pre_classifier_breaking"


def test_rss_collector_stores_kommersant_subtitle_but_keeps_raw_title() -> None:
    raw = """
    <item>
      <title>Основной заголовок // Подзаголовок материала</title>
      <link>https://www.kommersant.ru/doc/1</link>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(
        _build_source(
            source_key="kommersant_main",
            split_title_on=" // ",
        ),
        http_client=None,
    )

    article = collector._parse_item(item)

    assert article is not None
    assert article.title == "Основной заголовок // Подзаголовок материала"
    assert article.extra["subtitle"] == "Подзаголовок материала"


def test_rss_collector_stores_mk_source_host_for_mixed_regional_hosts() -> None:
    raw = """
    <item>
      <title>Региональная новость</title>
      <link>https://spb.mk.ru/incident/2026/04/12/story.html</link>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(
        _build_source(
            source_key="mk",
            mixed_regional_hosts=True,
        ),
        http_client=None,
    )

    article = collector._parse_item(item)

    assert article is not None
    assert article.extra["source_host"] == "spb.mk.ru"


def test_rss_collector_stores_aif_external_signals_in_doc_keys() -> None:
    raw = """
    <item>
      <title>АиФ материал</title>
      <link>https://aif.ru/story/test</link>
      <yandex:theme_tags>story-5189</yandex:theme_tags>
      <yandex:related>
        <link url="https://aif.ru/related/1">Связанная статья</link>
      </yandex:related>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(
        _build_source(
            source_key="aif_news",
            read_theme_tags=True,
            read_related_links=True,
        ),
        http_client=None,
    )

    article = collector._parse_item(item)

    assert article is not None
    assert article.extra["yandex_story_tag"] == "story-5189"
    assert article.extra["source_related_urls"] == ["https://aif.ru/related/1"]
    assert article.extra["source_related_titles"] == ["Связанная статья"]


def test_rss_collector_maps_ria_type_into_check_safe_content_type() -> None:
    raw = """
    <item>
      <title>РИА новость</title>
      <link>https://ria.ru/20260412/test-1.html</link>
      <rian:type>article</rian:type>
      <rian:priority>2</rian:priority>
    </item>
    """
    item = BeautifulSoup(raw, "xml").find("item")
    collector = RSSCollector(
        _build_source(
            source_key="ria",
        ),
        http_client=None,
    )

    article = collector._parse_item(item)

    assert article is not None
    assert article.content_type == "news"
    assert article.extra["source_content_type"] == "article"
    assert article.extra["rian_priority"] == 2
