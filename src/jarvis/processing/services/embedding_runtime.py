"""Embedding runtime helpers for Layer 2."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import logging
import re

from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings


logger = logging.getLogger(__name__)

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class EmbeddingOutput:
    """Dense and sparse embedding pair for one chunk."""

    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]


@lru_cache(maxsize=1)
def _load_sentence_transformers_bge_m3():
    """Lazy-load BGE-M3 through sentence-transformers."""

    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("BAAI/bge-m3", trust_remote_code=True)


@lru_cache(maxsize=1)
def _load_flagembedding_bge_m3():
    """Lazy-load native BGE-M3 runtime with dense + lexical sparse output."""

    from FlagEmbedding import BGEM3FlagModel

    return BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)


def _stable_sparse_index(token: str) -> int:
    """Map a token to a deterministic sparse-dimension id."""

    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big", signed=False)


def _compute_sparse_tfidf(doc: str, corpus_stats: dict[str, float] | None = None) -> tuple[list[int], list[float]]:
    """Small TF-IDF-like fallback sparse vector."""

    tokens = _TOKEN_PATTERN.findall(doc.lower())
    if not tokens:
        return [], []

    tf = Counter(tokens)
    total = len(tokens)
    stats = corpus_stats or {}
    weights_by_index: dict[int, float] = {}

    for token, count in tf.items():
        tf_norm = count / total
        idf = stats.get(token, 1.0)
        index = _stable_sparse_index(token)
        weights_by_index[index] = weights_by_index.get(index, 0.0) + (tf_norm * idf)

    indices = sorted(weights_by_index)
    values = [round(weights_by_index[index], 6) for index in indices]
    return indices, values


def _flag_sparse_to_lists(weights: object) -> tuple[list[int], list[float]]:
    """Convert FlagEmbedding lexical weights to Qdrant sparse arrays."""

    if not isinstance(weights, dict):
        return [], []

    sparse: dict[int, float] = {}
    for raw_key, raw_value in weights.items():
        try:
            index = int(raw_key)
            value = float(raw_value)
        except (TypeError, ValueError):
            index = _stable_sparse_index(str(raw_key))
            value = float(raw_value or 0.0)
        if value:
            sparse[index] = value

    indices = sorted(sparse)
    values = [round(sparse[index], 6) for index in indices]
    return indices, values


def _encode_with_flagembedding(texts: list[str]) -> list[EmbeddingOutput]:
    model = _load_flagembedding_bge_m3()
    encoded = model.encode(
        texts,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense_vectors = encoded.get("dense_vecs")
    if dense_vectors is None:
        dense_vectors = []

    lexical_weights = encoded.get("lexical_weights")
    if lexical_weights is None:
        lexical_weights = [{} for _ in texts]
    elif isinstance(lexical_weights, dict):
        lexical_weights = [lexical_weights]

    if len(dense_vectors) != len(texts) or len(lexical_weights) != len(texts):
        raise RuntimeError("FlagEmbedding returned an unexpected number of vectors")

    results: list[EmbeddingOutput] = []
    for dense_vec, sparse_weights in zip(dense_vectors, lexical_weights, strict=True):
        sparse_indices, sparse_values = _flag_sparse_to_lists(sparse_weights)
        results.append(
            EmbeddingOutput(
                dense_vector=[float(value) for value in dense_vec],
                sparse_indices=sparse_indices,
                sparse_values=sparse_values,
            )
        )
    return results


def _encode_with_sentence_transformers(
    texts: list[str],
    *,
    sparse_texts: list[str] | None,
) -> list[EmbeddingOutput]:
    model = _load_sentence_transformers_bge_m3()
    dense_vecs = model.encode(texts, show_progress_bar=False)

    results: list[EmbeddingOutput] = []
    for index, (text, dense_vec) in enumerate(zip(texts, dense_vecs, strict=True)):
        sparse_source = sparse_texts[index] if sparse_texts is not None else text
        sparse_indices, sparse_values = _compute_sparse_tfidf(sparse_source)
        results.append(
            EmbeddingOutput(
                dense_vector=[float(value) for value in dense_vec],
                sparse_indices=sparse_indices,
                sparse_values=sparse_values,
            )
        )
    return results


def encode_texts(texts: list[str], *, sparse_texts: list[str] | None = None) -> list[EmbeddingOutput]:
    """Encode texts with backend policy: flagembedding, sentence-transformers or auto."""

    if not texts:
        return []
    if sparse_texts is not None and len(sparse_texts) != len(texts):
        raise ValueError("sparse_texts must have the same length as texts")

    backend = get_settings().processing_embedding_backend
    if backend in {"auto", "flagembedding"}:
        try:
            return _encode_with_flagembedding(texts)
        except Exception as exc:
            if backend == "flagembedding":
                raise
            log_event(
                logger,
                logging.WARNING,
                "embedding_backend_fallback",
                primary_backend="flagembedding",
                fallback_backend="sentence-transformers",
                error=str(exc),
            )

    return _encode_with_sentence_transformers(texts, sparse_texts=sparse_texts)
