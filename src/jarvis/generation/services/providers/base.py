"""Base provider contract for Layer 5."""

from __future__ import annotations

from abc import ABC, abstractmethod

from jarvis.generation.models.generation_models import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    ProviderConfig,
)


class LLMProviderError(RuntimeError):
    """Provider-level error that callers may recover from."""


class LLMAuthenticationError(LLMProviderError):
    """Provider rejected the current credentials."""


class LLMRateLimitError(LLMProviderError):
    """Provider rate-limited the current request."""


class LLMTimeoutError(LLMProviderError):
    """Provider timed out before returning a response."""


class AllProvidersFailedError(LLMProviderError):
    """All providers in the fallback chain failed."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("All configured LLM providers failed")


class LLMProvider(ABC):
    """Provider-agnostic async interface for LLM generation."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @property
    def provider_name(self) -> str:
        return self.config.provider_name

    @abstractmethod
    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        """Generate one response from the provider."""
