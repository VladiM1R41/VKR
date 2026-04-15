"""Tests for Layer 2 keyword extraction (YAKE)."""

import pytest

from jarvis.processing.nlp.keywords import extract_keywords


class TestExtractKeywords:
    """Тесты извлечения ключевых слов."""

    def test_basic_extraction(self):
        """Должен извлечь ключевые фразы из новостного текста."""
        text = (
            "Центральный банк России повысил ключевую ставку на 200 базисных пунктов. "
            "Инфляция продолжает расти, а экономический рост замедляется. "
            "Регулятор принял решение в условиях санкционного давления."
        )
        results = extract_keywords(text)
        # Должен найти хотя бы 1 ключевую фразу
        assert len(results) >= 1
        # Текст одной из фраз должен быть непустым
        assert all(r.text.strip() for r in results)

    def test_short_text_returns_empty(self):
        """Слишком короткий текст (< 20 символов) не должен обрабатываться."""
        results = extract_keywords("ЦБ")
        assert results == []

    def test_empty_text_returns_empty(self):
        results = extract_keywords("")
        assert results == []

    def test_results_sorted_by_score(self):
        """Результаты должны быть отсортированы по score (лучшие первые)."""
        text = "Экономика России растёт. ВВП увеличивается. Инфляция снижается. " * 5
        results = extract_keywords(text)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i].score <= results[i + 1].score

    def test_filters_garbage(self):
        """Чисто пунктуация и мусор не должны попадать в результаты."""
        text = "... !!! ??? --- "
        results = extract_keywords(text)
        for r in results:
            assert r.text.strip()
            assert len(r.text) >= 2
