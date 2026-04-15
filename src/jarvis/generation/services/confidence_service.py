"""Confidence scoring for Layer 5 grounded generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfidenceEvidence:
    """Evidence summary used to assign a confidence label."""

    n_documents: int
    avg_trust_score: float
    avg_content_grade: float
    has_conflicting_sources: bool = False


class ConfidenceService:
    """Map evidence quality to a system-level confidence label."""

    def compute_label(self, evidence: ConfidenceEvidence) -> str:
        if evidence.n_documents == 0:
            return "LOW"

        if (
            evidence.n_documents >= 3
            and evidence.avg_trust_score >= 0.8
            and evidence.avg_content_grade <= 2
            and not evidence.has_conflicting_sources
        ):
            return "TOP"

        if (
            evidence.n_documents >= 2
            and evidence.avg_trust_score >= 0.6
            and evidence.avg_content_grade <= 3
        ):
            return "HIGH"

        if (
            evidence.n_documents >= 1
            and evidence.avg_trust_score >= 0.4
            and evidence.avg_content_grade <= 4
        ):
            return "MEDIUM"

        return "LOW"


def compute_confidence(
    n_documents: int,
    avg_trust_score: float,
    avg_content_grade: float,
    has_conflicting_sources: bool = False,
) -> str:
    """Backward-compatible helper for direct confidence computation."""

    service = ConfidenceService()
    return service.compute_label(
        ConfidenceEvidence(
            n_documents=n_documents,
            avg_trust_score=avg_trust_score,
            avg_content_grade=avg_content_grade,
            has_conflicting_sources=has_conflicting_sources,
        )
    )
