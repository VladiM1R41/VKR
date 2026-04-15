"""Rule-based citation validation for Layer 5."""

from __future__ import annotations

import re
from dataclasses import dataclass


_SOURCE_TOKEN = (
    r"(?:"
    r"[A-Za-zА-Яа-яЁё0-9&-]+(?:\s+[A-Za-zА-Яа-яЁё0-9&-]+){0,3}"
    r"|"
    r"[A-Za-z0-9-]+\.[A-Za-zА-Яа-яЁё]{2,4}"
    r")"
)
_KNOWN_SOURCES = {
    "тасс",
    "риа",
    "риа новости",
    "коммерсант",
    "коммерсантъ",
    "рбк",
    "bbc",
    "lenta.ru",
    "банк россии",
    "цб",
}
_SOURCE_PATTERNS = [
    re.compile(
        rf"(?:по\s+данным|по\s+информации|согласно|как\s+пишет)\s+({_SOURCE_TOKEN})(?=[,.;:!?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"({_SOURCE_TOKEN})\s+(?:сообщает|пишет)\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"источник[:\s]+({_SOURCE_TOKEN})(?=[,.;:!?]|$)",
        re.IGNORECASE,
    ),
    re.compile(rf"\(({_SOURCE_TOKEN})\)"),
]


@dataclass(frozen=True, slots=True)
class CitationIssue:
    text_snippet: str
    source_name: str
    issue_type: str


@dataclass(frozen=True, slots=True)
class CitationValidationResult:
    is_valid: bool
    cited_sources: list[str]
    valid_citations: list[str]
    invalid_citations: list[CitationIssue]
    total_citations: int


class CitationValidator:
    """Check that cited sources are present in the provided context."""

    def __init__(self, *, fuzzy_threshold: float = 0.7) -> None:
        self._fuzzy_threshold = fuzzy_threshold

    def validate(
        self,
        answer_text: str,
        documents_used: list[dict],
    ) -> CitationValidationResult:
        allowed_sources = {
            self._normalize_source_name(doc.get("source") or doc.get("source_name") or "")
            for doc in documents_used
            if doc.get("source") or doc.get("source_name")
        }
        cited_sources = self._extract_cited_sources(answer_text)

        valid_citations: list[str] = []
        invalid_citations: list[CitationIssue] = []
        for cited in cited_sources:
            normalized = self._normalize_source_name(cited)
            if normalized in allowed_sources:
                valid_citations.append(cited)
            else:
                invalid_citations.append(
                    CitationIssue(
                        text_snippet=self._find_citation_snippet(answer_text, cited),
                        source_name=cited,
                        issue_type="not_in_context",
                    )
                )

        return CitationValidationResult(
            is_valid=not invalid_citations,
            cited_sources=cited_sources,
            valid_citations=valid_citations,
            invalid_citations=invalid_citations,
            total_citations=len(cited_sources),
        )

    def _normalize_source_name(self, name: str) -> str:
        normalized = re.sub(r"\s+", " ", name.strip().lower().replace("ё", "е"))
        normalized = normalized.strip(".,;:!?'\"()[]{}")
        synonym_map = {
            "риа новости": "риа",
            "ria novosti": "риа",
            "информационное агентство россии": "риа",
            "коммерсантъ": "коммерсант",
            "цб рф": "цб",
            "банк россии": "цб",
            "центральный банк": "цб",
            "центробанк": "цб",
        }
        return synonym_map.get(normalized, normalized)

    def _extract_cited_sources(self, text: str) -> list[str]:
        sources: list[str] = []
        seen: set[str] = set()
        for pattern in _SOURCE_PATTERNS:
            for match in pattern.finditer(text):
                source = self._clean_source_candidate(match.group(1))
                if not source or not self._looks_like_source(source):
                    continue
                normalized = self._normalize_source_name(source)
                if normalized in seen:
                    continue
                sources.append(source)
                seen.add(normalized)
        return sources

    def _looks_like_source(self, value: str) -> bool:
        cleaned = value.strip()
        if len(cleaned) < 2:
            return False
        if re.search(r"\.[a-zа-я]{2,4}$", cleaned.lower()):
            return True
        if cleaned.lower() in _KNOWN_SOURCES:
            return True
        if any(ch.isupper() for ch in cleaned):
            return True
        return False

    @staticmethod
    def _clean_source_candidate(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned.strip(".,;:!?'\"()[]{}")

    @staticmethod
    def _find_citation_snippet(text: str, source_name: str) -> str:
        pos = text.lower().find(source_name.lower())
        if pos == -1:
            return source_name
        start = max(0, pos - 50)
        end = min(len(text), pos + len(source_name) + 50)
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet
