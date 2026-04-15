"""GraphRAG light service for Layer 5."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from jarvis.db.models import Entity, EntityCooccurrence, News, NewsEntity, Source
from jarvis.generation.services.answer_generation_service import (
    AnswerGenerationService,
    GenerationAnswerResult,
)
from jarvis.generation.services.context_assembler import NewsWithContext


@dataclass(frozen=True, slots=True)
class GraphExpansion:
    seed_entities: list[str]
    related_entities: list[str]
    added_news_ids: list[int]


@dataclass(frozen=True, slots=True)
class GraphRAGLightResult:
    answer: GenerationAnswerResult
    expansion: GraphExpansion


class GraphRAGLightService:
    """Light graph expansion over Layer 2 entity graph."""

    def extract_query_entities(self, session: Session, query: str, limit: int = 3) -> list[Entity]:
        lowered = query.lower()
        rows = session.scalars(select(Entity)).all()
        matches = [
            entity for entity in rows
            if entity.name.lower() in lowered or entity.normalized_name.lower() in lowered
        ]
        matches.sort(key=lambda item: int(item.mention_count or 0), reverse=True)
        return matches[:limit]

    def load_related_entities(
        self,
        session: Session,
        seed_entity_ids: list[int],
        limit: int = 5,
    ) -> list[Entity]:
        if not seed_entity_ids:
            return []
        rows = session.scalars(
            select(EntityCooccurrence).where(
                or_(
                    EntityCooccurrence.entity_a_id.in_(seed_entity_ids),
                    EntityCooccurrence.entity_b_id.in_(seed_entity_ids),
                )
            )
        ).all()
        scored: list[tuple[int, int]] = []
        seed_set = set(seed_entity_ids)
        for edge in rows:
            other_id = edge.entity_b_id if edge.entity_a_id in seed_set else edge.entity_a_id
            if other_id in seed_set:
                continue
            scored.append((int(other_id), int(edge.co_mention_count or 0)))
        scored.sort(key=lambda item: item[1], reverse=True)
        related_ids = [entity_id for entity_id, _ in scored[:limit]]
        if not related_ids:
            return []
        entities = session.scalars(select(Entity).where(Entity.id.in_(related_ids))).all()
        entity_map = {int(entity.id): entity for entity in entities}
        return [entity_map[entity_id] for entity_id in related_ids if entity_id in entity_map]

    def load_related_news_context(
        self,
        session: Session,
        entity_ids: list[int],
        exclude_news_ids: set[int],
        limit: int = 5,
    ) -> list[NewsWithContext]:
        if not entity_ids:
            return []
        news_ids = session.scalars(
            select(NewsEntity.news_id).where(NewsEntity.entity_id.in_(entity_ids))
        ).all()
        unique_ids = [int(news_id) for news_id in news_ids if int(news_id) not in exclude_news_ids]
        unique_ids = unique_ids[:limit]
        if not unique_ids:
            return []

        news_rows = session.scalars(select(News).where(News.id.in_(unique_ids))).all()
        news_map = {int(news.id): news for news in news_rows}
        source_ids = {int(news.source_id) for news in news_rows}
        sources = session.scalars(select(Source).where(Source.id.in_(source_ids))).all()
        source_map = {int(source.id): str(source.name) for source in sources}

        result: list[NewsWithContext] = []
        for news_id in unique_ids:
            news = news_map.get(news_id)
            if news is None:
                continue
            result.append(
                NewsWithContext(
                    news_id=int(news.id),
                    source_id=int(news.source_id),
                    source_name=source_map.get(int(news.source_id), "Unknown"),
                    title=str(news.title),
                    content=str(news.content or ""),
                    snippet_lead=str(news.snippet_lead or ""),
                    score=0.4,
                    rerank_score=0.4,
                    personalized_score=0.4,
                    topics=[],
                    entities=[],
                    published_at_str=str(news.published_at or ""),
                    trust_score=float((news.extra or {}).get("trust_score", 0.5)),
                    content_grade=int(news.content_grade or 6),
                    information_type=str((news.extra or {}).get("information_type", "daily")),
                    urgency=str((news.extra or {}).get("urgency", "normal")),
                    event_cluster_id=getattr(news, "event_cluster_id", None),
                )
            )
        return result

    @staticmethod
    def merge_unique_news_items(
        base_items: list[NewsWithContext],
        extra_items: list[NewsWithContext],
        limit: int = 10,
    ) -> list[NewsWithContext]:
        seen: set[int] = set()
        merged: list[NewsWithContext] = []
        for item in [*base_items, *extra_items]:
            if item.news_id in seen:
                continue
            merged.append(item)
            seen.add(item.news_id)
            if len(merged) >= limit:
                break
        return merged

    def generate(
        self,
        *,
        session: Session,
        answer_service: AnswerGenerationService,
        user_query: str,
        news_items: list[NewsWithContext],
        user_id: int | None = None,
        intent: str = "FACTUAL",
        limit: int = 10,
    ) -> GraphRAGLightResult:
        seed_entities = self.extract_query_entities(session, user_query)
        related_entities = self.load_related_entities(
            session,
            [int(entity.id) for entity in seed_entities],
        )
        extra_items = self.load_related_news_context(
            session,
            [int(entity.id) for entity in related_entities],
            exclude_news_ids={item.news_id for item in news_items},
            limit=max(0, limit - len(news_items)),
        )
        merged_items = self.merge_unique_news_items(news_items, extra_items, limit=limit)

        answer = answer_service.generate_answer(
            user_query=user_query,
            news_items=merged_items,
            user_id=user_id,
            intent=intent,
            rag_mode_override="graph_rag",
        )
        return GraphRAGLightResult(
            answer=answer,
            expansion=GraphExpansion(
                seed_entities=[entity.name for entity in seed_entities],
                related_entities=[entity.name for entity in related_entities],
                added_news_ids=[item.news_id for item in extra_items],
            ),
        )
