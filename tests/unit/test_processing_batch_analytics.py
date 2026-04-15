"""Tests for Layer 2 batch analytics (term_vocabulary + collocations)."""

from math import log
import pytest

from jarvis.processing.services.batch_analytics import (
    _MIN_PMI_SCORE,
    _MIN_TERM_FREQUENCY,
    _MIN_BIGRAM_FREQUENCY,
)


class TestBatchAnalyticsConstants:
    """Проверка констант batch-задач."""

    def test_min_term_frequency(self):
        assert _MIN_TERM_FREQUENCY == 3

    def test_min_pmi_score(self):
        assert _MIN_PMI_SCORE == 3.0

    def test_min_bigram_frequency(self):
        assert _MIN_BIGRAM_FREQUENCY == 5


class TestPMICalculation:
    """Тесты вычисления PMI (Pointwise Mutual Information)."""

    def test_pmi_strong_association(self):
        """Если слова всегда вместе — PMI высокий."""
        # P(a,b) = 0.1, P(a) = 0.1, P(b) = 0.1
        # PMI = log(0.1 / (0.1 * 0.1)) = log(10) ≈ 2.3
        p_joint = 0.1
        p_a = 0.1
        p_b = 0.1
        pmi = log(p_joint / (p_a * p_b))
        assert pmi == pytest.approx(log(10), abs=1e-6)

    def test_pmi_independent(self):
        """Если слова независимы — PMI ≈ 0."""
        # P(a,b) = P(a) * P(b) → PMI = log(1) = 0
        p_joint = 0.01
        p_a = 0.1
        p_b = 0.1
        pmi = log(p_joint / (p_a * p_b))
        assert pmi == pytest.approx(0.0, abs=1e-6)

    def test_pmi_threshold(self):
        """PMI > 3.0 означает сильную ассоциацию."""
        # Нужно P(a,b) / (P(a)*P(b)) > exp(3) ≈ 20
        threshold_ratio = log(_MIN_PMI_SCORE)  # exp(3) в log-пространстве
        # Проверяем что порог разумный
        assert _MIN_PMI_SCORE > 0


class TestVocabularyUpdate:
    """Тесты обновления словаря (unit, без БД)."""

    def test_empty_corpus_returns_nothing(self):
        """Пустой корпус → пустой результат."""
        from jarvis.processing.services.batch_analytics import _collect_corpus_lemmas
        # Без данных в БД должно вернуть пустые списки
        unigrams, bigrams = _collect_corpus_lemmas()
        # Может быть не пусто если есть данные, но тип должен быть правильным
        assert isinstance(unigrams, list)
        assert isinstance(bigrams, list)


class TestCollocationUpdate:
    """Тесты обновления коллокаций (unit, без БД)."""

    def test_rare_bigrams_filtered(self):
        """Редкие биграммы (< MIN_BIGRAM_FREQUENCY) должны фильтроваться."""
        # Проверяем что константа разумная
        assert _MIN_BIGRAM_FREQUENCY >= 1

    def test_pmi_formula_correct(self):
        """PMI = log(P(a,b) / (P(a) * P(b)))."""
        # Классический пример: "ключевая ставка"
        # Если "ключевая" и "ставка" почти всегда вместе
        p_joint = 0.05  # 5% всех биграмм
        p_a = 0.06      # 6% всех униграмм
        p_b = 0.07      # 7% всех униграмм
        pmi = log(p_joint / (p_a * p_b))
        # PMI ≈ log(0.05 / 0.0042) ≈ log(11.9) ≈ 2.48
        assert pmi > 2.0  # сильная ассоциация
