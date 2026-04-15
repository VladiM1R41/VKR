"""Prompt builder для Слоя 5 — шаблонизация промптов по intent и режиму.

Архитектура (по FINAL_LAYER_5_GUIDE.md, раздел 10):
  Каждая генерация состоит из трёх блоков:
    SYSTEM  — системная инструкция (кто LLM, какие правила)
    CONTEXT — документарный контекст (собранные источники)
    USER    — запрос пользователя

  Три intent-шаблона:
    FACTUAL     → короткий точный ответ по фактам
    CAPABILITY  → объяснение смысла и последствий
    INTENT      → аналитика, осторожный прогноз, альтернативы

Token budget (раздел 10.5):
  max input context: 18k-20k токенов
  reserve for answer: 1k-2k токенов
  Для русского языка: ~1.5-2 токена на слово (MVP: посимвольная эвристика).
"""

from __future__ import annotations

from dataclasses import dataclass

# ───────────────────────────────────────────────────────────
# Константы: token budget
# ───────────────────────────────────────────────────────────

# Для русского языка примерное соотношение: 1 токен ≈ 2-3 символа.
# Консервативная оценка: 1 токен = 2 символа (чтобы не перебрать).
_RU_CHARS_PER_TOKEN = 2.0


def estimate_token_count(text: str) -> int:
    """Оценить количество токенов в тексте для русского языка.

    MVP: посимвольная эвристика (консервативная, чтобы не перебрать лимит).
    В будущем можно заменить на tiktoken / официальную модель GigaChat.
    """
    if not text:
        return 0
    return max(1, int(len(text) / _RU_CHARS_PER_TOKEN))

# ───────────────────────────────────────────────────────────
# Константы: системные промпты
# ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT_COMMON = (
    "Ты — новостной аналитик системы «Джарвис»."
    " Отвечай только по предоставленным источникам."
    " Не выдумывай факты."
    " Если подтверждений недостаточно — скажи об этом явно."
    " Для каждого важного утверждения указывай источник."
)

_SYSTEM_PROMPT_FACTUAL = (
    _SYSTEM_PROMPT_COMMON
    + " Давай краткий, точный ответ по существу."
)

_SYSTEM_PROMPT_CAPABILITY = (
    _SYSTEM_PROMPT_COMMON
    + " Объясни смысл ситуации и её возможные последствия."
    " Используй структуру: состояние → динамика → прогноз."
    " Если уверенность невысока — упомяни альтернативные гипотезы."
)

_SYSTEM_PROMPT_INTENT = (
    _SYSTEM_PROMPT_COMMON
    + " Проведи аналитический разбор."
    " Используй структуру: состояние → динамика → прогноз."
    " Будь осторожен с прогнозами — явно указывай степень уверенности."
    " Приводи альтернативные сценарии при низкой уверенности."
)

_SYSTEM_PROMPT_DIGEST = (
    _SYSTEM_PROMPT_COMMON
    + " Составь связный новостной дайджест из предоставленных материалов."
    " Сгруппируй новости по событиям."
    " Пиши связным текстом, подходящим для чтения и озвучки."
    " Для каждого события укажи источники."
)

_SYSTEM_PROMPT_ALERT = (
    _SYSTEM_PROMPT_COMMON
    + " Составь короткое push-уведомление об одном ключевом факте."
    " Максимум один-два источника."
    " Без длинной аналитики."
)

# ───────────────────────────────────────────────────────────
# Константы: контекстный блок (один документ)
# ───────────────────────────────────────────────────────────

# Шаблон для одного документа в контексте.
# Поля заполняются из SearchResult / PersonalizedResult / News.
_DOCUMENT_TEMPLATE = (
    "[Doc {index}]\n"
    "source: {source_name}\n"
    "date: {published_at}\n"
    "title: {title}\n"
    "content: {content}"
)

# ───────────────────────────────────────────────────────────
# Константы: инструкции для LLM по формату ответа
# ───────────────────────────────────────────────────────────

_INSTRUCTION_FACTUAL = (
    "\n\nОтветь кратко (3-5 предложений)."
    " Для каждого утверждения указывай источник в скобках, например: (ТАСС)."
)

_INSTRUCTION_CAPABILITY = (
    "\n\nОтвет дай по структуре: состояние → динамика → прогноз."
    " Для каждого утверждения указывай источник в скобках, например: (РИА Новости)."
    " Если есть противоречия между источниками — упомяни их."
)

_INSTRUCTION_INTENT = (
    "\n\nОтвет дай по структуре: состояние → динамика → прогноз."
    " Для каждого утверждения указывай источник в скобках, например: (Коммерсантъ)."
    " Приведи основной прогноз и альтернативный сценарий."
    " Явно укажи степень уверенности для каждого прогноза."
)

