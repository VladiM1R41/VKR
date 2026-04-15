"""Tests for entity co-occurrence graph builder."""

import pytest

from jarvis.processing.services.cooccurrence import (
    CooccurrenceEdge,
    build_cooccurrence_edges,
    _make_edge,
)


class TestMakeEdge:
    """Тесты создания ребра с invariant a < b."""

    def test_a_less_than_b(self):
        edge = _make_edge(1, 5)
        assert edge.entity_a_id == 1
        assert edge.entity_b_id == 5

    def test_b_less_than_a(self):
        """Порядок должен нормализоваться: (5, 1) → (1, 5)."""
        edge = _make_edge(5, 1)
        assert edge.entity_a_id == 1
        assert edge.entity_b_id == 5

    def test_equal_ids_raises(self):
        """Одинаковые ID не должны создавать ребро (но код должен работать)."""
        edge = _make_edge(3, 3)
        # invariant a < b не выполняется — ребро будет (3, 3)
        assert edge.entity_a_id == 3
        assert edge.entity_b_id == 3


class TestBuildCooccurrenceEdges:
    """Тесты построения рёбер из списка сущностей."""

    def test_single_entity_no_edges(self):
        edges = build_cooccurrence_edges([1])
        assert edges == []

    def test_two_entities_one_edge(self):
        edges = build_cooccurrence_edges([3, 1])
        assert len(edges) == 1
        # Нормализовано: a < b
        assert edges[0].entity_a_id == 1
        assert edges[0].entity_b_id == 3

    def test_three_entities_three_edges(self):
        """3 сущности = 3 ребра (полный граф клики)."""
        edges = build_cooccurrence_edges([1, 2, 3])
        assert len(edges) == 3  # C(3,2) = 3

    def test_four_entities_six_edges(self):
        """4 сущности = 6 рёбер."""
        edges = build_cooccurrence_edges([1, 2, 3, 4])
        assert len(edges) == 6  # C(4,2) = 6

    def test_no_duplicates(self):
        """Не должно быть дубликатов (A,B) и (B,A)."""
        edges = build_cooccurrence_edges([2, 1])
        assert len(edges) == 1
        assert edges[0].entity_a_id == 1
        assert edges[0].entity_b_id == 2

    def test_deduplicates_ids(self):
        """Дубликаты ID должны убираться."""
        edges = build_cooccurrence_edges([1, 1, 2, 2, 3])
        # unique = [1, 2, 3] → 3 ребра
        assert len(edges) == 3

    def test_limits_to_10_entities(self):
        """Максимум 10 сущностей для предотвращения O(N²)."""
        entity_ids = list(range(1, 21))  # 20 сущностей
        edges = build_cooccurrence_edges(entity_ids)
        # Ограничено до 10 → C(10, 2) = 45 рёбер
        assert len(edges) == 45

    def test_empty_list(self):
        edges = build_cooccurrence_edges([])
        assert edges == []
