"""Offline evaluation models for Layer 4 personalization."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvaluationScenario(BaseModel):
    """One offline evaluation scenario with expected targets."""

    name: str
    expected_news_ids: list[int] = Field(default_factory=list)
    blocked_news_ids: list[int] = Field(default_factory=list)
    preferred_topic: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)


class EvaluationMetrics(BaseModel):
    """Computed metrics for one ranked list."""

    hit_at_k: float
    reciprocal_rank: float
    blocked_exposure_at_k: float
    topical_coverage_at_k: float
    diversity_score_at_k: float
    seen_suppression_score_at_k: float


class EvaluationComparison(BaseModel):
    """Ablation-style comparison for one scenario."""

    scenario_name: str
    baseline: EvaluationMetrics
    personalized: EvaluationMetrics
    diversified: EvaluationMetrics
    hit_at_k_delta: float
    reciprocal_rank_delta: float
    blocked_exposure_delta: float
    diversity_score_delta: float

