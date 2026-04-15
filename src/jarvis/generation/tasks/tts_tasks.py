"""Celery tasks for Layer 5 digest TTS generation."""

from __future__ import annotations

import logging

from jarvis.core.logging import log_event
from jarvis.db.session import SyncSessionLocal
from jarvis.generation.services.tts_service import DigestTTSService
from jarvis.ingestion.tasks.celery_app import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(
    name="jarvis.generation.generate_digest_audio",
    queue="generation_queue",
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
    time_limit=120,
    soft_time_limit=100,
)
def generate_digest_audio_task(digest_id: int) -> dict:
    """Generate audio for a persisted digest and update audio_path."""

    service = DigestTTSService()
    with SyncSessionLocal() as session:
        result = service.attach_audio_to_digest(session, digest_id=digest_id)
        session.commit()

    if result is None:
        return {"status": "skipped", "digest_id": digest_id}

    log_event(
        logger,
        logging.INFO,
        "digest_audio_generated",
        digest_id=digest_id,
        audio_path=result.audio_path,
    )
    return {
        "status": "success",
        "digest_id": digest_id,
        "audio_path": result.audio_path,
        "duration_sec": result.duration_sec,
    }
