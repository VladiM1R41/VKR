from bs4 import BeautifulSoup

from jarvis.ingestion.extraction.rss_fulltext import extract_rss_fulltext


def test_extract_yandex_fulltext_returns_clean_text() -> None:
    xml = """
    <item>
      <description><![CDATA[Краткий лид]]></description>
      <yandex:full-text><![CDATA[<p>Первый абзац</p><p>Второй абзац</p>]]></yandex:full-text>
    </item>
    """
    item = BeautifulSoup(xml, "xml").find("item")

    result = extract_rss_fulltext(
        item=item,
        method="rss_yandex_fulltext",
        config={"full_text_tag": "yandex:full-text", "postprocess_rules": []},
        full_text_html=None,
        description_html="Краткий лид",
    )

    assert result["content"] == "Первый абзац\nВторой абзац"
    assert result["content_status"] == "ok"
    assert result["extraction_method"] == "rss_yandex_fulltext"


def test_extract_rbc_fulltext_strips_tail() -> None:
    xml = """
    <item>
      <description><![CDATA[Лид]]></description>
      <rbc_news:full-text><![CDATA[
        <p>Основной текст</p>
        <p>Оставайтесь на связи с РБК в Max.</p>
      ]]></rbc_news:full-text>
    </item>
    """
    item = BeautifulSoup(xml, "xml").find("item")

    result = extract_rss_fulltext(
        item=item,
        method="rss_custom_namespace",
        config={
            "full_text_tag": "rbc_news:full-text",
            "postprocess_rules": [
                {"type": "regex_strip_tail", "pattern": r"\s*Оставайтесь на связи с РБК.*$"}
            ],
        },
        full_text_html=None,
        description_html="Лид",
    )

    assert result["content"] == "Основной текст"
    assert result["content_status"] == "ok"


def test_extract_ixbt_description_html_preserves_thumbnail_and_removes_seealso() -> None:
    html = """
    <p>Первый абзац</p>
    <a href="https://www.ixbt.com/news/x.html?utm_campaign=seealso">Связанный материал</a>
    <a href="https://www.ixbt.com/img/large.jpg"><figure><img src="https://www.ixbt.com/img/thumb.jpg"/></figure></a>
    Фото NASA
    <p>Второй абзац</p>
    """

    result = extract_rss_fulltext(
        item=BeautifulSoup("<item></item>", "xml").find("item"),
        method="rss_description_html",
        config={
            "postprocess_rules": [
                {"type": "bs4_decompose_selector", "selector": "a[href*='utm_campaign=seealso']"},
                {"type": "bs4_decompose_selector", "selector": "a:has(figure)"},
                {"type": "bs4_decompose_selector", "selector": "figure"},
                {"type": "remove_lines_starting_with", "prefixes": ["Фото", "Создано", "Photo"]}
            ]
        },
        full_text_html=None,
        description_html=html,
    )

    assert result["content"] == "Первый абзац\nВторой абзац"
    assert result["extra"]["thumbnail"] == "https://www.ixbt.com/img/thumb.jpg"
