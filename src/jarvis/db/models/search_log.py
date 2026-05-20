"""ORM model for search request logging."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class SearchLog(Base):
    """Log entry for one search request."""

    __tablename__ = "search_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    num_results: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    retrieval_time_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    retrieval_mode: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'qdrant_hybrid'"),
    )
    search_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rag_mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    top_result_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'")
    )
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
