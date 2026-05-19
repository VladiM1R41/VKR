"""Celery application for Layer 1 orchestration."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from jarvis.core.logging import configure_logging
from jarvis.core.settings import get_settings


configure_logging()
settings = get_settings()

celery_app = Celery(
    "jarvis_collector",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    enable_utc=True,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_send_task_events=True,
    task_send_sent_event=True,
    task_default_queue="collector_queue",
    task_default_retry_delay=60,
    task_time_limit=600,
    task_soft_time_limit=540,
    task_queues={
        "collector_queue": {"exchange": "collector_queue", "routing_key": "collector"},
        "processing_queue": {"exchange": "processing_queue", "routing_key": "processing"},
        "enrichment_queue": {"exchange": "enrichment_queue", "routing_key": "enrichment"},
        "generation_queue": {"exchange": "generation_queue", "routing_key": "generation"},
    },
    beat_schedule={
        "dispatch-due-sources": {
            "task": "jarvis.ingestion.dispatch_due_sources",
            "schedule": settings.scheduler_tick_seconds,
            "options": {
                "expires": settings.scheduler_tick_seconds,
            },
        },
        "daily-health-check": {
            "task": "jarvis.ingestion.daily_health_check",
            "schedule": crontab(hour=3, minute=0),
        },
        "audit-dates-daily": {
            "task": "jarvis.ingestion.audit_dates",
            "schedule": crontab(hour=3, minute=15),
        },
        "process-pending-news": {
            "task": "jarvis.processing.process_pending_batch",
            "schedule": settings.processing_tick_seconds,
            "options": {
                "expires": settings.processing_tick_seconds,
            },
        },
        "update-term-vocabulary": {
            "task": "jarvis.processing.update_term_vocabulary",
            "schedule": crontab(hour="*/6", minute=0),  # каждые 6 часов
        },
        "update-collocations": {
            "task": "jarvis.processing.update_collocations",
            "schedule": crontab(hour=4, minute=0),  # ежедневно в 04:00
        },
        "update-entity-profiles": {
            "task": "jarvis.processing.update_entity_profiles",
            "schedule": crontab(minute=20),  # hourly entity trend refresh
        },
        "rebuild-user-embeddings": {
            "task": "jarvis.personalization.rebuild_user_embeddings",
            "schedule": crontab(hour="*/4", minute=30),
        },
        "build-alerts-batch": {
            "task": "jarvis.personalization.build_alert_batch",
            "schedule": 300.0,  # каждые 5 минут
            "options": {"expires": 290},
        },
    },
)

celery_app.autodiscover_tasks([
    "jarvis.ingestion.tasks",
    "jarvis.processing.tasks",
    "jarvis.personalization.tasks",
    "jarvis.generation.tasks",
])
