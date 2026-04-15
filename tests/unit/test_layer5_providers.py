from __future__ import annotations

import httpx
import pytest

from jarvis.generation.models.generation_models import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    ProviderConfig,
)
from jarvis.generation.services.providers import (
    AllProvidersFailedError,
    FallbackLLMProvider,
    GigaChatProvider,
    LLMAuthenticationError,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    YandexGPTProvider,
)
from jarvis.generation.services.providers.factory import _make_provider
from jarvis.generation.services.providers.http_provider import HTTPLLMProvider


class FakeProvider(LLMProvider):
    def __init__(self, provider_name: str, *, should_fail: bool = False) -> None:
        super().__init__(
            ProviderConfig(
                provider_name=provider_name,
                model_name=f"{provider_name}-model",
            )
        )
        self.should_fail = should_fail

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        if self.should_fail:
            raise LLMProviderError(f"{self.provider_name} failed")
        return LLMGenerationResponse(
            provider_name=self.provider_name,
            model_name=self.config.model_name,
            content=f"ok:{request.user_prompt}",
        )


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://provider.test/chat/completions")
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    responses: list[object] = []
    calls: int = 0

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, *, json: dict, headers: dict) -> object:
        type(self).calls += 1
        next_item = type(self).responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


class _TestHTTPLLMProvider(HTTPLLMProvider):
    def __init__(self, retry_attempts: int = 2) -> None:
        super().__init__(
            ProviderConfig(
                provider_name="test",
                model_name="test-model",
                base_url="https://provider.test",
                api_key="secret",
                retry_attempts=retry_attempts,
            ),
            endpoint_path="/chat/completions",
        )


def test_factory_supports_expected_provider_names() -> None:
    assert isinstance(_make_provider("gigachat"), GigaChatProvider)
    assert isinstance(_make_provider("yandexgpt"), YandexGPTProvider)


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        _make_provider("unknown-provider")


@pytest.mark.asyncio
async def test_fallback_provider_uses_first_successful_provider() -> None:
    chain = FallbackLLMProvider(
        [
            FakeProvider("primary", should_fail=True),
            FakeProvider("fallback", should_fail=False),
        ]
    )

    response = await chain.generate(
        LLMGenerationRequest(
            system_prompt="s",
            context="c",
            user_prompt="hello",
        )
    )

    assert response.provider_name == "fallback"
    assert response.content == "ok:hello"


@pytest.mark.asyncio
async def test_fallback_provider_raises_when_all_fail() -> None:
    chain = FallbackLLMProvider(
        [
            FakeProvider("primary", should_fail=True),
            FakeProvider("fallback", should_fail=True),
        ]
    )

    with pytest.raises(AllProvidersFailedError) as exc_info:
        await chain.generate(
            LLMGenerationRequest(
                system_prompt="s",
                context="c",
                user_prompt="hello",
            )
        )

    assert "primary" in exc_info.value.errors[0]


def test_request_model_keeps_metadata_and_overrides() -> None:
    request = LLMGenerationRequest(
        system_prompt="sys",
        context="ctx",
        user_prompt="query",
        max_output_tokens=777,
        temperature=0.4,
        metadata={"intent": "FACTUAL"},
    )

    assert request.max_output_tokens == 777
    assert request.temperature == 0.4
    assert request.metadata["intent"] == "FACTUAL"


@pytest.mark.asyncio
async def test_http_provider_retries_retryable_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import jarvis.generation.services.providers.http_provider as http_provider_module

    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.responses = [
        _FakeResponse(429, {}),
        _FakeResponse(
            200,
            {
                "model": "test-model",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        ),
    ]
    monkeypatch.setattr(http_provider_module.httpx, "AsyncClient", _FakeAsyncClient)

    provider = _TestHTTPLLMProvider(retry_attempts=2)
    response = await provider.generate(LLMGenerationRequest(user_prompt="hello"))

    assert response.content == "ok"
    assert _FakeAsyncClient.calls == 2


@pytest.mark.asyncio
async def test_http_provider_maps_timeout_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import jarvis.generation.services.providers.http_provider as http_provider_module

    request = httpx.Request("POST", "https://provider.test/chat/completions")
    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.responses = [httpx.ReadTimeout("timeout", request=request)]
    monkeypatch.setattr(http_provider_module.httpx, "AsyncClient", _FakeAsyncClient)

    provider = _TestHTTPLLMProvider(retry_attempts=0)

    with pytest.raises(LLMTimeoutError):
        await provider.generate(LLMGenerationRequest(user_prompt="hello"))


@pytest.mark.asyncio
async def test_http_provider_maps_auth_errors_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    import jarvis.generation.services.providers.http_provider as http_provider_module

    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.responses = [_FakeResponse(401, {})]
    monkeypatch.setattr(http_provider_module.httpx, "AsyncClient", _FakeAsyncClient)

    provider = _TestHTTPLLMProvider(retry_attempts=2)

    with pytest.raises(LLMAuthenticationError):
        await provider.generate(LLMGenerationRequest(user_prompt="hello"))

    assert _FakeAsyncClient.calls == 1


@pytest.mark.asyncio
async def test_http_provider_maps_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import jarvis.generation.services.providers.http_provider as http_provider_module

    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.responses = [_FakeResponse(429, {})]
    monkeypatch.setattr(http_provider_module.httpx, "AsyncClient", _FakeAsyncClient)

    provider = _TestHTTPLLMProvider(retry_attempts=0)

    with pytest.raises(LLMRateLimitError):
        await provider.generate(LLMGenerationRequest(user_prompt="hello"))
