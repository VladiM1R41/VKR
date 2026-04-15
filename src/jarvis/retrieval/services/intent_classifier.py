"""Rule-based intent classification for Layer 3.

Three intent types (per Platt, ch. 3):
- FACTUAL: "What happened?" — factual answer with sources
- CAPABILITY: "What does this mean?" — analytical with context
- INTENT: "What will happen?" — predictive with alternatives

MVP: rule-based keyword matching (free, fast, covers ~80%).
Future: LLM few-shot classifier for higher accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.core.logging import log_event
import logging


logger = logging.getLogger(__name__)

# Keywords that signal each intent type
_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "INTENT": (
        "прогноз", "будет", "ожидает", "что будет", "ожидание",
        "предсказани", "перспектив", "будущее", "долгосроч",
        "как измен", "как повлияет", "чем грозит",
    ),
    "CAPABILITY": (
        "почему", "что означает", "как понять", "значит", "объясни",
        "смысл", "причин", "последствия", "почему это важно",
        "что это значит", "в чём суть",
    ),
}


@dataclass(frozen=True, slots=True)
class IntentResult:
    """Classification result with confidence."""

    intent: str  # FACTUAL | CAPABILITY | INTENT
    confidence: float  # 0.0-1.0
    method: str  # "rule-based" for now


def classify_intent(query: str) -> IntentResult:
    """Classify user query intent (MVP: rule-based).

    Algorithm:
    1. Check for INTENT keywords (future/predictions)
    2. Check for CAPABILITY keywords (explanation/meaning)
    3. Default to FACTUAL (facts/events)

    Args:
        query: Original user query text.

    Returns:
        IntentResult with intent type, confidence, and method.
    """
    q = query.lower().strip()
    if not q:
        return IntentResult(intent="FACTUAL", confidence=0.5, method="rule-based")

    # Check INTENT keywords
    intent_matches = 0
    max_matches = 0
    for intent_type, keywords in _INTENT_KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in q)
        if matches > max_matches:
            max_matches = matches
            intent_type_best = intent_type
            intent_matches = matches

    if max_matches == 0:
        # No keywords found → FACTUAL (default)
        return IntentResult(intent="FACTUAL", confidence=0.6, method="rule-based")

    # Confidence scales with number of matched keywords
    confidence = min(0.95, 0.6 + intent_matches * 0.15)

    result = IntentResult(
        intent=intent_type_best,
        confidence=round(confidence, 2),
        method="rule-based",
    )

    log_event(
        logger,
        logging.DEBUG,
        "intent_classified",
        query=q[:100],
        intent=result.intent,
        confidence=result.confidence,
        matches=intent_matches,
    )
    return result
