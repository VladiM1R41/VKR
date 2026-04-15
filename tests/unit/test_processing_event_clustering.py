"""Tests for Layer 2 event clustering."""

import pytest

from jarvis.processing.services.event_clustering import (
    _cosine_similarity,
    _TEMPORAL_WINDOW_HOURS,
    _SIMILARITY_THRESHOLD,
)


class TestCosineSimilarity:
    """Тесты вычисления cosine similarity."""

    def test_identical_vectors(self):
        """Одинаковые векторы → similarity = 1.0."""
        vec = [1.0, 0.0, 1.0]
        assert _cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """Ортогональные векторы → similarity = 0.0."""
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        """Противоположные векторы → similarity = -1.0."""
        assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_partial_similarity(self):
        """Частичное совпадение → 0 < similarity < 1."""
        score = _cosine_similarity([1.0, 1.0, 0.0], [1.0, 0.0, 0.0])
        assert 0.0 < score < 1.0

    def test_zero_vector(self):
        """Нулевой вектор → similarity = 0."""
        assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == pytest.approx(0.0)

    def test_different_lengths(self):
        """Векторы разной длины — zip обрезает по shorter."""
        from math import sqrt
        # [1,1,1] vs [1,1] → zip даёт [1,1] vs [1,1], но norms считаются от полных
        # dot=2, norm_a=sqrt(3), norm_b=sqrt(2) → 2/(sqrt(3)*sqrt(2))
        expected = 2.0 / (sqrt(3) * sqrt(2))
        score = _cosine_similarity([1.0, 1.0, 1.0], [1.0, 1.0])
        assert score == pytest.approx(expected, abs=1e-6)


class TestClusteringConstants:
    """Проверка констант кластеризации."""

    def test_temporal_window(self):
        assert _TEMPORAL_WINDOW_HOURS == 48

    def test_similarity_threshold(self):
        assert _SIMILARITY_THRESHOLD == 0.75
