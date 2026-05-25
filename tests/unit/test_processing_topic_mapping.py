from jarvis.processing.nlp import topics
from jarvis.processing.services.topic_mapping import (
    classify_topics_lexical,
    map_source_categories,
    normalize_category_label,
    resolve_topics,
)


def test_normalize_category_label_collapses_noise() -> None:
    assert normalize_category_label("  Economy!!!   ") == "economy"


def test_map_source_categories_matches_expected_topics() -> None:
    matches = map_source_categories(["economy", "AI"])
    names = {match.name for match in matches}

    assert "Экономика" in names
    assert "Технологии" in names
    assert all(match.confidence == 0.95 for match in matches)


def test_lexical_topics_cover_uncategorized_finance_text() -> None:
    matches = classify_topics_lexical(
        title="Банк России сохранил ключевую ставку",
        body="ЦБ отметил риски инфляции и денежно-кредитной политики.",
    )
    names = {match.name for match in matches}

    assert "Финансы" in names
    assert "Технологии" not in names


def test_lexical_topics_cover_security_news_without_categories() -> None:
    matches = classify_topics_lexical(
        title="В ЛНР пострадавших после удара ВСУ эвакуировали в Москву",
        body="После атаки БПЛА по общежитию колледжа несколько человек остаются в больницах.",
    )
    names = {match.name for match in matches}

    assert "Безопасность" in names


def test_short_markers_do_not_match_inside_unrelated_words() -> None:
    matches = classify_topics_lexical(
        title="Российский танк сорвал ротацию ВСУ в Сумской области",
        body="Операторы БПЛА обнаружили позиции противника.",
    )
    names = {match.name for match in matches}

    assert "Безопасность" in names
    assert "Транспорт" not in names


def test_resolve_topics_keeps_rule_based_unchanged_without_zero_shot(monkeypatch) -> None:
    def fail_zero_shot(text: str):
        raise AssertionError("zero-shot should not be called when lexical or rule topics exist")

    monkeypatch.setattr("jarvis.processing.nlp.topics.classify_topics_zero_shot", fail_zero_shot)

    matches = resolve_topics(
        source_categories=["economy"],
        title="Банк России сохранил ставку",
        body="Инфляция и финансовые рынки остаются в фокусе.",
    )
    names = {match.name for match in matches}

    assert names == {"Экономика"}


def test_zero_shot_rejects_weak_top_score(monkeypatch) -> None:
    class FakeClassifier:
        def __call__(self, text, *, candidate_labels, multi_label):
            return {
                "labels": ["Финансы", "Бизнес"],
                "scores": [0.58, 0.57],
            }

    monkeypatch.setattr(topics, "_load_zero_shot_model", lambda: FakeClassifier())

    assert topics.classify_topics_zero_shot("спорный короткий текст") == []
