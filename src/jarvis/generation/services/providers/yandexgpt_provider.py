"""YandexGPT provider adapter for Layer 5."""

from __future__ import annotations

from jarvis.core.settings import get_settings
from jarvis.generation.models.generation_models import ProviderConfig
from jarvis.generation.services.providers.http_provider import HTTPLLMProvider


class YandexGPTProvider(HTTPLLMProvider):
    """HTTP-based provider wrapper for YandexGPT-compatible API."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        settings = get_settings()
        resolved = config or ProviderConfig(
            provider_name="yandexgpt",
            model_name=settings.jarvis_llm_model,
            timeout_sec=settings.jarvis_llm_timeout_sec,
            retry_attempts=settings.jarvis_llm_retry_attempts,
            max_input_tokens=settings.jarvis_llm_max_input_tokens,
            max_output_tokens=settings.jarvis_llm_max_output_tokens,
            temperature=settings.jarvis_llm_temperature,
            base_url=settings.yandexgpt_base_url,
            api_key=settings.yandexgpt_api_key,
        )
        super().__init__(resolved, endpoint_path="/chat/completions")
