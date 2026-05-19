"""PostgreSQL/Qdrant consistency checks and repair helpers for Layer 2."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from sqlalchemy import select

from jarvis.core.logging import log_event
from jarvis.db.models import Chunk
from jarvis.db.session import SyncSessionLocal
from jarvis.processing.services.process_article import process_one_news_article
from jarvis.processing.services.qdrant_index import QdrantIndexer


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QdrantConsistencyReport:
    """Consistency report for chunks table and Qdrant collection."""

    db_chunk_count: int
    qdrant_point_count: int
    missing_point_ids: list[str] = field(default_factory=list)
    orphan_point_ids: list[str] = field(default_factory=list)

    @property
    def is_green(self) -> bool:
        return not self.missing_point_ids and not self.orphan_point_ids


def _load_db_chunk_points() -> dict[str, int]:
    with SyncSessionLocal() as session:
        rows = session.execute(select(Chunk.qdrant_point_id, Chunk.news_id)).all()
    return {str(point_id): int(news_id) for point_id, news_id in rows}


def _scroll_qdrant_point_ids(indexer: QdrantIndexer) -> set[str]:
    client = indexer._client()
    point_ids: set[str] = set()
    offset = None

    while True:
        try:
            points, offset = client.scroll(
                collection_name=indexer._settings.qdrant_collection_alias,
                limit=1024,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
        except Exception as exc:
            if "doesn't exist" in str(exc) or "Not found: Collection" in str(exc):
                return set()
            raise
        point_ids.update(str(point.id) for point in points)
        if offset is None:
            break

    return point_ids


def check_qdrant_consistency(*, qdrant_indexer: QdrantIndexer | None = None) -> QdrantConsistencyReport:
    """Dry-run consistency check between PostgreSQL chunks and Qdrant points."""

    indexer = qdrant_indexer or QdrantIndexer()
    db_points = _load_db_chunk_points()
    qdrant_points = _scroll_qdrant_point_ids(indexer)

    missing = sorted(set(db_points) - qdrant_points)
    orphan = sorted(qdrant_points - set(db_points))
    report = QdrantConsistencyReport(
        db_chunk_count=len(db_points),
        qdrant_point_count=len(qdrant_points),
        missing_point_ids=missing,
        orphan_point_ids=orphan,
    )
    log_event(
        logger,
        logging.INFO,
        "qdrant_consistency_checked",
        db_chunk_count=report.db_chunk_count,
        qdrant_point_count=report.qdrant_point_count,
        missing_count=len(report.missing_point_ids),
        orphan_count=len(report.orphan_point_ids),
        is_green=report.is_green,
    )
    return report


def repair_qdrant_consistency(*, qdrant_indexer: QdrantIndexer | None = None) -> QdrantConsistencyReport:
    """Repair missing/orphan Qdrant points and return a fresh post-repair report."""

    indexer = qdrant_indexer or QdrantIndexer()
    before = check_qdrant_consistency(qdrant_indexer=indexer)
    if before.orphan_point_ids:
        indexer.delete_points(before.orphan_point_ids)

    if before.missing_point_ids:
        db_points = _load_db_chunk_points()
        missing_news_ids = sorted({db_points[point_id] for point_id in before.missing_point_ids if point_id in db_points})
        for news_id in missing_news_ids:
            process_one_news_article(news_id, qdrant_indexer=indexer, force=True)

    after = check_qdrant_consistency(qdrant_indexer=indexer)
    log_event(
        logger,
        logging.INFO,
        "qdrant_consistency_repaired",
        before_missing=len(before.missing_point_ids),
        before_orphan=len(before.orphan_point_ids),
        after_missing=len(after.missing_point_ids),
        after_orphan=len(after.orphan_point_ids),
    )
    return after
