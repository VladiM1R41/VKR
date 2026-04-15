"""ORM model for article-topic many-to-many links."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKey, PrimaryKeyConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class NewsTopic(Base):
    """Topic assignment for one processed article."""

    __tablename__ = "news_topics"
    __table_args__ = (
        PrimaryKeyConstraint("news_id", "topic_id", name="pk_news_topics"),
        CheckConstraint("confidence BETWEEN 0.0 AND 1.0", name="ck_news_topics_confidence"),
    )

    news_id: Mapped[int] = mapped_column(ForeignKey("news.id", ondelete="CASCADE"), nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("1.0"))
