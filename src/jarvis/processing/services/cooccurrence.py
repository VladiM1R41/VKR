"""Entity co-occurrence graph builder for Layer 2.

Когда NER извлёк из одной статьи несколько сущностей,
мы строим рёбра между всеми парами — они «встречались вместе».

Это создаёт граф знаний:
    Путин ──[15 статей]──→ ЦБ ──[8 статей]──→ Набиуллина

Используется Слоем 6 для визуализации графа (/graph)
и Слоем 5 для GraphRAG (поиск связанных сущностей).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import logging

from sqlalchemy import insert, select, update

from jarvis.db.models import EntityCooccurrence


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CooccurrenceEdge:
    """One edge in the co-occurrence graph."""

    entity_a_id: int
    entity_b_id: int
    count: int = 1


def _make_edge(entity_id_a: int, entity_id_b: int) -> CooccurrenceEdge:
    """Создать ребро с invariant a < b.

    Это гарантирует отсутствие дубликатов (A,B) и (B,A).
    CHECK constraint в БД проверяет это же условие.
    """
    if entity_id_a < entity_id_b:
        return CooccurrenceEdge(entity_id_a, entity_id_b)
    return CooccurrenceEdge(entity_id_b, entity_id_a)


def build_cooccurrence_edges(entity_ids: list[int]) -> list[CooccurrenceEdge]:
    """Построить все рёбра между сущностями одной статьи.

    Для N сущностей: N*(N-1)/2 рёбер (полный граф клики).
    Для производительности ограничиваем максимум 10 сущностями
    на статью (типичная статья содержит 3-7 сущностей).

    Args:
        entity_ids: ID сущностей, извлечённых из одной статьи.

    Returns:
        Список рёбер (без дубликатов).
    """
    if len(entity_ids) < 2:
        return []

    # Ограничиваем чтобы не создавать O(N²) для статей с 50+ сущностями
    unique_ids = sorted(set(entity_ids))[:10]

    return [_make_edge(a, b) for a, b in combinations(unique_ids, 2)]


def upsert_cooccurrences(session, edges: list[CooccurrenceEdge]) -> int:
    """Upsert рёбер в entity_cooccurrences.

    Для каждого ребра:
    - если уже существует → co_mention_count += 1
    - если нет → INSERT

    Args:
        session: SQLAlchemy sync session.
        edges: Рёбра для вставки/обновления.

    Returns:
        Число обработанных рёбер.
    """
    if not edges:
        return 0

    count = 0
    for edge in edges:
        # Проверяем существует ли ребро
        existing = session.scalar(
            select(EntityCooccurrence).where(
                EntityCooccurrence.entity_a_id == edge.entity_a_id,
                EntityCooccurrence.entity_b_id == edge.entity_b_id,
            )
        )

        if existing:
            existing.co_mention_count += edge.count
            # SQLAlchemy detect change automatically via attribute set
            from sqlalchemy.orm.attributes import flag_modified
            session.add(existing)
        else:
            session.add(
                EntityCooccurrence(
                    entity_a_id=edge.entity_a_id,
                    entity_b_id=edge.entity_b_id,
                    co_mention_count=edge.count,
                )
            )
        count += 1

    return count
