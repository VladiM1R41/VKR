"""Cross-encoder reranker for Layer 3.

Uses BAAI/bge-reranker-v2-m3 via sentence-transformers CrossEncoder.
- large multilingual cross-encoder; should be used only on a small candidate set
- Supports Russian language
- Apache 2.0 license
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import math
import re

from jarvis.core.logging import log_event
from jarvis.core.settings import get_settings
from jarvis.retrieval.services.qdrant_search import SearchResult


logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SHORT_QUERY_TERMS = {
    "ai",
    "it",
    "ии",
    "мвд",
    "мид",
    "оон",
    "рф",
    "сша",
    "цб",
}
_QUERY_STOP_TERMS = {
    "а",
    "без",
    "бы",
    "в",
    "во",
    "для",
    "до",
    "и",
    "из",
    "или",
    "к",
    "как",
    "на",
    "не",
    "о",
    "об",
    "от",
    "по",
    "при",
    "с",
    "со",
    "что",
    "это",
}


@dataclass
class RerankedResult:
    """One reranked result with both retrieval and rerank scores."""

    result: SearchResult
    rerank_score: float  # [0, 1] from cross-encoder


def _resolve_device(device: str) -> str:
    """Resolve auto/cuda/cpu into a concrete device for CrossEncoder."""
    if device == "auto":
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"
    return device


@lru_cache(maxsize=8)
def _load_reranker(
    model_name: str = "BAAI/bge-reranker-v2-m3",
    device: str = "auto",
    max_length: int = 0,
):
    """Lazy-load BGE reranker via sentence-transformers."""
    try:
        from sentence_transformers import CrossEncoder

        kwargs = {
            "device": _resolve_device(device),
        }
        if max_length > 0:
            kwargs["max_length"] = max_length
        return CrossEncoder(model_name, **kwargs)
    except Exception as exc:
        logger.warning("reranker unavailable: %s", exc)
        return None


def _neutral_results(candidates: list[SearchResult]) -> list[RerankedResult]:
    """Return candidates with neutral rerank scores in retrieval order."""
    return [RerankedResult(result=c, rerank_score=0.5) for c in candidates]


def _is_cuda_oom(exc: Exception) -> bool:
    message = str(exc).lower()
    return "cuda" in message and ("out of memory" in message or "cuda oom" in message)


def _empty_cuda_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


def _normalize_text(text: str) -> str:
    return text.lower().replace("ё", "е")


def _query_terms(query: str) -> set[str]:
    terms = set()
    for token in _TOKEN_RE.findall(_normalize_text(query)):
        if token in _QUERY_STOP_TERMS:
            continue
        if token.isdigit() or len(token) >= 3 or token in _SHORT_QUERY_TERMS:
            terms.add(token)
    return terms


def _split_sentences(text: str) -> list[str]:
    try:
        from razdel import sentenize

        return [
            text[item.start:item.stop].strip()
            for item in sentenize(text)
            if text[item.start:item.stop].strip()
        ]
    except Exception:
        return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _sentence_match_score(sentence: str, query_terms: set[str]) -> int:
    if not query_terms:
        return 0
    normalized = _normalize_text(sentence)
    return sum(1 for term in query_terms if term in normalized)


def _select_best_passage(query: str, text: str, max_chars: int) -> str:
    if not text or max_chars <= 0:
        return text

    query_terms = _query_terms(query)
    if not query_terms:
        return text[:max_chars]

    sentences = _split_sentences(text)
    if not sentences:
        return text[:max_chars]

    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (_sentence_match_score(item[1], query_terms), -item[0]),
        reverse=True,
    )
    selected: list[str] = []
    used: set[int] = set()
    budget = max_chars
    for idx, sentence in ranked:
        if idx in used or _sentence_match_score(sentence, query_terms) <= 0:
            continue
        candidate = sentence[:budget]
        if candidate:
            selected.append(candidate)
            used.add(idx)
            budget -= len(candidate) + 1
        if budget <= 80 or len(selected) >= 3:
            break

    passage = " ".join(selected).strip()
    return passage[:max_chars] if passage else text[:max_chars]


def _build_rerank_document(
    query: str,
    candidate: SearchResult,
    max_doc_chars: int,
    passage_mode: str = "best",
) -> str:
    """Build a compact text for cross-encoder scoring."""
    if passage_mode == "prefix":
        parts = [candidate.title, candidate.snippet_lead, candidate.text]
        text = "\n".join(part.strip() for part in parts if part and part.strip())
        if not text:
            text = candidate.title
        if max_doc_chars > 0 and len(text) > max_doc_chars:
            return text[:max_doc_chars]
        return text

    fixed_parts = [candidate.title, candidate.snippet_lead]
    fixed_text = "\n".join(part.strip() for part in fixed_parts if part and part.strip())
    body_budget = max_doc_chars
    if max_doc_chars > 0:
        body_budget = max(0, max_doc_chars - len(fixed_text) - 2)

    body = _select_best_passage(query, candidate.text, body_budget) if body_budget else ""
    parts = [candidate.title, candidate.snippet_lead, body]
    text = "\n".join(part.strip() for part in parts if part and part.strip())
    if not text:
        text = candidate.title
    if max_doc_chars > 0 and len(text) > max_doc_chars:
        return text[:max_doc_chars]
    return text


class RerankingService:
    """Cross-encoder reranking service."""

    def rerank(
        self,
        query: str,
        candidates: list[SearchResult],
    ) -> list[RerankedResult]:
        """Rerank candidates using cross-encoder.

        Args:
            query: Original user query.
            candidates: Top-K results from retrieval (typically 30-50).

        Returns:
            Reranked results sorted by descending rerank_score.
            If reranker unavailable, returns candidates with score 0.5.
        """
        if not candidates:
            return []

        settings = get_settings()
        if not settings.reranker_enabled:
            return _neutral_results(candidates)

        model = _load_reranker(
            settings.reranker_model,
            settings.reranker_device,
            settings.reranker_max_length,
        )
        if model is None:
            return _neutral_results(candidates)

        pairs = [
            [
                query,
                _build_rerank_document(
                    query,
                    candidate,
                    settings.reranker_max_doc_chars,
                    settings.reranker_passage_mode,
                ),
            ]
            for candidate in candidates
        ]

        predict_kwargs = {"show_progress_bar": False}
        if settings.reranker_batch_size > 0:
            predict_kwargs["batch_size"] = settings.reranker_batch_size
        try:
            scores = model.predict(pairs, **predict_kwargs)
        except Exception as exc:
            if _is_cuda_oom(exc):
                _empty_cuda_cache()
                log_event(
                    logger,
                    logging.WARNING,
                    "reranking_cuda_oom_fallback",
                    candidates_count=len(candidates),
                    error=str(exc)[:500],
                )
                return _neutral_results(candidates)
            log_event(
                logger,
                logging.WARNING,
                "reranking_failed_fallback",
                candidates_count=len(candidates),
                error=str(exc)[:500],
            )
            return _neutral_results(candidates)

        results = []
        for candidate, score in zip(candidates, scores, strict=True):
            # CrossEncoder возвращает logits → нормализуем через sigmoid
            normalized_score = float(1 / (1 + math.exp(-score)))
            results.append(
                RerankedResult(
                    result=candidate,
                    rerank_score=round(normalized_score, 4),
                )
            )

        # Sort by rerank_score descending
        results.sort(key=lambda r: r.rerank_score, reverse=True)

        log_event(
            logger,
            logging.INFO,
            "reranking_completed",
            candidates_count=len(candidates),
            top_score=results[0].rerank_score if results else 0,
            bottom_score=results[-1].rerank_score if results else 0,
        )
        return results
