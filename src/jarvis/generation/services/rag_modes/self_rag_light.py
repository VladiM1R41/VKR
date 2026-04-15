"""Self-RAG light service for Layer 5."""

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
class SelfRAGDecision:
    retrieve_needed: bool
    used_existing_context: bool
    used_retrieval: bool
    relevant_documents: int
    reason: str


@dataclass(frozen=True, slots=True)
class SelfRAGLightResult:
    answer: GenerationAnswerResult
    decision: SelfRAGDecision


class SelfRAGLightService:
    """Lightweight retrieve/no-retrieve and relevance filtering wrapper."""

    def _tokenize(self, text: str) -> set[str]:
        return {token.lower() for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9.-]+", text)}

    def _looks_like_smalltalk(self, query: str) -> bool:
        normalized = " ".join(query.lower().split())
        return normalized in {
            "привет",
            "здравствуй",
            "спасибо",
            "как дела",
            "добрый день",
        }

    def filter_relevant_documents(
        self,
        user_query: str,
        news_items: list[NewsWithContext],
    ) -> list[NewsWithContext]:
        query_tokens = self._tokenize(user_query)
        if not query_tokens:
            return news_items

        relevant: list[NewsWithContext] = []
        for item in news_items:
            doc_tokens = self._tokenize(f"{item.title} {item.content or ''} {' '.join(item.topics)} {' '.join(item.entities)}")
            overlap = len(query_tokens & doc_tokens)
            if overlap > 0:
                relevant.append(item)
        return relevant

    def generate(
        self,
        *,
        answer_service: AnswerGenerationService,
        user_query: str,
        news_items: list[NewsWithContext],
        retrieval_fn: RetrievalFn | None = None,
        user_id: int | None = None,
        intent: str = "FACTUAL",
    ) -> SelfRAGLightResult:
        relevant_items = self.filter_relevant_documents(user_query, news_items)

        retrieve_needed = not relevant_items and not self._looks_like_smalltalk(user_query)
        used_retrieval = False
        reason = "existing_context_relevant"
        selected_items = relevant_items

        if retrieve_needed and retrieval_fn is not None:
            selected_items = retrieval_fn(user_query)
            used_retrieval = True
            reason = "retrieval_triggered_for_missing_relevant_context"
        elif retrieve_needed:
            reason = "retrieval_needed_but_not_available"
        elif self._looks_like_smalltalk(user_query):
            reason = "no_retrieve_smalltalk_like_query"

        answer = answer_service.generate_answer(
            user_query=user_query,
            news_items=selected_items,
            user_id=user_id,
            intent=intent,
            rag_mode_override="self_rag",
        )
        return SelfRAGLightResult(
            answer=answer,
            decision=SelfRAGDecision(
                retrieve_needed=retrieve_needed,
                used_existing_context=bool(relevant_items),
                used_retrieval=used_retrieval,
                relevant_documents=len(relevant_items),
                reason=reason,
            ),
        )
