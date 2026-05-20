"""Tests for Layer 2 embedding runtime helpers."""

from jarvis.processing.services.embedding_runtime import (
    EmbeddingOutput,
    _compute_sparse_tfidf,
    _encode_with_flagembedding,
    _stable_sparse_index,
    encode_texts,
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


def test_auto_backend_falls_back_to_sentence_transformers(monkeypatch) -> None:
    import jarvis.processing.services.embedding_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: type("Settings", (), {"processing_embedding_backend": "auto"})(),
    )
    monkeypatch.setattr(
        runtime,
        "_encode_with_flagembedding",
        lambda texts: (_ for _ in ()).throw(RuntimeError("missing flagembedding")),
    )
    monkeypatch.setattr(
        runtime,
        "_encode_with_sentence_transformers",
        lambda texts, sparse_texts=None: [EmbeddingOutput([1.0], [1], [0.5]) for _ in texts],
    )

    result = encode_texts(["hello"])

    assert result == [EmbeddingOutput([1.0], [1], [0.5])]


def test_flagembedding_backend_accepts_numpy_dense_vectors(monkeypatch) -> None:
    import numpy as np
    import jarvis.processing.services.embedding_runtime as runtime

    class FakeFlagEmbeddingModel:
        def encode(self, texts, *, return_dense, return_sparse, return_colbert_vecs):
            assert return_dense is True
            assert return_sparse is True
            assert return_colbert_vecs is False
            return {
                "dense_vecs": np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
                "lexical_weights": [{"10": np.float32(0.5)}, {"20": np.float32(0.7)}],
            }

    monkeypatch.setattr(runtime, "_load_flagembedding_bge_m3", lambda: FakeFlagEmbeddingModel())

    result = _encode_with_flagembedding(["first", "second"])

    assert result == [
        EmbeddingOutput([0.10000000149011612, 0.20000000298023224], [10], [0.5]),
        EmbeddingOutput([0.30000001192092896, 0.4000000059604645], [20], [0.7]),
    ]
