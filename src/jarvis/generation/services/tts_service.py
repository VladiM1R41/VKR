"""TTS integration for Layer 5 digest audio generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import wave

from sqlalchemy.orm import Session

from jarvis.core.settings import get_settings
from jarvis.db.models import Digest


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TTSResult:
    audio_path: str
    duration_sec: float


class DigestTTSService:
    """Generate digest audio artifacts and attach them to digests."""

    def __init__(self, output_dir: str = "generated_audio") -> None:
        self._settings = get_settings()
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _estimate_duration(text: str) -> float:
        words = max(1, len(text.split()))
        return max(1.0, words / 2.5)

    def synthesize_digest(self, *, digest_id: int, text: str) -> TTSResult:
        """Create a valid WAV file placeholder for digest audio."""

        duration_sec = self._estimate_duration(text)
        sample_rate = 16000
        n_frames = int(sample_rate * duration_sec)
        audio_path = self._output_dir / f"digest_{digest_id}.wav"

        with wave.open(str(audio_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"\x00\x00" * n_frames)

        return TTSResult(audio_path=str(audio_path), duration_sec=duration_sec)

    def attach_audio_to_digest(self, session: Session, *, digest_id: int) -> TTSResult | None:
        if not self._settings.jarvis_tts_enabled:
            return None

        digest = session.get(Digest, digest_id)
        if digest is None or not digest.content_text.strip():
            return None

        result = self.synthesize_digest(digest_id=digest_id, text=digest.content_text)
        digest.audio_path = result.audio_path
        session.flush()
        return result
