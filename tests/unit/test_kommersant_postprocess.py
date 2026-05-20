from jarvis.ingestion.extraction.postprocess import apply_postprocess_rules
from tests.conftest import build_source_stub


def test_kommersant_seed_postprocess_removes_company_news_tail_only() -> None:
    for source_key in ("kommersant_news", "kommersant_corp", "kommersant_main"):
        source = build_source_stub(source_key)
        rules = source.config["postprocess_rules"]

        cleaned_content, _ = apply_postprocess_rules(
            content=(
                "\u041f\u0435\u0440\u0432\u044b\u0439 \u043f\u043e\u043b\u0435\u0437\u043d\u044b\u0439 \u0430\u0431\u0437\u0430\u0446.\n\n"
                "\u0424\u0438\u043d\u0430\u043b\u044c\u043d\u044b\u0439 \u043f\u043e\u043b\u0435\u0437\u043d\u044b\u0439 \u0430\u0431\u0437\u0430\u0446.\n\n"
                "\u041d\u043e\u0432\u043e\u0441\u0442\u0438 \u043a\u043e\u043c\u043f\u0430\u043d\u0438\u0439"
            ),
            snippet_lead=None,
            rules=rules,
        )

        assert (
            cleaned_content
            == "\u041f\u0435\u0440\u0432\u044b\u0439 \u043f\u043e\u043b\u0435\u0437\u043d\u044b\u0439 \u0430\u0431\u0437\u0430\u0446.\n"
            "\u0424\u0438\u043d\u0430\u043b\u044c\u043d\u044b\u0439 \u043f\u043e\u043b\u0435\u0437\u043d\u044b\u0439 \u0430\u0431\u0437\u0430\u0446."
        )
