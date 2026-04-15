"""ORM model for generated digests."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class Digest(Base):
    """Generated digest for a user."""

    __tablename__ = "digests"
    __table_args__ = (
        CheckConstraint(
            "digest_type IN ('morning','evening','weekly','on_demand')",
            name="ck_digests_digest_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    digest_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generation_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("generation_logs.id", ondelete="SET NULL"),
        nullable=True,
    )
    news_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    topics_covered: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
