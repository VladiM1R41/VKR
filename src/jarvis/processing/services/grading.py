"""Cross-source grading helpers for Layer 2.

Шкала content_grade (по Плэтту, гл. 6):
  1 — подтверждено 2+ независимыми надёжными источниками
  2 — один надёжный источник (A-B)
  3 — один средний источник (C)
  4 — один слабый источник (D-E)
  5 — явное противоречие внутри кластера (разные источники говорят разное)
  6 — недостаточно данных (unknown reliability)
"""

from __future__ import annotations


def derive_content_grade(*, reliability: str, cluster_source_count: int) -> int:
    """Compute content grade per Platt matrix."""

    if cluster_source_count >= 2 and reliability in {"A", "B"}:
        return 1
    if reliability in {"A", "B"}:
        return 2
    if reliability == "C":
        return 3
    if reliability in {"D", "E"}:
        if cluster_source_count >= 2:
            # Несколько слабых источников = противоречие/неоднозначность
            return 5
        return 4
    return 6


def derive_uncertainty(*, reliability: str, cluster_source_count: int) -> bool:
    """Flag weakly supported news as uncertain."""

    return reliability in {"D", "E"} and cluster_source_count <= 1

