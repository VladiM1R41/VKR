"""Normalized article contract for all collectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class NormalizedArticle:
    """Unified representation of an article before persistence."""

    source_id: int
    url: str
    canonical_url: str
    title: str
    channel_type: str

    published_at: datetime | None = None
    raw_pub_date: str | None = None
    content: str | None = None
    snippet_lead: str | None = None

    title_hash: str | None = None
    content_status: str = "ok"
    extraction_method: str | None = None

    information_type: str = "daily"
    content_type: str = "news"
    language: str = "ru"
    urgency: str = "normal"
    is_uncertain: bool = False

    raw_content: str | None = None
    raw_format: str = "html"

    date_inferred: bool = False
    parser_version: str = "unknown"

    extra: dict[str, Any] = field(default_factory=dict)
