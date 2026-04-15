"""Reusable HTTP provider base for OpenAI-like chat APIs."""

from __future__ import annotations

import time
from typing import Any

import httpx

from jarvis.generation.models.generation_models import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    ProviderConfig,
)
from jarvis.generation.services.providers.base import (
    LLMAuthenticationError,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)


class HTTPLLMProvider(LLMProvider):
    """Thin reusable base for providers reachable over HTTP."""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        endpoint_path: str,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(config)
        self._endpoint_path = endpoint_path
        self._default_headers = dict(default_headers or {})

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        if not self.config.base_url:
            raise LLMProviderError(f"{self.provider_name} base URL is not configured")

        url = f"{self.config.base_url.rstrip('/')}/{self._endpoint_path.lstrip('/')}"
        started = time.perf_counter()
        payload = self._build_payload(request)
        headers = self._build_headers()

        response = await self._post_with_retry(url=url, payload=payload, headers=headers)

        body = response.json()
        latency_ms = int((time.perf_counter() - started) * 1000)
        return self._parse_response(body, latency_ms=latency_ms)

    async def _post_with_retry(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> httpx.Response:
        attempts = self.config.retry_attempts + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout_sec) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    return response
            except httpx.TimeoutException as exc:
                last_error = LLMTimeoutError(f"{self.provider_name} request timed out")
            except httpx.HTTPStatusError as exc:
                last_error = self._map_http_status_error(exc)
                if not self._should_retry_status(exc.response.status_code, attempt, attempts):
                    raise last_error from exc
            except httpx.RequestError as exc:
                last_error = LLMProviderError(f"{self.provider_name} request failed: {exc}")

            if attempt >= attempts and last_error is not None:
                raise last_error

        raise LLMProviderError(f"{self.provider_name} request failed without a response")

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            **self._default_headers,
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _build_payload(self, request: LLMGenerationRequest) -> dict[str, Any]:
        return {
            "model": self.config.model_name,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {
                    "role": "user",
                    "content": self._compose_llm_content(request),
                },
            ],
            "temperature": (
                self.config.temperature if request.temperature is None else request.temperature
            ),
            "max_tokens": (
                self.config.max_output_tokens
                if request.max_output_tokens is None
                else request.max_output_tokens
            ),
        }

    @staticmethod
    def _compose_user_content(request: LLMGenerationRequest) -> str:
        if request.context:
            return f"Контекст:\n{request.context}\n\nЗапрос:\n{request.user_prompt}"
        return request.user_prompt

    @staticmethod
    def _compose_llm_content(request: LLMGenerationRequest) -> str:
        if request.context:
            return f"Context:\n{request.context}\n\nQuery:\n{request.user_prompt}"
        return request.user_prompt

    def _map_http_status_error(self, exc: httpx.HTTPStatusError) -> LLMProviderError:
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            return LLMAuthenticationError(f"{self.provider_name} authentication failed")
        if status_code == 429:
            return LLMRateLimitError(f"{self.provider_name} rate limit exceeded")
        return LLMProviderError(f"{self.provider_name} request failed with HTTP {status_code}")

    @staticmethod
    def _should_retry_status(status_code: int, attempt: int, max_attempts: int) -> bool:
        if attempt >= max_attempts:
            return False
        return status_code in {408, 409, 425, 429, 500, 502, 503, 504}

    def _parse_response(self, body: dict[str, Any], *, latency_ms: int) -> LLMGenerationResponse:
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = body.get("usage") or {}
        content = message.get("content")
        if not content:
            raise LLMProviderError(f"{self.provider_name} returned empty content")
        return LLMGenerationResponse(
            provider_name=self.provider_name,
            model_name=str(body.get("model") or self.config.model_name),
            content=str(content),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
            raw_response=body,
        )
