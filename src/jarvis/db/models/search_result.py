"""ORM model for logged search result rows."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class SearchResult(Base):
    """One result row associated with a search request."""

    __tablename__ = "search_results"
    __table_args__ = (
        CheckConstraint(
            "rank_position IS NULL OR rank_position > 0",
            name="ck_search_results_rank_position",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_id: Mapped[int] = mapped_column(
        ForeignKey("search_logs.id", ondelete="CASCADE"),
        nullable=False,
    )
    news_id: Mapped[int] = mapped_column(
        ForeignKey("news.id", ondelete="CASCADE"),
        nullable=False,
    )
    rank_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    was_clicked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    dwell_time_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
