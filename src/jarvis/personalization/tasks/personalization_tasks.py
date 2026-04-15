"""Celery tasks for production-like Layer 4 maintenance."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from jarvis.db.models import News, User
from jarvis.db.session import SyncSessionLocal
from jarvis.ingestion.tasks.celery_app import celery_app
from jarvis.personalization.services.user_embedding_service import UserEmbeddingService


logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="jarvis.personalization.rebuild_user_embeddings",
    queue="processing_queue",
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def rebuild_user_embeddings_task(self, limit_users: int = 100, per_user_limit: int = 50) -> dict[str, object]:
    """Periodically rebuild user centroid embeddings from fresh interactions."""
    service = UserEmbeddingService()
    with SyncSessionLocal() as session:
        results = service.rebuild_recent_user_embeddings(
            session,
            limit_users=limit_users,
            per_user_limit=per_user_limit,
        )
    updated = [item.user_id for item in results if item.updated]
    return {
        "selected_users": len(results),
        "updated_users": len(updated),
        "updated_user_ids": updated,
    }


@celery_app.task(
    bind=True,
    name="jarvis.personalization.build_alert_batch",
    queue="processing_queue",
    max_retries=2,
)
def build_alert_batch_task(
    self,
    lookback_minutes: int = 10,
    limit_users: int = 100,
) -> dict[str, object]:
    """Периодически проверяет свежие статьи на предмет алертов для всех активных пользователей.

    Запускается каждые 5 минут через Beat. Берёт статьи за последние lookback_minutes,
    вызывает AlertService для каждого пользователя.
    """
    from jarvis.personalization.services.alert_service import AlertService

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    service = AlertService()
    total_alerts = 0

    with SyncSessionLocal() as session:
        recent_news_ids = list(
            session.scalars(
                select(News.id)
                .where(News.ingested_at >= cutoff, News.processed.is_(True))
                .order_by(News.ingested_at.desc())
                .limit(500)
            ).all()
        )
        if not recent_news_ids:
            return {"users_processed": 0, "alerts_generated": 0}

        user_ids = list(
            session.scalars(select(User.id).order_by(User.id).limit(limit_users)).all()
        )
        for user_id in user_ids:
            try:
                batch = service.build_alert_batch(
                    session,
                    user_id=int(user_id),
                    news_ids=[int(nid) for nid in recent_news_ids],
                )
                total_alerts += len(batch.alerts)
            except Exception:
                logger.exception("build_alert_batch_task: ошибка для user_id=%s", user_id)

    return {"users_processed": len(user_ids), "alerts_generated": total_alerts}
