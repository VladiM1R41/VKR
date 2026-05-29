from jarvis.processing.services.entity_profiles import _trend_direction


def test_trend_direction_suppresses_one_off_new_entities() -> None:
    assert _trend_direction(1.0, 0.0, source_diversity=1) == "stable"


def test_trend_direction_requires_source_diversity_for_new_spikes() -> None:
    assert _trend_direction(10.0, 0.0, source_diversity=1) == "stable"
    assert _trend_direction(10.0, 0.0, source_diversity=2) == "ascending"


def test_trend_direction_keeps_real_growth_and_decline() -> None:
    assert _trend_direction(10.0, 5.0, source_diversity=2) == "ascending"
    assert _trend_direction(2.0, 5.0, source_diversity=1) == "descending"
