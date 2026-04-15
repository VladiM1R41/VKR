"""ORM model for corpus vocabulary terms."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class TermVocabulary(Base):
    """Global vocabulary entry used for autocomplete and corpus analytics."""

    __tablename__ = "term_vocabulary"

    term: Mapped[str] = mapped_column(String(100), primary_key=True)
    doc_frequency: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    collection_frequency: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))

