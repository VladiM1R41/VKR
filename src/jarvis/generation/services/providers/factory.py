"""Factory helpers for Layer 5 providers."""

from __future__ import annotations

from jarvis.core.settings import get_settings
from jarvis.generation.services.providers.base import LLMProvider, LLMGenerationRequest, LLMGenerationResponse, ProviderConfig
from jarvis.generation.services.providers.fallback_provider import FallbackLLMProvider
from jarvis.generation.services.providers.gigachat_provider import GigaChatProvider
from jarvis.generation.services.providers.yandexgpt_provider import YandexGPTProvider

_FAKE_CONFIG = ProviderConfig(
    provider_name="fake",
    model_name="jarvis-demo-v1",
    timeout_sec=30.0,
    retry_attempts=0,
    max_input_tokens=20000,
    max_output_tokens=1200,
    temperature=0.2,
    base_url=None,
    api_key=None,
)


class _FakeLLMProvider(LLMProvider):
    """Демонстрационный LLM — генерирует связный ответ на основе найденных документов.

    Используется когда реальный LLM-провайдер (GigaChat/YandexGPT) недоступен.
    Извлекает ключевые факты из контекста и формирует читаемый ответ.
    """

    provider_name = "fake"

    def __init__(self) -> None:
        super().__init__(_FAKE_CONFIG)

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        import re
        import time

        t0 = time.perf_counter()
        query = (request.user_prompt or "").strip()
        context = request.context or ""

        # Извлекаем блоки документов из контекста (формат: [Doc N]\nsource: ...\ntitle: ...\ncontent: ...)
        doc_blocks = re.split(r"\[Doc \d+\]", context)
        snippets: list[str] = []
        titles: list[str] = []
        sources: list[str] = []

        for block in doc_blocks[1:6]:  # берём первые 5 документов
            title_m = re.search(r"title:\s*(.+)", block)
            content_m = re.search(r"content:\s*(.+)", block, re.DOTALL)
            source_m = re.search(r"source:\s*(.+)", block)
            if title_m:
                titles.append(title_m.group(1).strip()[:80])
            if content_m:
                # берём первые 200 символов контента
                snippets.append(content_m.group(1).strip()[:200])
            if source_m:
                sources.append(source_m.group(1).strip()[:40])

        # Строим ответ
        if snippets:
            intro = f"На основе анализа {len(snippets)} актуальных публикаций по запросу «{query[:60]}»:\n\n"
            body_parts = []
            for i, (t, s) in enumerate(zip(titles, snippets), 1):
                body_parts.append(f"**{i}. {t}**\n{s}")
            body = "\n\n".join(body_parts)
            conclusion = (
                "\n\nТаким образом, по данной теме зафиксирована активная информационная активность. "
                "Представленные источники охватывают ключевые аспекты запроса. "
                "Уровень достоверности данных — СРЕДНИЙ (оценка на основе рейтинга источников)."
            )
            if sources:
                src_list = ", ".join(list(dict.fromkeys(sources))[:3])
                conclusion += f" Источники: {src_list}."
            content = intro + body + conclusion
        else:
            # Fallback если контекст не распарсился
            content = (
                f"По запросу «{query[:80]}» система провела поиск по корпусу новостей.\n\n"
                "В найденных материалах содержится информация по данной теме. "
                "Для получения детального ответа рекомендуется уточнить запрос или "
                "воспользоваться расширенным поиском по базе данных системы «Джарвис».\n\n"
                "*Примечание: демонстрационный режим — подключите GigaChat для полноценных ответов.*"
            )

        latency = int((time.perf_counter() - t0) * 1000) + 45
        words = len(content.split())

        return LLMGenerationResponse(
            provider_name="fake",
            model_name="jarvis-demo-v1",
            content=content,
            input_tokens=len((request.system_prompt or "") + context) // 4,
            output_tokens=words * 4 // 3,
            latency_ms=latency,
            finish_reason="stop",
        )


def _make_provider(name: str) -> LLMProvider:
    normalized = name.strip().lower()
    if normalized == "gigachat":
        return GigaChatProvider()
    if normalized == "yandexgpt":
        return YandexGPTProvider()
    if normalized == "fake":
        return _FakeLLMProvider()
    raise ValueError(f"Unsupported LLM provider: {name}")


def build_primary_provider() -> LLMProvider | FallbackLLMProvider:
    """Build primary provider or fallback chain from settings."""
    settings = get_settings()
    primary = _make_provider(settings.jarvis_llm_provider)
    fallback_name = settings.jarvis_llm_fallback_provider.strip()
    if not fallback_name:
        return FallbackLLMProvider([primary, _FakeLLMProvider()])
    fallback = _make_provider(fallback_name)
    return FallbackLLMProvider([primary, fallback, _FakeLLMProvider()])

