"""ORM model for normalized named entities."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class Entity(Base):
    """Normalized entity extracted from processed news."""

    __tablename__ = "entities"
    __table_args__ = (
        CheckConstraint("type IN ('person','organization','location')", name="ck_entities_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

