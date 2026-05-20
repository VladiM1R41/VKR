"""ORM model for collector runs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, Text, String, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


DISCOVERY_RUN_KIND = "discovery"
ENRICHMENT_RUN_KIND = "enrichment"


class IngestionRun(Base):
    """Single source run with aggregated metrics."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','success','partial','failed','timeout','skipped_304','skipped_backpressure')",
            name="ck_ingestion_runs_status",
        ),
        CheckConstraint(
            "run_kind IN ('discovery','enrichment')",
            name="ck_ingestion_runs_run_kind",
        ),
        CheckConstraint("items_total >= 0", name="ck_ingestion_runs_items_total"),
        CheckConstraint("items_new >= 0", name="ck_ingestion_runs_items_new"),
        CheckConstraint("items_duplicate >= 0", name="ck_ingestion_runs_items_duplicate"),
        CheckConstraint("items_failed >= 0", name="ck_ingestion_runs_items_failed"),
        CheckConstraint("http_errors_count >= 0", name="ck_ingestion_runs_http_errors_count"),
        CheckConstraint("parse_errors_count >= 0", name="ck_ingestion_runs_parse_errors_count"),
        CheckConstraint(
            "extraction_errors_count >= 0",
            name="ck_ingestion_runs_extraction_errors_count",
        ),
        CheckConstraint(
            "response_bytes IS NULL OR response_bytes >= 0",
            name="ck_ingestion_runs_response_bytes",
        ),
        Index("ix_ingestion_runs_source_kind_started", "source_id", "run_kind", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    run_kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'discovery'"),
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'running'"))

    items_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    items_new: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    items_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    items_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    http_errors_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    parse_errors_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    extraction_errors_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sent_etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_if_modified_since: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
