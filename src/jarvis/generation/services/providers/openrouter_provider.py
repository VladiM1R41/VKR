"""OpenRouter provider adapter for Layer 5."""

from __future__ import annotations

from jarvis.core.settings import get_settings
from jarvis.generation.models.generation_models import ProviderConfig
from jarvis.generation.services.providers.http_provider import HTTPLLMProvider


class OpenRouterProvider(HTTPLLMProvider):
    """HTTP provider for OpenRouter's OpenAI-compatible chat API."""

    def __init__(self, config: ProviderConfig | None = None) -> None:
        settings = get_settings()
        resolved = config or ProviderConfig(
            provider_name="openrouter",
            model_name=settings.jarvis_llm_model,
            timeout_sec=settings.jarvis_llm_timeout_sec,
            retry_attempts=settings.jarvis_llm_retry_attempts,
            max_input_tokens=settings.jarvis_llm_max_input_tokens,
            max_output_tokens=settings.jarvis_llm_max_output_tokens,
            temperature=settings.jarvis_llm_temperature,
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
        )
        headers: dict[str, str] = {}
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        if settings.openrouter_app_name:
            headers["X-Title"] = settings.openrouter_app_name
            headers["X-OpenRouter-Title"] = settings.openrouter_app_name
        super().__init__(
            resolved,
            endpoint_path="/chat/completions",
            default_headers=headers,
        )
