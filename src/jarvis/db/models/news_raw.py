"""ORM model for raw article payloads."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class NewsRaw(Base):
    """Raw source payload retained for reprocessing."""

    __tablename__ = "news_raw"
    __table_args__ = (
        CheckConstraint("raw_format IN ('html','json','xml','text')", name="ck_news_raw_format"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_id: Mapped[int] = mapped_column(
        ForeignKey("news.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    raw_format: Mapped[str | None] = mapped_column(String(10), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
