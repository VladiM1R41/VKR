import pytest
from pydantic import ValidationError

from jarvis.core.settings import Settings
from jarvis.ingestion.tasks import celery_app
from jarvis.ingestion.tasks.enrichment_tasks import enrich_source_pending_task
from jarvis.ingestion.tasks.health_tasks import audit_dates_task, daily_health_check_task
from jarvis.ingestion.tasks.scheduler_tasks import dispatch_due_sources_task
from jarvis.ingestion.tasks.source_tasks import collect_source_task


def test_celery_app_uses_utc_and_safe_worker_settings() -> None:
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.timezone == "UTC"
    assert celery_app.conf.broker_connection_retry_on_startup is True
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_time_limit == 600
    assert celery_app.conf.task_soft_time_limit == 540


def test_source_task_is_registered() -> None:
    assert collect_source_task.name == "jarvis.ingestion.collect_source"
    assert collect_source_task.name in celery_app.tasks


def test_enrichment_task_is_registered() -> None:
    assert enrich_source_pending_task.name == "jarvis.ingestion.enrich_source_pending"
    assert enrich_source_pending_task.name in celery_app.tasks


def test_scheduler_task_is_registered_in_beat_schedule() -> None:
    assert dispatch_due_sources_task.name == "jarvis.ingestion.dispatch_due_sources"
    assert dispatch_due_sources_task.name in celery_app.tasks
    assert celery_app.conf.beat_schedule["dispatch-due-sources"]["task"] == dispatch_due_sources_task.name
    assert (
        celery_app.conf.beat_schedule["dispatch-due-sources"]["options"]["expires"]
        == celery_app.conf.beat_schedule["dispatch-due-sources"]["schedule"]
    )


def test_settings_require_lock_ttl_to_stay_above_budget() -> None:
    with pytest.raises(ValidationError):
        Settings(
            SOURCE_BUDGET_SECONDS=300,
            SOURCE_LOCK_TTL_SECONDS=300,
        )


def test_daily_health_tasks_are_registered_with_expected_schedule() -> None:
    assert daily_health_check_task.name == "jarvis.ingestion.daily_health_check"
    assert audit_dates_task.name == "jarvis.ingestion.audit_dates"
    assert daily_health_check_task.name in celery_app.tasks
    assert audit_dates_task.name in celery_app.tasks

    daily_schedule = celery_app.conf.beat_schedule["daily-health-check"]
    audit_schedule = celery_app.conf.beat_schedule["audit-dates-daily"]

    assert daily_schedule["task"] == daily_health_check_task.name
    assert audit_schedule["task"] == audit_dates_task.name
    assert str(daily_schedule["schedule"]) == "<crontab: 0 3 * * * (m/h/dM/MY/d)>"
    assert str(audit_schedule["schedule"]) == "<crontab: 15 3 * * * (m/h/dM/MY/d)>"
