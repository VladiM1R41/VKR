"""PostgreSQL FTS fallback for Layer 3 retrieval.

Qdrant is the primary search backend. This module is only a degraded
availability path for cases when Qdrant is temporarily unavailable.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Optional

from sqlalchemy import bindparam, text

from jarvis.core.logging import log_event
from jarvis.db.session import SyncSessionLocal
from jarvis.retrieval.services.qdrant_search import SearchResult


logger = logging.getLogger(__name__)


class PostgresFTSSearchService:
    """Small degraded-mode retrieval service backed by PostgreSQL FTS."""

    def search(
        self,
        query: str,
        *,
        limit: int = 30,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        source_ids: Optional[list[int]] = None,
        topics: Optional[list[str]] = None,
        language: str = "ru",
        zone: Optional[str] = None,
        content_grade: Optional[int] = None,
        content_grade_max: Optional[int] = None,
        urgency: Optional[str] = None,
        information_type: Optional[str] = None,
        event_cluster_id: Optional[int] = None,
        retrieval_mode: str = "postgres_fts_fallback",
    ) -> list[SearchResult]:
        """Search processed news through PostgreSQL full-text search."""
        if not query.strip():
            return []

        if zone == "title":
            search_document = "coalesce(n.title, '')"
            result_text = "coalesce(n.snippet_lead, n.title, '')"
            result_zone = "title"
        elif zone == "body":
            search_document = "coalesce(n.content, '') || ' ' || coalesce(n.snippet_lead, '')"
            result_text = "coalesce(n.content, n.snippet_lead, '')"
            result_zone = "body"
        else:
            search_document = "coalesce(n.title, '') || ' ' || coalesce(n.content, '') || ' ' || coalesce(n.snippet_lead, '')"
            result_text = "coalesce(n.content, n.snippet_lead, n.title, '')"
            result_zone = "body"

        where = [
            "n.processed = true",
            "n.language = :language",
            f"to_tsvector('russian', {search_document}) @@ websearch_to_tsquery('russian', :query)",
        ]
        params: dict[str, object] = {
            "query": query,
            "limit": limit,
            "language": language,
        }
        expanding_params: list[str] = []

        if date_from is not None:
            where.append("n.published_at >= :date_from")
            params["date_from"] = date_from
        if date_to is not None:
            where.append("n.published_at <= :date_to")
            params["date_to"] = date_to
        if source_ids:
            where.append("n.source_id IN :source_ids")
            params["source_ids"] = source_ids
            expanding_params.append("source_ids")
        if topics:
            where.append(
                """
                EXISTS (
                    SELECT 1
                    FROM news_topics nt
                    JOIN topics t ON t.id = nt.topic_id
                    WHERE nt.news_id = n.id AND t.name IN :topics
                )
                """
            )
            params["topics"] = topics
            expanding_params.append("topics")
        if content_grade is not None:
            where.append("n.content_grade = :content_grade")
            params["content_grade"] = content_grade
        elif content_grade_max is not None:
            where.append("n.content_grade <= :content_grade_max")
            params["content_grade_max"] = content_grade_max
        if urgency:
            where.append("n.urgency = :urgency")
            params["urgency"] = urgency
        if information_type:
            where.append("n.information_type = :information_type")
            params["information_type"] = information_type
        if event_cluster_id is not None:
            where.append("n.event_cluster_id = :event_cluster_id")
            params["event_cluster_id"] = event_cluster_id

        sql = f"""
            SELECT
                n.id AS news_id,
                n.source_id AS source_id,
                s.name AS source_name,
                n.title AS title,
                {result_text} AS text,
                n.snippet_lead AS snippet_lead,
                n.published_at AS published_at,
                s.trust_score AS trust_score,
                n.content_grade AS content_grade,
                n.information_type AS information_type,
                n.urgency AS urgency,
                n.event_cluster_id AS event_cluster_id,
                n.is_uncertain AS is_uncertain,
                n.extra AS extra,
                ts_rank_cd(
                    to_tsvector('russian', {search_document}),
                    websearch_to_tsquery('russian', :query)
                ) AS rank_score,
                ARRAY(
                    SELECT t.name
                    FROM news_topics nt
                    JOIN topics t ON t.id = nt.topic_id
                    WHERE nt.news_id = n.id
                    ORDER BY nt.confidence DESC
                    LIMIT 5
                ) AS topics,
                ARRAY(
                    SELECT e.normalized_name
                    FROM news_entities ne
                    JOIN entities e ON e.id = ne.entity_id
                    WHERE ne.news_id = n.id
                    ORDER BY ne.mention_count DESC
                    LIMIT 10
                ) AS entities
            FROM news n
            JOIN sources s ON s.id = n.source_id
            WHERE {" AND ".join(where)}
            ORDER BY rank_score DESC, n.published_at DESC NULLS LAST, n.id DESC
            LIMIT :limit
        """
        stmt = text(sql)
        for name in expanding_params:
            stmt = stmt.bindparams(bindparam(name, expanding=True))

        try:
            with SyncSessionLocal() as session:
                rows = session.execute(stmt, params).mappings().all()
        except Exception as exc:
            log_event(logger, logging.ERROR, "postgres_fts_search_failed", error=str(exc))
            return []

        results: list[SearchResult] = []
        for row in rows:
            extra = row.get("extra") or {}
            processing = extra.get("processing") if isinstance(extra, dict) else {}
            processing = processing if isinstance(processing, dict) else {}
            rank_score = float(row.get("rank_score") or 0.0)
            results.append(
                SearchResult(
                    point_id=f"postgres-fts:{row['news_id']}",
                    news_id=int(row["news_id"]),
                    source_id=int(row["source_id"]),
                    source_name=row.get("source_name") or "Unknown",
                    title=row.get("title") or "",
                    text=row.get("text") or "",
                    score=rank_score,
                    zone=result_zone,
                    topics=list(row.get("topics") or []),
                    entities=list(row.get("entities") or []),
                    published_at=row.get("published_at"),
                    trust_score=float(row.get("trust_score") or 0.5),
                    content_grade=int(row.get("content_grade") or 6),
                    information_type=row.get("information_type") or "daily",
                    urgency=row.get("urgency") or "normal",
                    event_cluster_id=row.get("event_cluster_id"),
                    value_score=processing.get("value_score"),
                    freshness=processing.get("freshness"),
                    completeness=processing.get("completeness"),
                    cluster_support=processing.get("cluster_support"),
                    is_uncertain=bool(row.get("is_uncertain", False)),
                    snippet_lead=row.get("snippet_lead") or "",
                    retrieval_mode=retrieval_mode,
                )
            )

        log_event(
            logger,
            logging.WARNING if retrieval_mode == "postgres_fts_fallback" else logging.INFO,
            "postgres_fts_search_used",
            retrieval_mode=retrieval_mode,
            results_count=len(results),
        )
        return results
