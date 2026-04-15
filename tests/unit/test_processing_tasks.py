from jarvis.ingestion.tasks import celery_app
from jarvis.processing.tasks.processing_tasks import process_pending_news_batch_task
from jarvis.processing.tasks.analytics_tasks import (
    update_term_vocabulary_task,
    update_collocations_task,
)


def test_processing_task_is_registered() -> None:
    assert process_pending_news_batch_task.name == "jarvis.processing.process_pending_batch"
    assert process_pending_news_batch_task.name in celery_app.tasks


def test_processing_task_is_registered_in_beat_schedule() -> None:
    schedule = celery_app.conf.beat_schedule["process-pending-news"]
    assert schedule["task"] == process_pending_news_batch_task.name
    assert schedule["options"]["expires"] == schedule["schedule"]


def test_term_vocabulary_task_is_registered() -> None:
    assert update_term_vocabulary_task.name == "jarvis.processing.update_term_vocabulary"
    assert update_term_vocabulary_task.name in celery_app.tasks


def test_term_vocabulary_task_in_beat_schedule() -> None:
    schedule = celery_app.conf.beat_schedule["update-term-vocabulary"]
    assert schedule["task"] == update_term_vocabulary_task.name


def test_collocations_task_is_registered() -> None:
    assert update_collocations_task.name == "jarvis.processing.update_collocations"
    assert update_collocations_task.name in celery_app.tasks


def test_collocations_task_in_beat_schedule() -> None:
    schedule = celery_app.conf.beat_schedule["update-collocations"]
    assert schedule["task"] == update_collocations_task.name
