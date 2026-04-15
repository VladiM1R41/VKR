"""ORM model for per-entity trend profile."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class EntityProfile(Base):
    """Aggregated profile for anomaly and trend detection."""

    __tablename__ = "entity_profiles"
    __table_args__ = (
        CheckConstraint(
            "trend_direction IN ('ascending','descending','stable','cyclic')",
            name="ck_entity_profiles_trend_direction",
        ),
    )

    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mention_freq_baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    mention_freq_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment_baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_diversity: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    trend_direction: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'stable'"))
    last_updated: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))

