from bs4 import BeautifulSoup

from jarvis.ingestion.extraction.rss_fulltext import extract_rss_fulltext


def test_yandex_fulltext_keeps_inline_links_inside_sentence() -> None:
    xml = """
    <item>
      <description><![CDATA[Lead]]></description>
      <yandex:full-text><![CDATA[
        <p>The TV channel <a href="https://example.com">Al Jazeera</a> cited medical sources.</p>
        <p>Claire San Filippo <a href="https://example.com/quote">said</a>, that the situation remains severe.</p>
      ]]></yandex:full-text>
    </item>
    """
    item = BeautifulSoup(xml, "xml").find("item")

    result = extract_rss_fulltext(
        item=item,
        method="rss_yandex_fulltext",
        config={"full_text_tag": "yandex:full-text", "postprocess_rules": []},
        full_text_html=None,
        description_html="Lead",
    )

    assert (
        result["content"]
        == "The TV channel Al Jazeera cited medical sources.\n"
        "Claire San Filippo said, that the situation remains severe."
    )
