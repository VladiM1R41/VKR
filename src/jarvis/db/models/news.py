"""ORM model for normalized news articles."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class News(Base):
    """Central normalized article table."""

    __tablename__ = "news"
    __table_args__ = (
        CheckConstraint(
            "channel_type IN ('RSS','TELEGRAM','SCRAPE','API','ARCHIVE')",
            name="ck_news_channel_type",
        ),
        CheckConstraint(
            "information_type IN ('breaking','daily','analytics','reference')",
            name="ck_news_information_type",
        ),
        CheckConstraint(
            "content_type IN ('news','analysis','press_release','opinion')",
            name="ck_news_content_type",
        ),
        CheckConstraint("content_grade BETWEEN 1 AND 6", name="ck_news_content_grade"),
        CheckConstraint("urgency IN ('critical','high','normal')", name="ck_news_urgency"),
        CheckConstraint(
            "content_status IN ('ok','partial','paywall','extraction_failed','low')",
            name="ck_news_content_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet_lead: Mapped[str | None] = mapped_column(Text, nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))

    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    ingestion_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL", use_alter=True, name="fk_news_ingestion_run"),
        nullable=True,
    )

    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    information_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'daily'"))
    content_type: Mapped[str | None] = mapped_column(String(20), nullable=True, server_default=text("'news'"))
    language: Mapped[str] = mapped_column(String(5), nullable=False, server_default=text("'ru'"))

    title_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("news.id"), nullable=True)
    event_cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "news.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_news_event_cluster",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )

    content_grade: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("6"))
    urgency: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'normal'"))
    is_uncertain: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    content_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'ok'"))
    extraction_method: Mapped[str | None] = mapped_column(String(40), nullable=True)

    raw_pub_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    parser_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    date_inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    extra: Mapped[dict] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
