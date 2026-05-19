"""Search request logging for Layer 3.

Logs every search query to PostgreSQL for:
- Analytics and improvement
- Learning to Rank data collection
- Failed query analysis
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select

from jarvis.core.logging import log_event
from jarvis.db.session import SyncSessionLocal


logger = logging.getLogger(__name__)


class SearchLogger:
    """Logs search requests to PostgreSQL."""

    def log_search(
        self,
        query_text: str,
        intent: str,
        num_results: int,
        retrieval_time_ms: int,
        top_result_ids: Optional[list[int]] = None,
        result_rows: Optional[list[dict[str, Any]]] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        resolved_query: Optional[str] = None,
        cache_hit: bool = False,
        retrieval_mode: str = "qdrant_hybrid",
        search_type: Optional[str] = None,
        rag_mode: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log a search request.

        Args:
            query_text: Original user query.
            intent: Classified intent type.
            num_results: Number of results returned.
            retrieval_time_ms: Search latency.
            top_result_ids: news_ids of top results (for CTR tracking).
            result_rows: Full returned result rows with news_id, rank_position and score.
            user_id: Authenticated user ID (if available).
            session_id: Session identifier (for grouping).
        """
        try:
            from jarvis.db.models.search_log import SearchLog
            from jarvis.db.models.search_result import SearchResult

            rows = result_rows or [
                {"news_id": news_id, "rank_position": rank, "score": 0.0}
                for rank, news_id in enumerate(top_result_ids or [], start=1)
            ]
            logged_ids = [int(row["news_id"]) for row in rows if row.get("news_id") is not None]

            with SyncSessionLocal() as session:
                log_entry = SearchLog(
                    user_id=user_id,
                    query_text=query_text[:500],  # truncate
                    resolved_query=resolved_query[:500] if resolved_query else None,
                    intent=intent,
                    num_results=num_results,
                    retrieval_time_ms=retrieval_time_ms,
                    cache_hit=cache_hit,
                    retrieval_mode=retrieval_mode[:40],
                    search_type=search_type[:40] if search_type else None,
                    rag_mode=rag_mode[:40] if rag_mode else None,
                    top_result_ids=logged_ids,
                    extra=extra or {},
                    session_id=session_id,
                )
                session.add(log_entry)
                session.flush()
                for fallback_rank, row in enumerate(rows, start=1):
                    news_id = row.get("news_id")
                    if news_id is None:
                        continue
                    session.add(
                        SearchResult(
                            search_id=log_entry.id,
                            news_id=int(news_id),
                            rank_position=int(row.get("rank_position") or fallback_rank),
                            score=float(row.get("score") or 0.0),
                        )
                    )
                session.commit()
        except Exception as exc:
            # Don't fail search if logging fails
            logger.warning("search_log_failed: %s", exc)

    def log_click(
        self,
        search_id: int,
        news_id: int,
        dwell_time_sec: Optional[float] = None,
    ) -> None:
        """Log a click on a search result (implicit feedback).

        For Learning to Rank data collection.

        Args:
            search_id: ID of the search_logs entry.
            news_id: news_id that was clicked.
            dwell_time_sec: Time spent reading (if available).
        """
        try:
            from jarvis.db.models.search_result import SearchResult
            with SyncSessionLocal() as session:
                click = session.scalar(
                    select(SearchResult).where(
                        SearchResult.search_id == search_id,
                        SearchResult.news_id == news_id,
                    )
                )
                if click is None:
                    click = SearchResult(
                        search_id=search_id,
                        news_id=news_id,
                        score=0.0,
                        was_clicked=True,
                        dwell_time_sec=dwell_time_sec,
                    )
                    session.add(click)
                else:
                    click.was_clicked = True
                    if dwell_time_sec is not None:
                        click.dwell_time_sec = dwell_time_sec
                session.commit()
        except Exception as exc:
            logger.warning("search_click_log_failed: %s", exc)
