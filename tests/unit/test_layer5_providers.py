from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from jarvis.core.settings import Settings
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
    OpenRouterProvider,
    YandexGPTProvider,
)
from jarvis.generation.services.providers.factory import _make_provider, build_primary_provider
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
    init_kwargs: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        type(self).init_kwargs.append(kwargs)

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
    assert isinstance(_make_provider("openrouter"), OpenRouterProvider)
    assert isinstance(_make_provider("yandexgpt"), YandexGPTProvider)


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        _make_provider("unknown-provider")


def test_factory_does_not_add_fake_fallback_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    import jarvis.generation.services.providers.factory as factory_module

    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="production",
            jarvis_llm_provider="gigachat",
            jarvis_llm_fallback_provider="",
            jarvis_llm_model="gigachat-max",
            jarvis_llm_timeout_sec=30.0,
            jarvis_llm_retry_attempts=2,
            jarvis_llm_max_input_tokens=20000,
            jarvis_llm_max_output_tokens=1200,
            jarvis_llm_temperature=0.2,
            gigachat_base_url=None,
            gigachat_api_key="token",
            gigachat_auth_key=None,
            gigachat_scope="GIGACHAT_API_PERS",
            gigachat_tls_verify=True,
            gigachat_ca_bundle=None,
        ),
    )

    provider = build_primary_provider()

    assert not isinstance(provider, FallbackLLMProvider)
    assert provider.provider_name == "gigachat"


def test_factory_does_not_add_fake_fallback_by_default_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.generation.services.providers.factory as factory_module

    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="development",
            jarvis_llm_provider="gigachat",
            jarvis_llm_fallback_provider="",
            jarvis_llm_allow_fake_fallback=False,
            jarvis_llm_model="gigachat-max",
            jarvis_llm_timeout_sec=30.0,
            jarvis_llm_retry_attempts=2,
            jarvis_llm_max_input_tokens=20000,
            jarvis_llm_max_output_tokens=1200,
            jarvis_llm_temperature=0.2,
            gigachat_base_url=None,
            gigachat_api_key="token",
            gigachat_auth_key=None,
            gigachat_scope="GIGACHAT_API_PERS",
            gigachat_tls_verify=True,
            gigachat_ca_bundle=None,
        ),
    )

    provider = build_primary_provider()

    assert not isinstance(provider, FallbackLLMProvider)
    assert provider.provider_name == "gigachat"


def test_factory_adds_fake_fallback_only_when_explicitly_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.generation.services.providers.factory as factory_module

    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="development",
            jarvis_llm_provider="gigachat",
            jarvis_llm_fallback_provider="",
            jarvis_llm_allow_fake_fallback=True,
            jarvis_llm_model="gigachat-max",
            jarvis_llm_timeout_sec=30.0,
            jarvis_llm_retry_attempts=2,
            jarvis_llm_max_input_tokens=20000,
            jarvis_llm_max_output_tokens=1200,
            jarvis_llm_temperature=0.2,
            gigachat_base_url=None,
            gigachat_api_key="token",
            gigachat_auth_key=None,
            gigachat_scope="GIGACHAT_API_PERS",
            gigachat_tls_verify=True,
            gigachat_ca_bundle=None,
        ),
    )

    provider = build_primary_provider()

    assert isinstance(provider, FallbackLLMProvider)
    assert [item.provider_name for item in provider._providers] == ["gigachat", "fake"]


def test_gigachat_uses_tls_verify_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import jarvis.generation.services.providers.gigachat_provider as gigachat_module

    monkeypatch.setattr(
        gigachat_module,
        "get_settings",
        lambda: SimpleNamespace(
            jarvis_llm_model="gigachat-max",
            jarvis_llm_timeout_sec=30.0,
            jarvis_llm_retry_attempts=2,
            jarvis_llm_max_input_tokens=20000,
            jarvis_llm_max_output_tokens=1200,
            jarvis_llm_temperature=0.2,
            gigachat_base_url=None,
            gigachat_api_key="token",
            gigachat_auth_key=None,
            gigachat_scope="GIGACHAT_API_PERS",
            gigachat_tls_verify=True,
            gigachat_ca_bundle=None,
        ),
    )

    provider = GigaChatProvider()

    assert provider._tls_verify is True


def test_gigachat_uses_ca_bundle_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import jarvis.generation.services.providers.gigachat_provider as gigachat_module

    monkeypatch.setattr(
        gigachat_module,
        "get_settings",
        lambda: SimpleNamespace(
            jarvis_llm_model="gigachat-max",
            jarvis_llm_timeout_sec=30.0,
            jarvis_llm_retry_attempts=2,
            jarvis_llm_max_input_tokens=20000,
            jarvis_llm_max_output_tokens=1200,
            jarvis_llm_temperature=0.2,
            gigachat_base_url=None,
            gigachat_api_key="token",
            gigachat_auth_key=None,
            gigachat_scope="GIGACHAT_API_PERS",
            gigachat_tls_verify=True,
            gigachat_ca_bundle="C:/certs/sber-ca.pem",
        ),
    )

    provider = GigaChatProvider()

    assert provider._tls_verify == "C:/certs/sber-ca.pem"


