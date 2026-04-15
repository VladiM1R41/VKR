"""Embedding runtime helpers for Layer 2.

MVP: dense vectors через BGE-M3 (sentence-transformers),
sparse vectors через простой TF-approximation.

Примечание: BGE-M3 native sparse (FlagEmbedding) не поддерживает Python 3.12.
После выхода поддержки Python 3.12 в FlagEmbedding — можно переключиться.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import re


_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class EmbeddingOutput:
    """Dense and sparse embedding pair for one chunk."""

    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]


@lru_cache(maxsize=1)
def _load_bge_m3():
    """Lazy-load BGE-M3 через sentence-transformers.

    Первый вызов скачивает модель (~2.2 GB) с HuggingFace в кэш.
    Последующие вызовы используют закэшированную модель.
    """
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("BAAI/bge-m3", trust_remote_code=True)
    return model


def _stable_sparse_index(token: str) -> int:
    """Map a token to a deterministic sparse-dimension id."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big", signed=False)


def _compute_sparse_tfidf(doc: str, corpus_stats: dict[str, float] | None = None) -> tuple[list[int], list[float]]:
    """Простой TF-IDF approximation для sparse вектора.

    В MVP заменяет native BGE-M3 sparse (недоступен на Python 3.12).
    corpus_stats = {token: idf_value, ...} — IDF веса из словаря корпуса.

    Для MVP без внешнего словаря используем TF * log(TF+1) как proxy.
    """
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


def encode_texts(texts: list[str], *, sparse_texts: list[str] | None = None) -> list[EmbeddingOutput]:
    """Encode texts: dense через BGE-M3, sparse через TF approximation."""

    if not texts:
        return []
    if sparse_texts is not None and len(sparse_texts) != len(texts):
        raise ValueError("sparse_texts must have the same length as texts")

    model = _load_bge_m3()
    dense_vecs = model.encode(texts, show_progress_bar=False)

    results: list[EmbeddingOutput] = []
    for index, (text, dense_vec) in enumerate(zip(texts, dense_vecs, strict=True)):
        sparse_source = sparse_texts[index] if sparse_texts is not None else text
        sparse_indices, sparse_values = _compute_sparse_tfidf(sparse_source)
        results.append(
            EmbeddingOutput(
                dense_vector=[float(v) for v in dense_vec],
                sparse_indices=sparse_indices,
                sparse_values=sparse_values,
            )
        )
    return results