_INSTRUCTION_DIGEST = (
    "\n\nСоставь связный дайджест."
    " Сгруппируй по событиям, для каждого события — краткое описание и источники."
    " Пиши связным текстом, подходящим для чтения вслух."
)

_INSTRUCTION_ALERT = (
    "\n\nНапиши одно короткое предложение (максимум 30 слов)."
    " Укажи источник в скобках."
)


# ───────────────────────────────────────────────────────────
# Data-классы
# ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class DocumentContext:
    """Компактное представление одного документа для контекста."""
    index: int
    news_id: int | None
    source_name: str
    published_at: str
    title: str
    content: str  # snippet или сжатый content


@dataclass(frozen=True, slots=True)
class PromptResult:
    """Результат сборки промпта — готовые три блока."""
    system_prompt: str
    context_block: str
    user_prompt: str


# ───────────────────────────────────────────────────────────
# Типы генерации (intent / режим)
# ───────────────────────────────────────────────────────────

GenerationMode = str  # "factual" | "capability" | "intent" | "digest" | "alert"

_MODE_SYSTEM: dict[GenerationMode, str] = {
    "factual": _SYSTEM_PROMPT_FACTUAL,
    "capability": _SYSTEM_PROMPT_CAPABILITY,
    "intent": _SYSTEM_PROMPT_INTENT,
    "digest": _SYSTEM_PROMPT_DIGEST,
    "alert": _SYSTEM_PROMPT_ALERT,
}

_MODE_INSTRUCTION: dict[GenerationMode, str] = {
    "factual": _INSTRUCTION_FACTUAL,
    "capability": _INSTRUCTION_CAPABILITY,
    "intent": _INSTRUCTION_INTENT,
    "digest": _INSTRUCTION_DIGEST,
    "alert": _INSTRUCTION_ALERT,
}


# ───────────────────────────────────────────────────────────
# Основная функция: сборка промпта
# ───────────────────────────────────────────────────────────

def build_prompt(
    mode: GenerationMode,
    user_query: str,
    documents: list[DocumentContext],
    custom_system: str | None = None,
) -> PromptResult:
    """Собрать полный промпт из SYSTEM / CONTEXT / USER блоков.

    Args:
        mode: режим генерации (factual / capability / intent / digest / alert).
        user_query: запрос пользователя (или пустота для digest/alert).
        documents: список документов для контекста.
        custom_system: опциональная замена системного промпта.

    Returns:
        PromptResult с тремя блоками.
    """
    system = custom_system or _MODE_SYSTEM[mode]
    context = _build_context_block(documents)
    user = _build_user_prompt(mode, user_query, documents)
    return PromptResult(
        system_prompt=system,
        context_block=context,
        user_prompt=user,
    )


def _build_context_block(documents: list[DocumentContext]) -> str:
    """Собрать CONTEXT-блок из списка документов."""
    if not documents:
        return "(Нет источников для ответа)\n"

    lines: list[str] = []
    for doc in documents:
        lines.append(
            _DOCUMENT_TEMPLATE.format(
                index=doc.index,
                source_name=doc.source_name,
                published_at=doc.published_at or "дата неизвестна",
                title=doc.title,
                content=doc.content,
            )
        )
    return "\n\n".join(lines) + "\n"


def _build_user_prompt(
    mode: GenerationMode,
    user_query: str,
    documents: list[DocumentContext],
) -> str:
    """Собрать USER-блок с инструкцией по режиму."""
    instruction = _MODE_INSTRUCTION[mode]

    if mode == "alert":
        # Для alert — query может быть пустым, используем title первого документа
        query = user_query or (documents[0].title if documents else "")
        return f"Напиши alert по событию: {query}{instruction}"

    if mode == "digest":
        return f"Составь дайджест из {len(documents)} источников ниже.{instruction}"

    return f"{user_query}{instruction}"


# ───────────────────────────────────────────────────────────
# Маппинг intent из Слоя 3 → GenerationMode
# ───────────────────────────────────────────────────────────

INTENT_TO_MODE: dict[str, GenerationMode] = {
    "FACTUAL": "factual",
    "CAPABILITY": "capability",
    "INTENT": "intent",
}


def intent_to_mode(intent: str) -> GenerationMode:
    """Преобразовать intent из Слоя 3 в GenerationMode.

    Слой 3 классифицирует запрос как FACTUAL / CAPABILITY / INTENT.
    Здесь маппим в внутренний режим промпта.
    """
    return INTENT_TO_MODE.get(intent.upper(), "factual")