def test_settings_rejects_disabled_gigachat_tls_in_production() -> None:
    with pytest.raises(ValidationError, match="GIGACHAT_TLS_VERIFY"):
        Settings(APP_ENV="production", GIGACHAT_TLS_VERIFY=False)


def test_settings_requires_openrouter_api_key_when_enabled() -> None:
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        Settings(JARVIS_LLM_PROVIDER="openrouter", OPENROUTER_API_KEY="")


def test_openrouter_provider_uses_openai_compatible_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.generation.services.providers.openrouter_provider as openrouter_module

    monkeypatch.setattr(
        openrouter_module,
        "get_settings",
        lambda: SimpleNamespace(
            jarvis_llm_model="openrouter/owl-alpha",
            jarvis_llm_timeout_sec=120.0,
            jarvis_llm_retry_attempts=2,
            jarvis_llm_max_input_tokens=100000,
            jarvis_llm_max_output_tokens=12000,
            jarvis_llm_temperature=0.2,
            openrouter_base_url="https://openrouter.ai/api/v1",
            openrouter_api_key="openrouter-test-key",
            openrouter_site_url="http://localhost:5173",
            openrouter_app_name="Newscope",
        ),
    )

    provider = OpenRouterProvider()

    assert provider.provider_name == "openrouter"
    assert provider.config.model_name == "openrouter/owl-alpha"
    assert provider.config.base_url == "https://openrouter.ai/api/v1"
    assert provider.config.api_key == "openrouter-test-key"
    assert provider._endpoint_path == "/chat/completions"
    headers = provider._build_headers()
    assert headers["Authorization"] == "Bearer openrouter-test-key"
    assert headers["HTTP-Referer"] == "http://localhost:5173"
    assert headers["X-Title"] == "Newscope"
    assert headers["X-OpenRouter-Title"] == "Newscope"


def test_openrouter_payload_omits_output_limit_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.generation.services.providers.openrouter_provider as openrouter_module

    monkeypatch.setattr(
        openrouter_module,
        "get_settings",
        lambda: SimpleNamespace(
            jarvis_llm_model="openrouter/owl-alpha",
            jarvis_llm_timeout_sec=120.0,
            jarvis_llm_retry_attempts=2,
            jarvis_llm_max_input_tokens=100000,
            jarvis_llm_max_output_tokens=0,
            jarvis_llm_temperature=0.2,
            openrouter_base_url="https://openrouter.ai/api/v1",
            openrouter_api_key="openrouter-test-key",
            openrouter_site_url=None,
            openrouter_app_name="Newscope",
        ),
    )

    provider = OpenRouterProvider()
    payload = provider._build_payload(LLMGenerationRequest(user_prompt="hello"))

    assert payload["model"] == "openrouter/owl-alpha"
    assert "max_tokens" not in payload


@pytest.mark.asyncio
async def test_gigachat_http_client_receives_configured_tls_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jarvis.generation.services.providers.gigachat_provider as gigachat_module

    monkeypatch.setattr(
        gigachat_module,
        "get_settings",
        lambda: SimpleNamespace(
            jarvis_llm_model="gigachat-max",
            jarvis_llm_timeout_sec=30.0,
            jarvis_llm_retry_attempts=0,
            jarvis_llm_max_input_tokens=20000,
            jarvis_llm_max_output_tokens=1200,
            jarvis_llm_temperature=0.2,
            gigachat_base_url=None,
            gigachat_api_key="token",
            gigachat_auth_key=None,
            gigachat_scope="GIGACHAT_API_PERS",
            gigachat_tls_verify=True,
            gigachat_ca_bundle="C:/certs/sber-ca.pem",
        ),
    )
    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.init_kwargs = []
    _FakeAsyncClient.responses = [
        _FakeResponse(
            200,
            {
                "model": "gigachat-max",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    ]
    monkeypatch.setattr(gigachat_module.httpx, "AsyncClient", _FakeAsyncClient)

    provider = GigaChatProvider()
    response = await provider._post_with_retry(
        url="https://gigachat.test/chat/completions",
        payload={"messages": []},
        headers={"Authorization": "Bearer token"},
    )

    assert response.json()["choices"][0]["message"]["content"] == "ok"
    assert _FakeAsyncClient.init_kwargs[0]["verify"] == "C:/certs/sber-ca.pem"


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


def test_http_provider_omits_max_tokens_when_output_limit_is_disabled() -> None:
    provider = _TestHTTPLLMProvider(retry_attempts=0)

    payload = provider._build_payload(LLMGenerationRequest(user_prompt="hello"))

    assert "max_tokens" not in payload


def test_http_provider_sends_explicit_request_output_limit() -> None:
    provider = _TestHTTPLLMProvider(retry_attempts=0)

    payload = provider._build_payload(
        LLMGenerationRequest(user_prompt="hello", max_output_tokens=777)
    )

    assert payload["max_tokens"] == 777


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
