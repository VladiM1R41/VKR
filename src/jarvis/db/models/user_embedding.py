"""ORM model for user embedding vector."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class UserEmbedding(Base):
    """User centroid embedding, updated periodically."""

    __tablename__ = "user_embeddings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))
