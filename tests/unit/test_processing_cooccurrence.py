"""Tests for entity co-occurrence graph builder."""

import pytest

from jarvis.processing.services.cooccurrence import build_cooccurrence_edges, _make_edge


class TestMakeEdge:
    """Edge normalization tests."""

    def test_a_less_than_b(self):
        edge = _make_edge(1, 5)
        assert edge.entity_a_id == 1
        assert edge.entity_b_id == 5

    def test_b_less_than_a(self):
        edge = _make_edge(5, 1)
        assert edge.entity_a_id == 1
        assert edge.entity_b_id == 5

    def test_equal_ids_raises(self):
        with pytest.raises(ValueError):
            _make_edge(3, 3)


class TestBuildCooccurrenceEdges:
    """Build clique edges for article entities."""

    def test_single_entity_no_edges(self):
        assert build_cooccurrence_edges([1]) == []

    def test_two_entities_one_edge(self):
        edges = build_cooccurrence_edges([3, 1])
        assert len(edges) == 1
        assert edges[0].entity_a_id == 1
        assert edges[0].entity_b_id == 3

    def test_three_entities_three_edges(self):
        assert len(build_cooccurrence_edges([1, 2, 3])) == 3

    def test_four_entities_six_edges(self):
        assert len(build_cooccurrence_edges([1, 2, 3, 4])) == 6

    def test_no_duplicates(self):
        edges = build_cooccurrence_edges([2, 1])
        assert len(edges) == 1
        assert edges[0].entity_a_id == 1
        assert edges[0].entity_b_id == 2

    def test_deduplicates_ids(self):
        assert len(build_cooccurrence_edges([1, 1, 2, 2, 3])) == 3

    def test_limits_to_10_entities(self):
        assert len(build_cooccurrence_edges(list(range(1, 21)))) == 45

    def test_empty_list(self):
        assert build_cooccurrence_edges([]) == []
