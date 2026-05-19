"""Batch updater for entity_profiles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import func, select

from jarvis.core.logging import log_event
from jarvis.db.models import Entity, EntityProfile, News, NewsEntity
from jarvis.db.session import SyncSessionLocal


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EntityProfilesUpdateResult:
    """Result of entity_profiles batch refresh."""

    profiles_added: int
    profiles_updated: int
    total_profiles: int


def _trend_direction(current: float, baseline: float) -> str:
    if baseline <= 0 and current > 0:
        return "ascending"
    if baseline <= 0:
        return "stable"
    ratio = current / baseline
    if ratio >= 1.25:
        return "ascending"
    if ratio <= 0.75:
        return "descending"
    return "stable"


def update_entity_profiles() -> EntityProfilesUpdateResult:
    """Refresh entity profiles from processed news/entity mentions."""

    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=1)
    baseline_start = now - timedelta(days=31)
    baseline_end = current_start

    added = 0
    updated = 0
    with SyncSessionLocal() as session:
        entity_ids = list(session.scalars(select(Entity.id)).all())
        for entity_id in entity_ids:
            current_mentions = float(
                session.scalar(
                    select(func.coalesce(func.sum(NewsEntity.mention_count), 0))
                    .select_from(NewsEntity)
                    .join(News, News.id == NewsEntity.news_id)
                    .where(
                        NewsEntity.entity_id == entity_id,
                        News.processed.is_(True),
                        News.ingested_at >= current_start,
                    )
                )
                or 0.0
            )
            baseline_total = float(
                session.scalar(
                    select(func.coalesce(func.sum(NewsEntity.mention_count), 0))
                    .select_from(NewsEntity)
                    .join(News, News.id == NewsEntity.news_id)
                    .where(
                        NewsEntity.entity_id == entity_id,
                        News.processed.is_(True),
                        News.ingested_at >= baseline_start,
                        News.ingested_at < baseline_end,
                    )
                )
                or 0.0
            )
            baseline_daily = baseline_total / 30.0
            source_diversity = int(
                session.scalar(
                    select(func.count(func.distinct(News.source_id)))
                    .select_from(NewsEntity)
                    .join(News, News.id == NewsEntity.news_id)
                    .where(
                        NewsEntity.entity_id == entity_id,
                        News.processed.is_(True),
                        News.ingested_at >= current_start,
                    )
                )
                or 0
            )

            profile = session.get(EntityProfile, entity_id)
            if profile is None:
                profile = EntityProfile(entity_id=entity_id)
                session.add(profile)
                added += 1
            else:
                updated += 1

            profile.mention_freq_current = current_mentions
            profile.mention_freq_baseline = round(baseline_daily, 4)
            profile.source_diversity = source_diversity
            profile.trend_direction = _trend_direction(current_mentions, baseline_daily)
            profile.last_updated = now

        session.commit()
        total_profiles = int(session.query(EntityProfile).count())

    result = EntityProfilesUpdateResult(
        profiles_added=added,
        profiles_updated=updated,
        total_profiles=total_profiles,
    )
    log_event(
        logger,
        logging.INFO,
        "entity_profiles_updated",
        profiles_added=result.profiles_added,
        profiles_updated=result.profiles_updated,
        total_profiles=result.total_profiles,
    )
    return result
