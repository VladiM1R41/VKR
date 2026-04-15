"""CRAG service for Layer 5."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from jarvis.generation.services.answer_generation_service import (
    AnswerGenerationService,
    GenerationAnswerResult,
)
from jarvis.generation.services.context_assembler import NewsWithContext


RetrievalFn = Callable[[str], list[NewsWithContext]]


@dataclass(frozen=True, slots=True)
class CRAGDecision:
    initial_quality_score: float
    retry_quality_score: float | None
    should_retry: bool
    used_retry: bool
    refined_query: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class CRAGResult:
    answer: GenerationAnswerResult
    decision: CRAGDecision


class CRAGService:
    """Context-aware retry wrapper around Standard RAG."""

    def evaluate_context_quality(self, news_items: list[NewsWithContext]) -> float:
        if not news_items:
            return 0.0
        avg_trust = sum(item.trust_score for item in news_items) / len(news_items)
        avg_grade = sum(item.content_grade for item in news_items) / len(news_items)
        grade_score = max(0.0, 1.0 - ((avg_grade - 1.0) / 5.0))
        source_diversity = len({item.source_name for item in news_items}) / max(1, len(news_items))
        document_support = min(1.0, len(news_items) / 3.0)
        return round(
            0.40 * avg_trust + 0.25 * grade_score + 0.20 * source_diversity + 0.15 * document_support,
            4,
        )

    def refine_query(self, user_query: str) -> str:
        tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9.-]+", user_query.lower())
        stop_words = {
            "что", "это", "как", "какой", "какая", "какие", "ли", "почему", "когда",
            "где", "кто", "расскажи", "объясни", "покажи", "про", "по", "о", "об",
        }
        refined = [token for token in tokens if token not in stop_words]
        return " ".join(refined) or user_query.strip()

    def generate(
        self,
        *,
        answer_service: AnswerGenerationService,
        user_query: str,
        news_items: list[NewsWithContext],
        retrieval_fn: RetrievalFn | None = None,
        user_id: int | None = None,
        intent: str = "FACTUAL",
    ) -> CRAGResult:
        initial_quality = self.evaluate_context_quality(news_items)
        should_retry = initial_quality < 0.62 and retrieval_fn is not None
        refined_query = self.refine_query(user_query) if should_retry else None

        selected_items = news_items
        retry_quality: float | None = None
        used_retry = False
        reason = "initial_context_good_enough"

        if should_retry and refined_query:
            retried_items = retrieval_fn(refined_query)
            retry_quality = self.evaluate_context_quality(retried_items)
            if retry_quality > initial_quality and retried_items:
                selected_items = retried_items
                used_retry = True
                reason = "retry_improved_context"
            else:
                reason = "retry_did_not_improve_context"

        answer = answer_service.generate_answer(
            user_query=user_query,
            news_items=selected_items,
            user_id=user_id,
            intent=intent,
            rag_mode_override="crag",
        )
        return CRAGResult(
            answer=answer,
            decision=CRAGDecision(
                initial_quality_score=initial_quality,
                retry_quality_score=retry_quality,
                should_retry=should_retry,
                used_retry=used_retry,
                refined_query=refined_query,
                reason=reason,
            ),
        )
