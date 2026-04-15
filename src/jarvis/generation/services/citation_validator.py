"""Citation validator для Слоя 5 — проверка что источники в ответе соответствуют документам из контекста.

Архитектура (по FINAL_LAYER_5_GUIDE.md, разделы 11.1, 11.4):
  После генерации ответа:
  1. Извлечь упоминания источников из текста ответа.
  2. Проверить что каждый упомянутый источник был в контексте (documents_used).
  3. Вернуть статус валидации + список проблемных цитат.

  Принцип: citation-aware output — каждое важное утверждение должно опираться
  на конкретный документ из контекста.

  MVP: rule-based проверка по именам источников (source_name), без глубокого
  NLP или LLM-as-judge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ───────────────────────────────────────────────────────────
# Data-классы
# ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class CitationIssue:
    """Одна проблемная цитата."""
    text_snippet: str       # фрагмент ответа с цитатой
    source_name: str        # упомянутый источник
    issue_type: str         # 'not_in_context' | 'mismatch'


@dataclass(frozen=True, slots=True)
class CitationValidationResult:
    """Результат проверки цитат."""
    is_valid: bool                      # все цитаты валидны
    cited_sources: list[str]            # все упомянутые источники
    valid_citations: list[str]          # подтверждённые источники
    invalid_citations: list[CitationIssue]  # проблемные цитаты
    total_citations: int                # всего цитат в ответе


# ───────────────────────────────────────────────────────────
# Константы
# ───────────────────────────────────────────────────────────

# Паттерны для извлечения имён источников из текста ответа
# Поддерживаемые форматы:
#   "По данным ТАСС..."
#   "как сообщает РИА Новости..."
#   "Источник: РБК"
#   "(ТАСС)"
#   "сообщает Коммерсантъ"
_CITATION_PATTERNS = [
    # "По данным <source>", "как сообщает <source>", "по информации <source>"
    re.compile(
        r'(?:по\s+данным|как\s+сообщает|сообщает|по\s+информации|со\s+ссылкой\s+на|как\s+пишет)\s+([А-ЯA-Z][А-Яа-яA-Za-z0-9\s&\-]+)',
        re.IGNORECASE
    ),
    # "Источник: <source>"
    re.compile(r'источник[:\s]+([А-ЯA-Z][А-Яа-яA-Za-z0-9\s&\-]+)', re.IGNORECASE),
    # "(<source>)" — источник в скобках
    re.compile(r'\(([А-ЯA-Z][А-Яа-яA-Za-z0-9\s&\-]{2,30})\)'),
    # "<source>:" — источник перед двоеточием
    re.compile(r'^([А-ЯA-Z][А-Яа-яA-Za-z0-9\s&\-]{2,30})\s*:', re.MULTILINE),
]


class CitationValidator:
    """Проверяет что источники в ответе соответствуют документам из контекста.

    Usage:
        validator = CitationValidator()
        result = validator.validate(
            answer_text="По данным ТАСС, ЦБ повысил ставку...",
            documents_used=[
                {"source": "ТАСС", "title": "..."},
                {"source": "РИА Новости", "title": "..."},
            ],
        )
        if not result.is_valid:
            # Обработать проблемные цитаты
    """

    def __init__(self, *, fuzzy_threshold: float = 0.7):
        """
        Args:
            fuzzy_threshold: порог fuzzy-совпадения имён источников (0.0-1.0).
                Для MVP не используется, зарезервировано.
        """
        self._fuzzy_threshold = fuzzy_threshold

    def validate(
        self,
        answer_text: str,
        documents_used: list[dict],
    ) -> CitationValidationResult:
        """Проверить цитаты в ответе.

        Args:
            answer_text: сгенерированный текст ответа.
            documents_used: список документов из контекста (ключ 'source' или 'source_name').

        Returns:
            CitationValidationResult с деталями валидации.
        """
        # Собираем допустимые источники из контекста
        allowed_sources: set[str] = set()
        for doc in documents_used:
            source = doc.get("source") or doc.get("source_name", "")
            if source:
                allowed_sources.add(self._normalize_source_name(source))

        # Извлекаем цитаты из ответа
        cited_sources = self._extract_cited_sources(answer_text)

        # Проверяем каждую цитату
        valid_citations: list[str] = []
        invalid_citations: list[CitationIssue] = []

        for cited in cited_sources:
            normalized = self._normalize_source_name(cited)
            if normalized in allowed_sources:
                valid_citations.append(cited)
            else:
                # Находим фрагмент текста где встречается цитата
                snippet = self._find_citation_snippet(answer_text, cited)
                invalid_citations.append(
                    CitationIssue(
                        text_snippet=snippet,
                        source_name=cited,
                        issue_type="not_in_context",
                    )
                )

        return CitationValidationResult(
            is_valid=len(invalid_citations) == 0,
            cited_sources=cited_sources,
            valid_citations=valid_citations,
            invalid_citations=invalid_citations,
            total_citations=len(cited_sources),
        )

    def _normalize_source_name(self, name: str) -> str:
        """Нормализовать имя источника для сравнения.

        Учитываем:
        - приведение к нижнему регистру
        - удаление лишних пробелов
        - базовые синонимы (РИА Новости → РИА)
        """
        normalized = name.strip().lower()
        # Удаляем лишние пробелы
        normalized = re.sub(r'\s+', ' ', normalized)

        # Базовые синонимы распространённых источников
        synonym_map = {
            "риа новости": "риа",
            "ria novosti": "риа",
            "информационное агентство россии": "риа",
            "коммерсантъ": "коммерсант",
            "коммерсант": "коммерсант",
            "цб рф": "цб",
            "банк россии": "цб",
            "центральный банк": "цб",
        }
        return synonym_map.get(normalized, normalized)

    def _extract_cited_sources(self, text: str) -> list[str]:
        """Извлечь все упомянутые источники из текста ответа."""
        sources: list[str] = []
        seen: set[str] = set()

        for pattern in _CITATION_PATTERNS:
            for match in pattern.finditer(text):
                source = match.group(1).strip()
                # Очищаем от лишних символов в конце
                source = re.sub(r'[.,;:\s]+$', '', source).strip()
                if source and source not in seen and len(source) >= 2:
                    sources.append(source)
                    seen.add(source)

        return sources

    @staticmethod
    def _find_citation_snippet(text: str, source_name: str) -> str:
        """Найти фрагмент текста где упоминается источник."""
        # Ищем первое вхождение источника
        pos = text.lower().find(source_name.lower())
        if pos == -1:
            return source_name

        # Берём контекст: 50 символов до и 50 после
        start = max(0, pos - 50)
        end = min(len(text), pos + len(source_name) + 50)
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet

from jarvis.generation.services.citation_validator_v2 import (  # noqa: E402
    CitationIssue,
    CitationValidationResult,
    CitationValidator,
)
