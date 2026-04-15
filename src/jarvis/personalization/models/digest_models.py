"""Models for digest orchestration outputs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DigestCandidate(BaseModel):
    """One article selected into a digest shortlist."""

    news_id: int
    title: str
    source_name: str
    position: int
    score: float
    topics: list[str] = Field(default_factory=list)
    snippet: str | None = None
    reasons: list[str] = Field(default_factory=list)


class DigestShortlist(BaseModel):
    """Digest shortlist prepared by Layer 4."""

    user_id: int
    digest_type: str
    candidates: list[DigestCandidate] = Field(default_factory=list)
    topics_covered: list[str] = Field(default_factory=list)
    content_hash: str
    is_duplicate_of_existing: bool = False
