"""ORM model for entity co-occurrence graph edges."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, PrimaryKeyConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class EntityCooccurrence(Base):
    """Undirected co-mention edge between two entities."""

    __tablename__ = "entity_cooccurrences"
    __table_args__ = (
        PrimaryKeyConstraint("entity_a_id", "entity_b_id", name="pk_entity_cooccurrences"),
        CheckConstraint("entity_a_id < entity_b_id", name="ck_entity_cooccurrences_order"),
    )

    entity_a_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    entity_b_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    co_mention_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    last_seen_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))

