"""ORM model for Layer 5 generation logs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from jarvis.db.base import Base


class GenerationLog(Base):
    """One logged LLM generation call."""

    __tablename__ = "generation_logs"
    __table_args__ = (
        CheckConstraint(
            "rag_mode IN ('standard','crag','self_rag','graph_rag','agentic')",
            name="ck_generation_logs_rag_mode",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence IN ('LOW','MEDIUM','HIGH','TOP')",
            name="ck_generation_logs_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    rag_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    model_name: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    documents_used: Mapped[list[dict] | None] = mapped_column(
        MutableList.as_mutable(JSONB),
        nullable=True,
    )
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("NOW()"))

