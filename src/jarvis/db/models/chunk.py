"""ORM model mapping processed article chunks to Qdrant points."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class Chunk(Base):
    """One searchable chunk of an article."""

    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint("zone IN ('title','body')", name="ck_chunks_zone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news.id", ondelete="CASCADE"), nullable=False)
    qdrant_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        unique=True,
        default=uuid.uuid4,
    )
    chunk_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    zone: Mapped[str] = mapped_column(String(10), nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
