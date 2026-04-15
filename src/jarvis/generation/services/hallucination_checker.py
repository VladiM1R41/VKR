"""Hallucination checker для Слоя 5 — проверка что ответ grounded на документах.

Архитектура (по FINAL_LAYER_5_GUIDE.md, разделы 11.3, 11.4):
  После генерации ответа:
  1. Извлечь factual claims из текста ответа (MVP: sentences).
  2. Проверить что каждый claim подтверждается хотя бы одним документом.
  3. Пометить неподтверждённые claims.
  4. Вернуть статус groundedness + рекомендации по коррекции.

  Принцип: groundedness важнее красоты — неподтверждённые утверждения
  должны быть помечены или удалены.

  MVP: rule-based проверка через лексическое перекрытие ключевых слов
  между claim и документами. Не использует LLM-as-judge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ───────────────────────────────────────────────────────────
# Data-классы
# ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ClaimCheck:
    """Один проверенный claim."""
    claim_text: str           # текст утверждения
    is_supported: bool        # подтверждён ли документами
    supporting_docs: list[int]  # news_id подтверждающих документов
    confidence: float         # 0.0-1.0, насколько уверенно подтверждён


@dataclass(frozen=True, slots=True)
class GroundednessResult:
    """Результат проверки groundedness ответа."""
    overall_score: float              # 0.0-1.0, общая groundedness
    total_claims: int                 # всего claims
    supported_claims: int             # подтверждённых claims
    unsupported_claims: list[ClaimCheck]  # неподтверждённые
    is_acceptable: bool               # можно ли считать ответ приемлемым
    recommendation: str               # "ok" | "minor_issues" | "needs_correction"


# ───────────────────────────────────────────────────────────
# Константы
# ───────────────────────────────────────────────────────────

# Минимальный порог lexical overlap для подтверждения claim
MIN_OVERLAP_SCORE = 0.3

# Минимальный процент подтверждённых claims для acceptable
MIN_SUPPORTED_RATIO = 0.6

# Стоп-слова которые не учитываются при overlap (базовые)
_STOP_WORDS = {
    "в", "на", "с", "по", "к", "у", "о", "от", "до", "из", "за", "для",
    "и", "а", "но", "или", "что", "как", "это", "не", "бы", "ли", "же",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "at", "to", "for", "with", "by", "from", "and",
    "or", "but", "that", "this", "it", "not",
}


class HallucinationChecker:
    """Проверяет что ответ grounded на предоставленных документах.

    MVP: rule-based через lexical overlap между claims и документами.

    Usage:
        checker = HallucinationChecker()
        result = checker.check_groundedness(
            answer_text="ЦБ повысил ставку на 0.5% до 16%.",
            documents=[
                {"news_id": 1, "content": "Банк России поднял ключевую ставку..."},
            ],
        )
        if not result.is_acceptable:
            # Ответ содержит слишком много неподтверждённого
    """

    def __init__(
        self,
        *,
        min_overlap: float = MIN_OVERLAP_SCORE,
        min_supported_ratio: float = MIN_SUPPORTED_RATIO,
    ):
        self._min_overlap = min_overlap
        self._min_supported_ratio = min_supported_ratio

    def check_groundedness(
        self,
        answer_text: str,
        documents: list[dict],
    ) -> GroundednessResult:
        """Проверить groundedness ответа.

        Args:
            answer_text: сгенерированный текст ответа.
            documents: список документов из контекста.
                Каждый dict должен иметь 'news_id' и 'content'/'text'/'title'.

        Returns:
            GroundednessResult с оценкой и рекомендациями.
        """
        # 1. Извлечь claims из ответа (MVP: предложения)
        claims = self._extract_claims(answer_text)

        if not claims:
            # Нет claims — считаем acceptable
            return GroundednessResult(
                overall_score=1.0,
                total_claims=0,
                supported_claims=0,
                unsupported_claims=[],
                is_acceptable=True,
                recommendation="ok",
            )

        # 2. Проверить каждый claim
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

        # 3. Агрегировать результат
        supported_count = sum(1 for c in claim_checks if c.is_supported)
        unsupported = [c for c in claim_checks if not c.is_supported]
        ratio = supported_count / len(claim_checks) if claim_checks else 1.0

        # Общая оценка: средний confidence всех claims
        overall_score = (
            sum(c.confidence for c in claim_checks) / len(claim_checks)
            if claim_checks else 1.0
        )

        is_acceptable = ratio >= self._min_supported_ratio

        if is_acceptable and len(unsupported) == 0:
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
        """Извлечь factual claims из текста (MVP: предложения).

        Разбиваем по предложениям, фильтруем пустые и слишком короткие.
        """
        # Разделяем по концам предложений
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())

        claims: list[str] = []
        for sent in sentences:
            sent = sent.strip()
            if len(sent) >= 15:  # игнорируем очень короткие
                claims.append(sent)

        return claims

    def _check_claim(
        self,
        claim: str,
        documents: list[dict],
    ) -> tuple[bool, list[int], float]:
        """Проверить один claim против документов.

        Returns:
            (is_supported, supporting_doc_ids, confidence_score)
        """
        claim_tokens = self._tokenize(claim)
        if not claim_tokens:
            return True, [], 1.0  # пустой claim считаем подтверждённым

        best_score = 0.0
        best_doc_ids: list[int] = []

        for doc in documents:
            # Собираем текст документа
            doc_text = (
                (doc.get("content") or "") + " " +
                (doc.get("text") or "") + " " +
                (doc.get("title") or "")
            ).strip()

            if not doc_text:
                continue

            doc_tokens = self._tokenize(doc_text)
            if not doc_tokens:
                continue

            # Lexical overlap: Jaccard-like similarity
            overlap = self._compute_overlap(claim_tokens, doc_tokens)
            news_id = doc.get("news_id", 0)

            if overlap > best_score:
                best_score = overlap
                best_doc_ids = [news_id]
            elif overlap == best_score and overlap > 0:
                best_doc_ids.append(news_id)

        is_supported = best_score >= self._min_overlap
        return is_supported, best_doc_ids, round(best_score, 3)

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Токенизировать текст: lowercase, удалить стоп-слова."""
        tokens = re.findall(r'[а-яa-z0-9\-]+', text.lower())
        return {t for t in tokens if t not in _STOP_WORDS and len(t) >= 2}

    @staticmethod
    def _compute_overlap(claim_tokens: set[str], doc_tokens: set[str]) -> float:
        """Вычислить lexical overlap score.

        Используем модифицированный Jaccard: |intersection| / |claim_tokens|
        (нам важно сколько claim-токенов нашлось в документе).
        """
        if not claim_tokens:
            return 1.0

        intersection = claim_tokens & doc_tokens
        return len(intersection) / len(claim_tokens)

from jarvis.generation.services.hallucination_checker_impl import (  # noqa: E402
    ClaimCheck,
    GroundednessResult,
    HallucinationChecker,
)
