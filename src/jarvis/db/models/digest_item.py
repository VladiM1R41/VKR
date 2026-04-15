"""ORM model for digest items."""

from __future__ import annotations

from sqlalchemy import ForeignKey, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class DigestItem(Base):
    """Membership of a news article in a digest, preserving ordering."""

    __tablename__ = "digest_items"

    digest_id: Mapped[int] = mapped_column(
        ForeignKey("digests.id", ondelete="CASCADE"), primary_key=True
    )
    news_id: Mapped[int] = mapped_column(
        ForeignKey("news.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
