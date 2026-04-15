"""Query preprocessing for Layer 3.

Reuses the same analysis pipeline as Layer 2 (per Manning ch. 2:
single analyzer for both documents and queries):
- Razdel tokenization
- PyMorphy3 lemmatization
- BGE-M3 embedding (dense + sparse)

Also includes:
- Intent classification
- Query context assembly
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from jarvis.core.logging import log_event
from jarvis.processing.ir.lemmatize import lemmatize_text
from jarvis.processing.services.embedding_runtime import encode_texts
from jarvis.retrieval.services.intent_classifier import classify_intent, IntentResult


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QueryContext:
    """Fully preprocessed query, ready for retrieval."""

    original: str
    lemma: str
    intent: IntentResult
    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]


def preprocess_query(query: str) -> QueryContext:
    """Full query preprocessing pipeline.

    Steps:
    1. Lemmatize (same pipeline as Layer 2 documents)
    2. Intent classification
    3. Dense + sparse embedding

    Args:
        query: Raw user query text.

    Returns:
        QueryContext with all preprocessing artifacts.
    """
    # Step 1: Lemmatization (single analyzer principle)
    lemma = lemmatize_text(query)

    # Step 2: Intent classification
    intent = classify_intent(query)

    # Step 3: Dense + sparse embedding
    # encode_texts returns list[EmbeddingOutput], we take the first
    embeddings = encode_texts([query], sparse_texts=[lemma])
    embedding = embeddings[0]

    ctx = QueryContext(
        original=query,
        lemma=lemma,
        intent=intent,
        dense_vector=embedding.dense_vector,
        sparse_indices=embedding.sparse_indices,
        sparse_values=embedding.sparse_values,
    )

    log_event(
        logger,
        logging.INFO,
        "query_preprocessed",
        query=query[:100],
        intent=intent.intent,
        dense_dim=len(embedding.dense_vector),
        sparse_dim=len(embedding.sparse_indices),
    )
    return ctx
