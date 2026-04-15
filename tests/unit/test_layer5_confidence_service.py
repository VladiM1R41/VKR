from __future__ import annotations

from jarvis.generation.services.confidence_service import (
    ConfidenceEvidence,
    ConfidenceService,
    compute_confidence,
)


def test_confidence_service_top() -> None:
    service = ConfidenceService()
    label = service.compute_label(
        ConfidenceEvidence(
            n_documents=3,
            avg_trust_score=0.85,
            avg_content_grade=2.0,
            has_conflicting_sources=False,
        )
    )
    assert label == "TOP"


def test_compute_confidence_helper_medium() -> None:
    assert compute_confidence(
        n_documents=1,
        avg_trust_score=0.5,
        avg_content_grade=4.0,
    ) == "MEDIUM"

