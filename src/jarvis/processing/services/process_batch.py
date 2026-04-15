"""Batch orchestration for Layer 2 processing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging

from jarvis.core.logging import log_event
from jarvis.processing.services.process_article import process_one_news_article
from jarvis.processing.services.qdrant_index import QdrantIndexer
from jarvis.processing.services.select_batch import load_unprocessed_batch


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessBatchResult:
    """Summary of one processing batch."""

    selected_count: int
    processed_count: int
    skipped_count: int
    failed_count: int
    processed_news_ids: list[int]
    failed_news_ids: list[int]

    def to_dict(self) -> dict[str, object]:
        """Convert to a Celery-friendly dict."""

        return asdict(self)


def process_pending_news_batch(*, limit: int) -> ProcessBatchResult:
    """Process one prioritized batch of unprocessed articles."""

    selected_news = load_unprocessed_batch(limit)
    if not selected_news:
        return ProcessBatchResult(
            selected_count=0,
            processed_count=0,
            skipped_count=0,
            failed_count=0,
            processed_news_ids=[],
            failed_news_ids=[],
        )

    processed_news_ids: list[int] = []
    failed_news_ids: list[int] = []
    skipped_count = 0
    qdrant_indexer = QdrantIndexer()

    for news in selected_news:
        try:
            result = process_one_news_article(news.id, qdrant_indexer=qdrant_indexer)
        except Exception as exc:
            failed_news_ids.append(news.id)
            log_event(
                logger,
                logging.ERROR,
                "processing_article_failed",
                news_id=news.id,
                error=str(exc),
            )
            continue

        if result.status == "processed":
            processed_news_ids.append(news.id)
        else:
            skipped_count += 1

    result = ProcessBatchResult(
        selected_count=len(selected_news),
        processed_count=len(processed_news_ids),
        skipped_count=skipped_count,
        failed_count=len(failed_news_ids),
        processed_news_ids=processed_news_ids,
        failed_news_ids=failed_news_ids,
    )
    log_event(
        logger,
        logging.INFO,
        "processing_batch_completed",
        **result.to_dict(),
    )
    return result
