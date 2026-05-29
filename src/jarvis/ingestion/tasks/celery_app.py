"""Celery application for background runtime orchestration."""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.schedules import crontab

from jarvis.core.logging import configure_logging
from jarvis.core.settings import Settings, get_settings


configure_logging()
settings = get_settings()


def build_beat_schedule(runtime_settings: Settings) -> dict[str, dict[str, Any]]:
    """Build the active Celery Beat schedule.

    Layer 1-2 jobs are part of the default always-on runtime. Layer 4
    personalization maintenance is opt-in because it is not required for the
    ingestion/processing loop and should not surprise local deployments.
    """

    schedule: dict[str, dict[str, Any]] = {
        "dispatch-due-sources": {
            "task": "jarvis.ingestion.dispatch_due_sources",
            "schedule": runtime_settings.scheduler_tick_seconds,
            "options": {
                "expires": runtime_settings.scheduler_tick_seconds,
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
            "schedule": runtime_settings.processing_tick_seconds,
            "options": {
                "expires": runtime_settings.processing_tick_seconds,
            },
        },
        "update-term-vocabulary": {
            "task": "jarvis.processing.update_term_vocabulary",
            "schedule": crontab(hour="*/6", minute=0),
        },
        "update-collocations": {
            "task": "jarvis.processing.update_collocations",
            "schedule": crontab(hour=4, minute=0),
        },
        "update-entity-profiles": {
            "task": "jarvis.processing.update_entity_profiles",
            "schedule": crontab(minute=20),
        },
    }

    if runtime_settings.celery_enable_layer4_schedule:
        schedule.update(
            {
                "rebuild-user-embeddings": {
                    "task": "jarvis.personalization.rebuild_user_embeddings",
                    "schedule": crontab(hour="*/4", minute=30),
                },
                "build-alerts-batch": {
                    "task": "jarvis.personalization.build_alert_batch",
                    "schedule": 300.0,
                    "options": {"expires": 290},
                },
            }
        )

    return schedule


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
        "analytics_queue": {"exchange": "analytics_queue", "routing_key": "analytics"},
        "enrichment_queue": {"exchange": "enrichment_queue", "routing_key": "enrichment"},
        "generation_queue": {"exchange": "generation_queue", "routing_key": "generation"},
    },
    imports=(
        "jarvis.ingestion.tasks.scheduler_tasks",
        "jarvis.ingestion.tasks.source_tasks",
        "jarvis.ingestion.tasks.enrichment_tasks",
        "jarvis.ingestion.tasks.health_tasks",
        "jarvis.processing.tasks.processing_tasks",
        "jarvis.processing.tasks.analytics_tasks",
        "jarvis.personalization.tasks.personalization_tasks",
        "jarvis.generation.tasks.generation_tasks",
        "jarvis.generation.tasks.tts_tasks",
    ),
    beat_schedule=build_beat_schedule(settings),
)

celery_app.autodiscover_tasks(
    [
        "jarvis.ingestion.tasks",
        "jarvis.processing.tasks",
        "jarvis.personalization.tasks",
        "jarvis.generation.tasks",
    ]
)
