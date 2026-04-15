"""ORM model for user interactions with news."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class UserInteraction(Base):
    """Append-only history of user interactions with articles."""

    __tablename__ = "user_interactions"
    __table_args__ = (
        CheckConstraint(
            "action IN ('click','read','like','dislike','save','hide','share')",
            name="ck_user_interactions_action",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    news_id: Mapped[int] = mapped_column(
        ForeignKey("news.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    dwell_time_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    search_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("search_logs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
