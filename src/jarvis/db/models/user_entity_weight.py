"""ORM model for user-entity preference weights."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class UserEntityWeight(Base):
    """Auto-learned entity weights for a user."""

    __tablename__ = "user_entity_weights"
    __table_args__ = (
        CheckConstraint("weight BETWEEN 0.0 AND 1.0", name="ck_user_entity_weights_weight"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0.5"))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
