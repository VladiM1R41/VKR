"""ORM model for explicit user entity subscriptions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class UserEntitySubscription(Base):
    """Explicit user subscription to a specific entity."""

    __tablename__ = "user_entity_subscriptions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    alert_on_spike: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    alert_on_news: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
