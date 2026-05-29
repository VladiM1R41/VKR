"""Rule-based citation validation for Layer 5."""

from __future__ import annotations

import re
from dataclasses import dataclass


_SOURCE_WORD = r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9&/-]*"
_SOURCE_DOMAIN = r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
_SOURCE_ATOM = rf"(?:{_SOURCE_DOMAIN}|{_SOURCE_WORD})"
_SOURCE_TOKEN = rf"{_SOURCE_ATOM}(?:\s+{_SOURCE_ATOM}){{0,3}}"
_TRAILING_PUNCT_RE = re.compile(r"^[\s'\"“”«»()\[\]{}.,;:!?]+|[\s'\"“”«»()\[\]{}.,;:!?]+$")

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
_NON_SOURCE_ACRONYMS = {
    "ai",
    "асду",
    "cpu",
    "gpu",
    "iiot",
    "iot",
    "llm",
    "mws ai",
}

_PREFIX_PATTERNS = [
    re.compile(rf"(?:по\s+данным|по\s+информации|согласно)\s+({_SOURCE_TOKEN})(?=[,.;:!?]|$)", re.IGNORECASE),
    re.compile(rf"как\s+(?:сообщает|пишет)\s+({_SOURCE_TOKEN})(?=[,.;:!?]|$)", re.IGNORECASE),
    re.compile(rf"источники?[:\s]+({_SOURCE_TOKEN})(?=[,.;:!?]|$)", re.IGNORECASE),
]
_POSTFIX_PATTERNS = [
    re.compile(rf"({_SOURCE_TOKEN})\s+(?:сообщает|пишет)\b", re.IGNORECASE),
    re.compile(rf"\(({_SOURCE_TOKEN})\)", re.IGNORECASE),
]
_DOC_REF_RE = re.compile(r"\[\s*doc\s+(\d+)\s*\]", re.IGNORECASE)
_PAREN_WITH_DOC_RE = re.compile(r"\(([^()]*\[\s*doc\s+\d+\s*\][^()]*)\)", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_SOURCES_BLOCK_RE = re.compile(
    r"(?:^|\n)\s*(?:#{1,6}\s*)?\**источники?\**\s*:\s*\n*(.+?)\Z",
    re.IGNORECASE | re.DOTALL,
)


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
        allowed_doc_refs = {
            f"doc {int(doc['index'])}"
            for doc in documents_used
            if doc.get("index") is not None
        }
        if not allowed_doc_refs:
            allowed_doc_refs = {
                f"doc {idx}"
                for idx, doc in enumerate(documents_used, start=1)
                if doc.get("source") or doc.get("source_name") or doc.get("news_id") is not None
            }
        cited_sources = self._extract_cited_sources(answer_text)

        valid_citations: list[str] = []
        invalid_citations: list[CitationIssue] = []
        for cited in cited_sources:
            normalized = self._normalize_source_name(cited)
            if normalized in allowed_sources or normalized in allowed_doc_refs:
                valid_citations.append(cited)
                continue
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
        normalized = _TRAILING_PUNCT_RE.sub("", normalized)
        doc_match = _DOC_REF_RE.fullmatch(normalized)
        if doc_match:
            return f"doc {int(doc_match.group(1))}"
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

        for match in _DOC_REF_RE.finditer(text):
            self._append_source(sources, seen, f"Doc {int(match.group(1))}", allow_doc=True)

        for match in _PAREN_WITH_DOC_RE.finditer(text):
            inside = match.group(1)
            without_doc = _DOC_REF_RE.sub("", inside)
            without_date = _ISO_DATE_RE.sub("", without_doc)
            for part in re.split(r"[,;]", without_date):
                source = self._clean_source_candidate(part)
                if source:
                    self._append_source(sources, seen, source)

        for source in self._extract_sources_block(text):
            self._append_source(sources, seen, source)

        for pattern in _PREFIX_PATTERNS + _POSTFIX_PATTERNS:
            for match in pattern.finditer(text):
                source = self._clean_source_candidate(match.group(1))
                self._append_source(sources, seen, source)

        return sources

    def _extract_sources_block(self, text: str) -> list[str]:
        """Extract human-readable source names from a final "Источники:" block."""
        result: list[str] = []
        for match in _SOURCES_BLOCK_RE.finditer(text):
            block = match.group(1)
            for raw_line in block.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                line = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line)
                line = re.sub(r"https?://\S+", "", line).strip()
                candidate = re.split(r"\s+[—–-]\s+", line, maxsplit=1)[0]
                candidate = re.split(r"\.\s+[\"«“]", candidate, maxsplit=1)[0]
                candidate = re.split(r":\s+[\"«“]", candidate, maxsplit=1)[0]
                candidate = self._clean_source_candidate(candidate)
                if candidate:
                    result.append(candidate)
        return result

    def _append_source(
        self,
        sources: list[str],
        seen: set[str],
        source: str,
        *,
        allow_doc: bool = False,
    ) -> None:
        if not source:
            return
        if not allow_doc and not self._looks_like_source(source):
            return
        normalized = self._normalize_source_name(source)
        if normalized in seen:
            return
        sources.append(source)
        seen.add(normalized)

    def _looks_like_source(self, value: str) -> bool:
        cleaned = self._clean_source_candidate(value)
        if len(cleaned) < 2:
            return False

        lowered = cleaned.lower()
        if lowered in {"как", "по", "согласно", "источник", "об этом"}:
            return False
        if "." in cleaned:
            return True
        if lowered in _KNOWN_SOURCES:
            return True
        if lowered in _NON_SOURCE_ACRONYMS:
            return False

        tokens = cleaned.split()
        if tokens and all(self._is_short_acronym(token) for token in tokens):
            return False

        if any(ch.isupper() for ch in cleaned):
            return True
        return False

    @staticmethod
    def _is_short_acronym(value: str) -> bool:
        letters = [ch for ch in value if ch.isalpha()]
        if not letters or len(letters) > 6:
            return False
        return all(ch.upper() == ch for ch in letters)

    @staticmethod
    def _clean_source_candidate(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        cleaned = re.sub(r"^(?:а|и|но)\s+", "", cleaned, flags=re.IGNORECASE)
        return _TRAILING_PUNCT_RE.sub("", cleaned)

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
