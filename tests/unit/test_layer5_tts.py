from __future__ import annotations

from pathlib import Path

from jarvis.generation.services.tts_service import DigestTTSService


def test_tts_service_creates_wave_file() -> None:
    output_dir = Path("test_artifacts/layer5_tts")
    output_dir.mkdir(parents=True, exist_ok=True)
    service = DigestTTSService(output_dir=str(output_dir))

    result = service.synthesize_digest(
        digest_id=5,
        text="Это тестовый дайджест для озвучки.",
    )

    audio_path = Path(result.audio_path)
    assert audio_path.exists()
    assert audio_path.suffix == ".wav"
    assert result.duration_sec >= 1.0
