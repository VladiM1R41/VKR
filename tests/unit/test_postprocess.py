from jarvis.ingestion.extraction.postprocess import apply_postprocess_rules, apply_pre_extraction_rules


def test_remove_lines_starting_with_for_bfm_noise() -> None:
    content = "Лента новостей\nОсновной текст статьи\nВсе новости\nФинальный абзац"
    rules = [{"type": "remove_lines_starting_with", "prefixes": ["Лента новостей", "Все новости"]}]

    cleaned_content, _ = apply_postprocess_rules(content=content, snippet_lead=None, rules=rules)

    assert cleaned_content == "Основной текст статьи\nФинальный абзац"


def test_pre_extraction_decompose_selector() -> None:
    html = "<html><body><aside class='sidebar'>Шум</aside><article><p>Полезный текст</p></article></body></html>"
    rules = [{"type": "bs4_decompose_selector", "selector": "aside.sidebar"}]

    cleaned_html = apply_pre_extraction_rules(html, rules)

    assert "Шум" not in cleaned_html
    assert "Полезный текст" in cleaned_html


def test_html_unescape_postprocess_on_snippet() -> None:
    rules = [{"type": "html_unescape", "fields": ["snippet_lead"]}]

    _, snippet = apply_postprocess_rules(content=None, snippet_lead="Tom &amp; Jerry", rules=rules)

    assert snippet == "Tom & Jerry"


def test_regex_strip_tail_respects_flags_contract() -> None:
    rules = [{"type": "regex_strip_tail", "pattern": r"stay tuned.*$", "flags": "si"}]

    cleaned_content, _ = apply_postprocess_rules(
        content="Main text\nSTAY TUNED for more updates",
        snippet_lead=None,
        rules=rules,
    )

    assert cleaned_content == "Main text"


def test_remove_lines_matching_supports_patterns_list() -> None:
    rules = [
        {
            "type": "remove_lines_matching",
            "patterns": [r"^\s*Лента новостей\s*$", r"^\s*Все новости\s*$"],
        }
    ]

    cleaned_content, _ = apply_postprocess_rules(
        content="Лента новостей\nОсновной текст\nВсе новости\nФинал",
        snippet_lead=None,
        rules=rules,
    )

    assert cleaned_content == "Основной текст\nФинал"


def test_pre_extraction_decompose_figure_with_data_attr_contract_key() -> None:
    html = "<figure data-turbo-ad-id='ad1'></figure><p>Полезный текст</p>"
    rules = [{"type": "bs4_decompose_figures_with_data_attr", "data_attr": "data-turbo-ad-id"}]

    cleaned_html = apply_pre_extraction_rules(html, rules)

    assert "data-turbo-ad-id" not in cleaned_html
    assert "Полезный текст" in cleaned_html
