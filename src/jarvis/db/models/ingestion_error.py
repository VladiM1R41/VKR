"""ORM model for detailed collector errors."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class IngestionError(Base):
    """Detailed ingestion error for incident analysis."""

    __tablename__ = "ingestion_errors"
    __table_args__ = (
        CheckConstraint(
            "error_type IN ('network','http_4xx','http_5xx','http_429','rss_parse','data_missing','date_parse','extraction','db_constraint','enqueue_failed','unknown')",
            name="ck_ingestion_errors_error_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))

    error_type: Mapped[str] = mapped_column(String(30), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
