"""ORM model for article-entity many-to-many links."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, PrimaryKeyConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class NewsEntity(Base):
    """Link between one processed article and one normalized entity."""

    __tablename__ = "news_entities"
    __table_args__ = (
        PrimaryKeyConstraint("news_id", "entity_id", name="pk_news_entities"),
    )

    news_id: Mapped[int] = mapped_column(ForeignKey("news.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

