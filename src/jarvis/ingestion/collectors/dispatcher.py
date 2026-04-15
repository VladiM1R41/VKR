"""Collector dispatcher for Layer 1."""

from __future__ import annotations

import httpx

from jarvis.db.models import Source
from jarvis.ingestion.collectors.base import BaseCollector
from jarvis.ingestion.collectors.rss import RSSCollector


class CollectorDispatcher:
    """Choose a collector implementation by source type."""

    _COLLECTORS: dict[str, type[BaseCollector]] = {
        "rss": RSSCollector,
    }

    @classmethod
    def get_collector(
        cls,
        source: Source,
        http_client: httpx.AsyncClient,
        known_canonical_urls: set[str] | None = None,
    ) -> BaseCollector:
        collector_class = cls._COLLECTORS.get(source.type)
        if collector_class is None:
            raise ValueError(f"Unsupported source type for MVP: {source.type}")
        return collector_class(source, http_client, known_canonical_urls=known_canonical_urls)
