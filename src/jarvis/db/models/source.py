"""ORM model for the sources registry."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class Source(Base):
    """Source configuration stored in the database."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("type IN ('rss','telegram','website','api')", name="ck_sources_type"),
        CheckConstraint("engine IN ('auto','httpx','playwright')", name="ck_sources_engine"),
        CheckConstraint("delivery_mode IN ('push','pull')", name="ck_sources_delivery_mode"),
        CheckConstraint("priority IN ('continuous','periodic','control')", name="ck_sources_priority"),
        CheckConstraint("trust_score BETWEEN 0.0 AND 1.0", name="ck_sources_trust_score"),
        CheckConstraint("reliability IN ('A','B','C','D','E')", name="ck_sources_reliability"),
        CheckConstraint(
            "default_info_type IN ('breaking','daily','analytics','reference')",
            name="ck_sources_default_info_type",
        ),
        CheckConstraint(
            "default_content_type IN ('news','analysis','press_release','opinion')",
            name="ck_sources_default_content_type",
        ),
        CheckConstraint("health_status IN ('green','yellow','red')", name="ck_sources_health_status"),
        CheckConstraint("consecutive_failures >= 0", name="ck_sources_consecutive_failures"),
        CheckConstraint(
            "parse_success_rate IS NULL OR (parse_success_rate BETWEEN 0.0 AND 1.0)",
            name="ck_sources_parse_success_rate",
        ),
        CheckConstraint(
            "extraction_success_rate IS NULL OR (extraction_success_rate BETWEEN 0.0 AND 1.0)",
            name="ck_sources_extraction_success_rate",
        ),
        CheckConstraint(
            "source_utility IS NULL OR (source_utility BETWEEN 0.0 AND 1.0)",
            name="ck_sources_source_utility",
        ),
        CheckConstraint(
            "legal_status IN ('public_rss','public_telegram','public_web','restricted')",
            name="ck_sources_legal_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    engine: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'auto'"))
    delivery_mode: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'pull'"))
    config: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    crawl_interval: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("15"))
    crawl_delay: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("1.0"))
    priority: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'periodic'"))

    trust_score: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"))
    reliability: Mapped[str] = mapped_column(String(1), nullable=False, server_default=text("'C'"))

    default_info_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'daily'"),
    )
    default_content_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'news'"),
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_user_added: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    last_crawled: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    health_status: Mapped[str] = mapped_column(String(10), nullable=False, server_default=text("'green'"))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL", use_alter=True, name="fk_sources_last_run"),
        nullable=True,
    )
    parse_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraction_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_published_at: Mapped[datetime | None] = mapped_column(nullable=True)

    source_utility: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_latency_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)

    legal_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'public_rss'"),
    )

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
