"""Cross-source grading helpers for Layer 2."""

from __future__ import annotations


def derive_content_grade(
    *,
    reliability: str,
    cluster_source_count: int,
    has_contradiction: bool = False,
) -> int:
    """Compute content grade per Platt-style matrix.

    Grade 5 is reserved for an explicit contradiction/disputed signal. Multiple weak
    sources without a contradiction stay grade 4 instead of being mislabeled as disputed.
    """

    if has_contradiction:
        return 5
    if cluster_source_count >= 2 and reliability in {"A", "B"}:
        return 1
    if reliability in {"A", "B"}:
        return 2
    if reliability == "C":
        return 3
    if reliability in {"D", "E"}:
        return 4
    return 6


def derive_uncertainty(*, reliability: str, cluster_source_count: int) -> bool:
    """Flag weakly supported news as uncertain."""

    return reliability in {"D", "E"} and cluster_source_count <= 1
