from jarvis.processing.services.topic_mapping import map_source_categories, normalize_category_label


def test_normalize_category_label_collapses_noise() -> None:
    assert normalize_category_label("  Economy!!!   ") == "economy"


def test_map_source_categories_matches_expected_topics() -> None:
    matches = map_source_categories(["economy", "AI"])
    names = {match.name for match in matches}

    assert "Экономика" in names
    assert "Технологии" in names
    assert all(match.confidence == 0.95 for match in matches)
