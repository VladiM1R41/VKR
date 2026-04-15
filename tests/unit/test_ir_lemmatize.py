"""Tests for Layer 2 IR lemmatization (PyMorphy3)."""

import pytest

from jarvis.processing.ir.lemmatize import (
    extract_bigrams,
    extract_unigrams,
    lemmatize_text,
    normalize_yo,
)


class TestNormalizeYo:
    """Тесты нормализации буквы Ё."""

    def test_replace_yo(self):
        assert normalize_yo("ещё") == "еще"
        assert normalize_yo("всё") == "все"
        assert normalize_yo("Ёжик") == "Ежик"

    def test_no_yo_unchanged(self):
        assert normalize_yo("привет") == "привет"


class TestLemmatize:
    """Тесты лемматизации русского текста."""

    def test_noun_lemmatization(self):
        """Существительные должны лемматизироваться."""
        result = lemmatize_text("ставки")
        assert "ставка" in result

    def test_verb_lemmatization(self):
        """Глаголы должны лемматизироваться."""
        result = lemmatize_text("сказал")
        assert "сказать" in result

    def test_adjective_lemmatization(self):
        """Прилагательные должны лемматизироваться."""
        result = lemmatize_text("ключевая")
        assert "ключевой" in result

    def test_empty_text(self):
        assert lemmatize_text("") == ""

    def test_lowercase_output(self):
        """Результат должен быть в нижнем регистре."""
        result = lemmatize_text("Путин")
        assert result == result.lower()

    def test_yo_normalization(self):
        """Ё должна заменяться на Е перед лемматизацией."""
        result = lemmatize_text("ещё")
        # Должно работать корректно с «еще» вместо «ещё»
        assert isinstance(result, str)
        assert "ё" not in result


class TestUnigrams:
    """Тесты извлечения унисграмм."""

    def test_basic_unigrams(self):
        unigrams = extract_unigrams("ЦБ повысил ставку")
        assert len(unigrams) >= 2  # как минимум 2 слова

    def test_filters_short_tokens(self):
        """Токены короче 2 символов должны фильтроваться."""
        unigrams = extract_unigrams("а я б в")
        # Все токены < 2 символов отфильтрованы
        for u in unigrams:
            assert len(u) >= 2


class TestBigrams:
    """Тесты извлечения биграмм."""

    def test_basic_bigrams(self):
        bigrams = extract_bigrams("ключевая ставка цб")
        assert len(bigrams) >= 1  # хотя бы одна биграмма

    def test_no_cross_sentence(self):
        """Биграммы не должны пересекать границы предложений."""
        text = "ЦБ повысил. Инфляция растёт."
        bigrams = extract_bigrams(text)
        # ("повысил", "инфляция") не должно быть — это разные предложения
        for b1, b2 in bigrams:
            assert not (b1 == "повысить" and b2 == "инфляция")

    def test_empty_text(self):
        bigrams = extract_bigrams("")
        assert bigrams == []
