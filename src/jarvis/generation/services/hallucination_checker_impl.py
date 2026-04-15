"""Rule-based groundedness checks for Layer 5."""

from __future__ import annotations

import re
from dataclasses import dataclass


MIN_OVERLAP_SCORE = 0.3
MIN_SUPPORTED_RATIO = 0.6
_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9-]+")
_STOP_WORDS = {
    "в", "на", "с", "по", "к", "у", "о", "от", "до", "из", "за", "для",
    "и", "а", "но", "или", "что", "как", "это", "не", "бы", "ли", "же",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "at", "to", "for", "with", "by", "from", "and",
    "or", "but", "that", "this", "it", "not",
}


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    claim_text: str
    is_supported: bool
    supporting_docs: list[int]
    confidence: float


@dataclass(frozen=True, slots=True)
class GroundednessResult:
    overall_score: float
    total_claims: int
    supported_claims: int
    unsupported_claims: list[ClaimCheck]
    is_acceptable: bool
    recommendation: str


class HallucinationChecker:
    def __init__(
        self,
        *,
        min_overlap: float = MIN_OVERLAP_SCORE,
        min_supported_ratio: float = MIN_SUPPORTED_RATIO,
    ) -> None:
        self._min_overlap = min_overlap
        self._min_supported_ratio = min_supported_ratio

    def check_groundedness(
        self,
        answer_text: str,
        documents: list[dict],
    ) -> GroundednessResult:
        claims = self._extract_claims(answer_text)
        if not claims:
            return GroundednessResult(
                overall_score=1.0,
                total_claims=0,
                supported_claims=0,
                unsupported_claims=[],
                is_acceptable=True,
                recommendation="ok",
            )

        claim_checks: list[ClaimCheck] = []
        for claim in claims:
            supported, doc_ids, score = self._check_claim(claim, documents)
            claim_checks.append(
                ClaimCheck(
                    claim_text=claim,
                    is_supported=supported,
                    supporting_docs=doc_ids,
                    confidence=score,
                )
            )

        supported_count = sum(1 for c in claim_checks if c.is_supported)
        unsupported = [c for c in claim_checks if not c.is_supported]
        ratio = supported_count / len(claim_checks)
        overall_score = sum(c.confidence for c in claim_checks) / len(claim_checks)
        is_acceptable = ratio >= self._min_supported_ratio

        if is_acceptable and not unsupported:
            recommendation = "ok"
        elif is_acceptable:
            recommendation = "minor_issues"
        else:
            recommendation = "needs_correction"

        return GroundednessResult(
            overall_score=round(overall_score, 3),
            total_claims=len(claim_checks),
            supported_claims=supported_count,
            unsupported_claims=unsupported,
            is_acceptable=is_acceptable,
            recommendation=recommendation,
        )

    @staticmethod
    def _extract_claims(text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        return [sent.strip() for sent in sentences if len(sent.strip()) >= 10]

    def _check_claim(
        self,
        claim: str,
        documents: list[dict],
    ) -> tuple[bool, list[int], float]:
        claim_tokens = self._tokenize(claim)
        if not claim_tokens:
            return True, [], 1.0

        best_score = 0.0
        best_doc_ids: list[int] = []
        for doc in documents:
            doc_text = " ".join(
                part for part in [doc.get("content") or "", doc.get("text") or "", doc.get("title") or ""]
                if part
            )
            if not doc_text:
                continue
            doc_tokens = self._tokenize(doc_text)
            if not doc_tokens:
                continue
            overlap = self._compute_overlap(claim_tokens, doc_tokens)
            news_id = int(doc.get("news_id", 0))
            if overlap > best_score:
                best_score = overlap
                best_doc_ids = [news_id]
            elif overlap == best_score and overlap > 0:
                best_doc_ids.append(news_id)

        is_supported = best_score >= self._min_overlap
        return is_supported, best_doc_ids, round(best_score, 3)

    @classmethod
    def _tokenize(cls, text: str) -> set[str]:
        tokens = []
        for raw in _TOKEN_RE.findall(text.lower().replace("ё", "е")):
            token = cls._normalize_token(raw)
            if token and token not in _STOP_WORDS and len(token) >= 2:
                tokens.append(token)
        return set(tokens)

    @staticmethod
    def _normalize_token(token: str) -> str:
        if token.startswith(("повыс", "повыш")):
            return "повыш"
        if token.startswith(("сниз", "сниж")):
            return "сниж"
        if token.startswith(("раст", "рос")):
            return "раст"
        if token.startswith(("банк", "центробанк", "центральн")):
            return "банк"
        if token.startswith("ставк"):
            return "ставк"
        if token.startswith("инфляц"):
            return "инфляц"

        for suffix in (
            "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими",
            "ать", "ять", "ить", "еть", "оть", "ти", "ый", "ий", "ая", "ое",
            "ые", "ие", "ых", "их", "ую", "юю", "ой", "ей", "ам", "ям", "ах",
            "ях", "ов", "ев", "ом", "ем", "а", "я", "ы", "и", "е", "о", "у",
            "ю", "ь",
        ):
            if len(token) > len(suffix) + 2 and token.endswith(suffix):
                return token[: -len(suffix)]
        return token

    @staticmethod
    def _compute_overlap(claim_tokens: set[str], doc_tokens: set[str]) -> float:
        if not claim_tokens:
            return 1.0
        intersection = claim_tokens & doc_tokens
        return len(intersection) / len(claim_tokens)
