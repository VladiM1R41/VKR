from bs4 import BeautifulSoup

from jarvis.ingestion.extraction.rss_fulltext import extract_rss_fulltext


def test_aif_turbo_structured_extracts_text_headings_and_inline_images() -> None:
    item_xml = """
    <item>
      <description><![CDATA[Lead text]]></description>
      <turbo:content><![CDATA[
        <header>
          <figure><img src="https://example.com/hero.jpg"/><figcaption>Hero caption</figcaption></figure>
          <h1>Main title</h1>
        </header>
        <ExtRetellWidget></ExtRetellWidget>
        <h2>First section</h2>
        <p>First paragraph.</p>
        <figure><img src="https://example.com/body-1.jpg"/><figcaption>Body image</figcaption></figure>
        <p>
          Paragraph with slider.
          <div data-block="slider">
            <figure><img src="https://example.com/slider-1.jpg"/><figcaption>Slider one</figcaption></figure>
            <figure><img src="https://example.com/slider-2.jpg"/><figcaption>Slider two</figcaption></figure>
          </div>
        </p>
        <figure data-turbo-ad-id="first_ad_place"></figure>
        <Ext24smiWidget></Ext24smiWidget>
      ]]></turbo:content>
      <yandex:full-text><![CDATA[<p>Fallback paragraph.</p>]]></yandex:full-text>
    </item>
    """
    item = BeautifulSoup(item_xml, "xml").find("item")

    result = extract_rss_fulltext(
        item=item,
        method="rss_turbo_structured",
        config={
            "full_text_tag": "turbo:content",
            "fallback_full_text_tag": "yandex:full-text",
            "postprocess_rules": [
                {"type": "bs4_decompose_selector", "selector": "header"},
                {"type": "bs4_decompose_selector", "selector": "ExtRetellWidget"},
                {"type": "bs4_decompose_selector", "selector": "Ext24smiWidget"},
                {"type": "bs4_decompose_figures_with_data_attr", "data_attr": "data-turbo-ad-id"},
            ],
        },
        full_text_html="""
        <header>
          <figure><img src="https://example.com/hero.jpg"/><figcaption>Hero caption</figcaption></figure>
          <h1>Main title</h1>
        </header>
        <ExtRetellWidget></ExtRetellWidget>
        <h2>First section</h2>
        <p>First paragraph.</p>
        <figure><img src="https://example.com/body-1.jpg"/><figcaption>Body image</figcaption></figure>
        <p>
          Paragraph with slider.
          <div data-block="slider">
            <figure><img src="https://example.com/slider-1.jpg"/><figcaption>Slider one</figcaption></figure>
            <figure><img src="https://example.com/slider-2.jpg"/><figcaption>Slider two</figcaption></figure>
          </div>
        </p>
        <figure data-turbo-ad-id="first_ad_place"></figure>
        <Ext24smiWidget></Ext24smiWidget>
        """,
        description_html="Lead text",
        thumbnail_url="https://example.com/hero.jpg",
    )

    assert result["content"] == "First section\n\nFirst paragraph.\n\nParagraph with slider."
    assert result["content_status"] == "ok"
    assert result["extraction_method"] == "rss_turbo_structured"
    assert result["extra"]["turbo_headings"] == ["First section"]
    assert result["extra"]["inline_images"] == [
        {"type": "image", "src": "https://example.com/body-1.jpg", "caption": "Body image"},
        {"type": "image", "src": "https://example.com/slider-1.jpg", "caption": "Slider one"},
        {"type": "image", "src": "https://example.com/slider-2.jpg", "caption": "Slider two"},
    ]


def test_aif_turbo_structured_falls_back_to_yandex_fulltext_when_turbo_is_empty() -> None:
    item_xml = """
    <item>
      <description><![CDATA[Lead text]]></description>
      <yandex:full-text><![CDATA[<p>Fallback paragraph.</p><p>Second fallback paragraph.</p>]]></yandex:full-text>
    </item>
    """
    item = BeautifulSoup(item_xml, "xml").find("item")

    result = extract_rss_fulltext(
        item=item,
        method="rss_turbo_structured",
        config={
            "fallback_full_text_tag": "yandex:full-text",
            "postprocess_rules": [],
        },
        full_text_html=None,
        description_html="Lead text",
        thumbnail_url=None,
    )

    assert result["content"] == "Fallback paragraph.\nSecond fallback paragraph."
    assert result["extraction_method"] == "rss_yandex_fulltext_fallback"
