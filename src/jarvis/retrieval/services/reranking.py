"""Cross-encoder reranker for Layer 3.

Uses BAAI/bge-reranker-v2-m3 via sentence-transformers CrossEncoder.
- 278M parameters, works on CPU (~130ms/batch 16 pairs)
- Supports Russian language
- Apache 2.0 license
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import logging
from typing import Optional

from jarvis.core.logging import log_event
from jarvis.retrieval.services.qdrant_search import SearchResult


logger = logging.getLogger(__name__)


@dataclass
class RerankedResult:
    """One reranked result with both retrieval and rerank scores."""

    result: SearchResult
    rerank_score: float  # [0, 1] from cross-encoder


@lru_cache(maxsize=1)
def _load_reranker():
    """Lazy-load BGE reranker via sentence-transformers."""
    try:
        from sentence_transformers import CrossEncoder
        return CrossEncoder("BAAI/bge-reranker-v2-m3")
    except Exception as exc:
        logger.warning("reranker unavailable: %s", exc)
        return None


class RerankingService:
    """Cross-encoder reranking service."""

    def rerank(
        self,
        query: str,
        candidates: list[SearchResult],
    ) -> list[RerankedResult]:
        """Rerank candidates using cross-encoder.

        Args:
            query: Original user query.
            candidates: Top-K results from retrieval (typically 30-50).

        Returns:
            Reranked results sorted by descending rerank_score.
            If reranker unavailable, returns candidates with score 0.5.
        """
        if not candidates:
            return []

        model = _load_reranker()
        if model is None:
            # Graceful degradation: return as-is with neutral score
            return [
                RerankedResult(result=c, rerank_score=0.5)
                for c in candidates
            ]

        # Build pairs: (query, document text)
        # Use lemma_text if available, else raw text
        pairs = []
        for c in candidates:
            doc_text = c.text or c.title
            pairs.append([query, doc_text])

        # Predict scores
        scores = model.predict(pairs)

        results = []
        for candidate, score in zip(candidates, scores, strict=True):
            # CrossEncoder возвращает logits → нормализуем через sigmoid
            import math
            normalized_score = float(1 / (1 + math.exp(-score)))
            results.append(
                RerankedResult(
                    result=candidate,
                    rerank_score=round(normalized_score, 4),
                )
            )

        # Sort by rerank_score descending
        results.sort(key=lambda r: r.rerank_score, reverse=True)

        log_event(
            logger,
            logging.INFO,
            "reranking_completed",
            candidates_count=len(candidates),
            top_score=results[0].rerank_score if results else 0,
            bottom_score=results[-1].rerank_score if results else 0,
        )
        return results
