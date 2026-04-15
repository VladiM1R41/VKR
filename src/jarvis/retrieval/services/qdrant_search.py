"""Qdrant search service for Layer 3.

Uses Qdrant Query API with prefetch for parallel dense + sparse search
in a single API call (Qdrant 1.10+).

Supports payload filtering: date, source, topics, language.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Optional

from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings


logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """One raw search result from Qdrant."""

    point_id: str
    news_id: int
    source_id: int
    source_name: str
    title: str
    text: str
    score: float
    zone: str
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    published_at: Optional[datetime] = None
    trust_score: float = 0.5
    content_grade: int = 6
    information_type: str = "daily"
    chunk_index: int = 0
    total_chunks: int = 1
    snippet_lead: str = ""
    url: str = ""


class QdrantSearchService:
    """Search service using Qdrant Query API."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def _client(self):
        from qdrant_client import QdrantClient
        return QdrantClient(url=self._settings.qdrant_url)

    def search(
        self,
        dense_vector: list[float],
        sparse_indices: list[int],
        sparse_values: list[float],
        *,
        limit: int = 30,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        source_ids: Optional[list[int]] = None,
        topics: Optional[list[str]] = None,
        language: str = "ru",
        additional_queries: list[tuple[list[float], list[int], list[float]]] | None = None,
    ) -> list[SearchResult]:
        """Parallel dense + sparse search with RRF fusion.

        Uses Qdrant Query API with prefetch — single API call.

        Args:
            dense_vector: BGE-M3 dense embedding (1024-dim).
            sparse_indices: Sparse vector indices.
            sparse_values: Sparse vector values.
            limit: Max results to return.
            date_from: Filter by published_at >= date.
            date_to: Filter by published_at <= date.
            source_ids: Filter by source_id list.
            topics: Filter by topics list.
            language: Language filter.

        Returns:
            List of SearchResult with RRF-fused scores.
        """
        from qdrant_client import models

        client = self._client()

        # Build filters
        must_conditions: list = [
            models.FieldCondition(key="language", match=models.MatchValue(value=language)),
        ]

        if date_from:
            must_conditions.append(
                models.FieldCondition(
                    key="published_at",
                    range=models.Range(gte=date_from.isoformat()),
                )
            )
        if date_to:
            must_conditions.append(
                models.FieldCondition(
                    key="published_at",
                    range=models.Range(lte=date_to.isoformat()),
                )
            )
        if source_ids:
            must_conditions.append(
                models.FieldCondition(
                    key="source_id",
                    match=models.MatchAny(any=source_ids),
                )
            )
        if topics:
            must_conditions.append(
                models.FieldCondition(
                    key="topics",
                    match=models.MatchAny(any=topics),
                )
            )

        query_filter = models.Filter(must=must_conditions)

        prefetches: list[object] = [
            models.Prefetch(
                query=dense_vector,
                using="dense",
                limit=limit,
            )
        ]
        if sparse_indices and sparse_values:
            prefetches.append(
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse_indices,
                        values=sparse_values,
                    ),
                    using="sparse",
                    limit=limit,
                )
            )

        for extra_dense, extra_sparse_indices, extra_sparse_values in additional_queries or []:
            prefetches.append(
                models.Prefetch(
                    query=extra_dense,
                    using="dense",
                    limit=limit,
                )
            )
            if extra_sparse_indices and extra_sparse_values:
                prefetches.append(
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=extra_sparse_indices,
                            values=extra_sparse_values,
                        ),
                        using="sparse",
                        limit=limit,
                    )
                )

        try:
            results = client.query_points(
                collection_name=self._settings.qdrant_collection_alias,
                prefetch=prefetches,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "qdrant_search_failed",
                error=str(exc),
                limit=limit,
            )
            return []

        search_results: list[SearchResult] = []
        for point in results.points:
            payload = point.payload or {}
            search_results.append(
                SearchResult(
                    point_id=str(point.id),
                    news_id=payload.get("news_id", 0),
                    source_id=payload.get("source_id", 0),
                    source_name=payload.get("source_name", "Unknown"),
                    title=payload.get("title") or payload.get("snippet_lead", ""),
                    text=payload.get("text") or payload.get("text_content", ""),
                    score=point.score or 0.0,
                    zone=payload.get("zone", "body"),
                    topics=payload.get("topics", []),
                    entities=payload.get("entities", []),
                    published_at=(
                        datetime.fromisoformat(payload["published_at"])
                        if payload.get("published_at")
                        else None
                    ),
                    trust_score=payload.get("trust_score", 0.5),
                    content_grade=payload.get("content_grade", 6),
                    information_type=payload.get("information_type", "daily"),
                    chunk_index=payload.get("chunk_index", 0),
                    total_chunks=payload.get("total_chunks", 1),
                    snippet_lead=payload.get("snippet_lead", ""),
                    url=payload.get("url", ""),
                )
            )

        log_event(
            logger,
            logging.INFO,
            "qdrant_search_completed",
            results_count=len(search_results),
            limit=limit,
        )
        return search_results
