"""Fallback chain for Layer 5 providers."""

from __future__ import annotations

from jarvis.generation.models.generation_models import LLMGenerationRequest, LLMGenerationResponse
from jarvis.generation.services.providers.base import (
    AllProvidersFailedError,
    LLMProvider,
    LLMProviderError,
)


class FallbackLLMProvider:
    """Try multiple providers in priority order until one succeeds."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        self._providers = list(providers)
        if not self._providers:
            raise ValueError("FallbackLLMProvider requires at least one provider")

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        errors: list[str] = []
        for provider in self._providers:
            try:
                return await provider.generate(request)
            except LLMProviderError as exc:
                errors.append(f"{provider.provider_name}: {exc}")
                continue
        raise AllProvidersFailedError(errors)
