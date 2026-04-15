"""Batch selection helpers for Layer 2."""

from __future__ import annotations

from sqlalchemy import case, select

from jarvis.db.models import News
from jarvis.db.session import SyncSessionLocal


def load_unprocessed_batch(limit: int) -> list[News]:
    """Load one prioritized batch of articles awaiting processing."""

    urgency_rank = case(
        (News.urgency == "critical", 1),
        (News.urgency == "high", 2),
        else_=3,
    )
    with SyncSessionLocal() as session:
        stmt = (
            select(News)
            .where(News.processed.is_(False))
            .order_by(urgency_rank.asc(), News.ingested_at.asc(), News.id.asc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())
