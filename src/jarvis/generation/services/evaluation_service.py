"""Offline evaluation and ablation helpers for Layer 5."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.generation.services.answer_generation_service import GenerationAnswerResult


@dataclass(frozen=True, slots=True)
class GenerationEvaluationScenario:
    mode_name: str
    result: GenerationAnswerResult


@dataclass(frozen=True, slots=True)
class GenerationEvaluationSummary:
    mode_name: str
    citation_valid: bool
    groundedness_score: float
    confidence: str | None
    latency_ms: int
    documents_used_count: int


@dataclass(frozen=True, slots=True)
class AblationComparison:
    baseline_mode: str
    candidate_mode: str
    groundedness_delta: float
    latency_delta_ms: int
    citation_gain: int


class GenerationEvaluationService:
    """Summarise and compare Layer 5 generation modes."""

    def summarize(self, scenario: GenerationEvaluationScenario) -> GenerationEvaluationSummary:
        result = scenario.result
        return GenerationEvaluationSummary(
            mode_name=scenario.mode_name,
            citation_valid=result.citation_valid,
            groundedness_score=result.groundedness_score,
            confidence=result.confidence,
            latency_ms=result.latency_ms,
            documents_used_count=result.documents_used_count,
        )

    def compare(
        self,
        baseline: GenerationEvaluationScenario,
        candidate: GenerationEvaluationScenario,
    ) -> AblationComparison:
        base = self.summarize(baseline)
        cand = self.summarize(candidate)
        return AblationComparison(
            baseline_mode=base.mode_name,
            candidate_mode=cand.mode_name,
            groundedness_delta=round(cand.groundedness_score - base.groundedness_score, 4),
            latency_delta_ms=int(cand.latency_ms - base.latency_ms),
            citation_gain=int(cand.citation_valid) - int(base.citation_valid),
        )
