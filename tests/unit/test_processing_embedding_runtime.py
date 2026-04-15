"""Tests for Layer 2 embedding runtime helpers."""

from jarvis.processing.services.embedding_runtime import (
    _compute_sparse_tfidf,
    _stable_sparse_index,
)


def test_stable_sparse_index_is_deterministic() -> None:
    first = _stable_sparse_index("ставка")
    second = _stable_sparse_index("ставка")

    assert first == second
    assert isinstance(first, int)


def test_sparse_tfidf_reuses_same_dimension_for_shared_token() -> None:
    shared_index = _stable_sparse_index("ставка")

    indices_a, _ = _compute_sparse_tfidf("ставка инфляция")
    indices_b, _ = _compute_sparse_tfidf("бюджет ставка")

    assert shared_index in indices_a
    assert shared_index in indices_b


def test_sparse_tfidf_is_order_invariant_for_same_term_counts() -> None:
    first = _compute_sparse_tfidf("ставка ставка цб")
    second = _compute_sparse_tfidf("цб ставка ставка")

    assert first == second
