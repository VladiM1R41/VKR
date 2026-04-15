"""Core models for Layer 5 provider abstraction."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProviderConfig(BaseModel):
    """Resolved provider configuration from settings."""

    model_config = ConfigDict(protected_namespaces=())

    provider_name: str
    model_name: str
    timeout_sec: float = 30.0
    retry_attempts: int = 2
    max_input_tokens: int = 20000
    max_output_tokens: int = 1200
    temperature: float = 0.2
    base_url: str | None = None
    api_key: str | None = None


class LLMGenerationRequest(BaseModel):
    """One provider-agnostic generation request."""

    model_config = ConfigDict(protected_namespaces=())

    system_prompt: str = Field(default="")
    user_prompt: str
    context: str = Field(default="")
    max_output_tokens: int | None = None
    temperature: float | None = None
    metadata: dict = Field(default_factory=dict)


class LLMGenerationResponse(BaseModel):
    """One provider-agnostic generation response."""

    model_config = ConfigDict(protected_namespaces=())

    provider_name: str
    model_name: str
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    finish_reason: str | None = None
    raw_response: dict | None = None
