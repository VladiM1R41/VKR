"""Tasks for Layer 5 generation."""

from jarvis.generation.tasks.generation_tasks import generate_chat_answer_task
from jarvis.generation.tasks.tts_tasks import generate_digest_audio_task

__all__ = [
    "generate_chat_answer_task",
    "generate_digest_audio_task",
]
