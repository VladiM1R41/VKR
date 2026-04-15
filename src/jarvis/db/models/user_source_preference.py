"""ORM model for user source preferences."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class UserSourcePreference(Base):
    """User preference for a source: preferred / neutral / blocked."""

    __tablename__ = "user_source_preferences"
    __table_args__ = (
        CheckConstraint(
            "preference IN ('preferred','neutral','blocked')",
            name="ck_user_source_preferences_preference",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    preference: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'neutral'")
    )
