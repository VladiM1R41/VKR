"""Tests for Layer 3 query autocorrect."""

import pytest

from jarvis.retrieval.services.query_autocorrect import (
    AutocorrectResult,
    _trigrams,
    _jaccard,
    _levenshtein,
    autocorrect_query,
)


class TestTrigrams:
    """Тесты извлечения триграмм."""

    def test_trigrams_basic(self):
        trigrams = _trigrams("test")
        assert "^te" in trigrams
        assert "est" in trigrams
        assert "st$" in trigrams  # last trigram ends with $

    def test_trigrams_short(self):
        trigrams = _trigrams("ab")
        # "^ab", "ab$" — минимум 1
        assert len(trigrams) >= 1

    def test_trigrams_empty(self):
        trigrams = _trigrams("")
        assert trigrams == set()  # empty string → no trigrams


class TestJaccard:
    """Тесты коэффициента Жаккара."""

    def test_identical_sets(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == pytest.approx(1.0)

    def test_disjoint_sets(self):
        assert _jaccard({"a", "b"}, {"c", "d"}) == pytest.approx(0.0)

    def test_partial_overlap(self):
        # {a, b} ∩ {b, c} = {b} → 1/3
        assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1.0 / 3.0)

    def test_empty_sets(self):
        assert _jaccard(set(), set()) == 0.0


class TestLevenshtein:
    """Тесты расстояния Левенштейна."""

    def test_identical(self):
        assert _levenshtein("test", "test") == 0

    def test_one_insertion(self):
        assert _levenshtein("test", "tests") == 1

    def test_one_substitution(self):
        assert _levenshtein("test", "tent") == 1

    def test_empty(self):
        assert _levenshtein("", "abc") == 3

    def test_symmetric(self):
        assert _levenshtein("abc", "abd") == _levenshtein("abd", "abc")


class TestAutocorrectQuery:
    """Тесты автокоррекции запросов."""

    def test_no_correction_needed(self):
        result = autocorrect_query("")
        assert not result.was_corrected
        assert result.original == ""
        assert result.corrected == ""

    def test_result_is_dataclass(self):
        result = autocorrect_query("test")
        assert isinstance(result, AutocorrectResult)
        assert hasattr(result, "original")
        assert hasattr(result, "corrected")
        assert hasattr(result, "was_corrected")
