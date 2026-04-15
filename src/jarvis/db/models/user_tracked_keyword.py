"""ORM model for user-tracked keywords."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class UserTrackedKeyword(Base):
    """Arbitrary keyword a user wants to monitor."""

    __tablename__ = "user_tracked_keywords"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    keyword: Mapped[str] = mapped_column(String(200), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
