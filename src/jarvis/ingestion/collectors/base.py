"""Abstract collector contract for Layer 1."""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from jarvis.db.models import Source
from jarvis.ingestion.contracts.normalized_article import NormalizedArticle


class BaseCollector(ABC):
    """Abstract base collector."""

    def __init__(
        self,
        source: Source,
        http_client: httpx.AsyncClient,
        known_canonical_urls: set[str] | None = None,
    ):
        self.source = source
        self.config = source.config or {}
        self.http = http_client
        self.known_canonical_urls = known_canonical_urls or set()

    @abstractmethod
    async def collect(self) -> list[NormalizedArticle]:
        """Collect new articles from the source."""

    def get_parser_version(self) -> str:
        """Return parser version used for provenance."""
        return f"{self.__class__.__name__.lower()}-v1"
