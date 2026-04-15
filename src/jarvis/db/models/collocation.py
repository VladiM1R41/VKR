"""ORM model for statistically significant collocations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Integer, PrimaryKeyConstraint, String, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class Collocation(Base):
    """Pair of terms with a statistical association score."""

    __tablename__ = "collocations"
    __table_args__ = (
        PrimaryKeyConstraint("term_a", "term_b", name="pk_collocations"),
    )

    term_a: Mapped[str] = mapped_column(String(100), nullable=False)
    term_b: Mapped[str] = mapped_column(String(100), nullable=False)
    pmi_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    frequency: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))

