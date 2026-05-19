"""GigaChat provider adapter for Layer 5 — с OAuth2 авторизацией."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx

from jarvis.core.settings import get_settings
from jarvis.generation.models.generation_models import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    ProviderConfig,
)
from jarvis.generation.services.providers.base import LLMAuthenticationError, LLMProviderError
from jarvis.generation.services.providers.http_provider import HTTPLLMProvider

# OAuth-эндпоинт Sber для получения Bearer-токена
_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
# Базовый URL GigaChat REST API
_GIGACHAT_BASE = "https://gigachat.devices.sberbank.ru/api/v1"


class GigaChatProvider(HTTPLLMProvider):
    """HTTP-based provider для GigaChat с автоматическим обновлением OAuth2-токена.

    Поддерживает два режима аутентификации:
    - GIGACHAT_AUTH_KEY  — Authorization Key с личного кабинета (Base64 clientId:secret).
      Используется для автоматического получения/обновления Bearer-токена.
    - GIGACHAT_API_KEY   — прямой Bearer-токен (устаревший ручной режим).
    """

    _token: str | None = None
    _token_expires_at: float = 0.0

    def __init__(self, config: ProviderConfig | None = None) -> None:
        settings = get_settings()
        resolved = config or ProviderConfig(
            provider_name="gigachat",
            model_name=settings.jarvis_llm_model,
            timeout_sec=settings.jarvis_llm_timeout_sec,
            retry_attempts=settings.jarvis_llm_retry_attempts,
            max_input_tokens=settings.jarvis_llm_max_input_tokens,
            max_output_tokens=settings.jarvis_llm_max_output_tokens,
            temperature=settings.jarvis_llm_temperature,
            base_url=settings.gigachat_base_url or _GIGACHAT_BASE,
            api_key=settings.gigachat_api_key,  # может быть None — будет заменён OAuth-токеном
        )
        super().__init__(resolved, endpoint_path="/chat/completions")
        self._auth_key = settings.gigachat_auth_key
        self._scope = settings.gigachat_scope
        self._tls_verify: bool | str = (
            settings.gigachat_ca_bundle
            if settings.gigachat_ca_bundle
            else settings.gigachat_tls_verify
        )

    # ── OAuth ────────────────────────────────────────────────────────────────

    async def _fetch_oauth_token(self) -> tuple[str, float]:
        """Получить Bearer-токен через OAuth2 по Authorization Key."""
        headers = {
            "Authorization": f"Basic {self._auth_key}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # Keep TLS verification configurable: use the system CA by default,
        # or pass a Sber CA bundle path through GIGACHAT_CA_BUNDLE.
        async with httpx.AsyncClient(verify=self._tls_verify, timeout=15.0) as client:
            try:
                resp = await client.post(
                    _OAUTH_URL,
                    headers=headers,
                    data={"scope": self._scope},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    raise LLMAuthenticationError(
                        "GigaChat OAuth failed: проверьте GIGACHAT_AUTH_KEY и GIGACHAT_SCOPE"
                    ) from exc
                raise LLMProviderError(f"GigaChat OAuth HTTP {exc.response.status_code}") from exc
            except httpx.RequestError as exc:
                raise LLMProviderError(f"GigaChat OAuth connection error: {exc}") from exc

        data = resp.json()
        token: str = data["access_token"]
        # expires_at приходит в миллисекундах
        expires_at: float = data.get("expires_at", 0) / 1000.0
        return token, expires_at

    async def _ensure_token(self) -> str:
        """Вернуть актуальный Bearer-токен, обновив при необходимости."""
        if not self._auth_key:
            # Нет Authorization Key — используем статичный api_key (ручной режим)
            if not self.config.api_key:
                raise LLMProviderError(
                    "GigaChat не настроен: укажите GIGACHAT_AUTH_KEY или GIGACHAT_API_KEY в .env"
                )
            return self.config.api_key

        # Обновляем токен за 60 секунд до истечения
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        self._token, self._token_expires_at = await self._fetch_oauth_token()
        return self._token

    # ── Override generate ─────────────────────────────────────────────────────

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        """Генерирует ответ через GigaChat API с автоматическим OAuth2."""
        token = await self._ensure_token()

        # Временно обновляем api_key в конфиге перед вызовом родительского метода
        saved_key = self.config.api_key
        self.config.api_key = token
        try:
            return await super().generate(request)
        finally:
            self.config.api_key = saved_key

    # ── Override HTTP client (GigaChat may require a custom Sber CA bundle) ──

    async def _post_with_retry(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> httpx.Response:
        """POST with retry and configurable TLS verification."""
        from jarvis.generation.services.providers.base import (
            LLMRateLimitError,
            LLMTimeoutError,
        )

        attempts = self.config.retry_attempts + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(
                    verify=self._tls_verify, timeout=self.config.timeout_sec
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    return response
            except httpx.TimeoutException:
                last_error = LLMTimeoutError("GigaChat request timed out")
            except httpx.HTTPStatusError as exc:
                last_error = self._map_http_status_error(exc)
                if not self._should_retry_status(exc.response.status_code, attempt, attempts):
                    raise last_error from exc
            except httpx.RequestError as exc:
                last_error = LLMProviderError(f"GigaChat connection error: {exc}")

            if attempt >= attempts and last_error is not None:
                raise last_error

        raise LLMProviderError("GigaChat request failed")
