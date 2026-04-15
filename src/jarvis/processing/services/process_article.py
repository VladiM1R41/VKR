"""Core article processing flow for Layer 2.

Три параллельные ветки обработки (по FINAL_LAYER_2_GUIDE.md):
  Ветка 1 (IR):     лемматизация → lemma_text для Qdrant FTS
  Ветка 2 (NLP):   NER + topics + keywords
  Ветка 3 (Embed): чанкинг → BGE-M3 embeddings → Qdrant upsert
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from math import exp, log
from uuid import uuid4

from sqlalchemy import delete, func, select

from jarvis.core.logging import log_event
from jarvis.db.models import Chunk, Entity, EntityCooccurrence, News, NewsEntity, NewsTopic, Source, Topic
from jarvis.db.session import SyncSessionLocal
from jarvis.processing.ir.lemmatize import lemmatize_text
from jarvis.processing.services.chunking import build_chunks
from jarvis.processing.services.embedding_runtime import encode_texts
from jarvis.processing.services.entity_extraction import ExtractedEntity, extract_entities
from jarvis.processing.services.grading import derive_content_grade, derive_uncertainty
from jarvis.processing.services.qdrant_index import IndexedChunk, QdrantIndexer
from jarvis.processing.services.topic_mapping import TopicMatch, resolve_topics
from jarvis.processing.services.cooccurrence import build_cooccurrence_edges, upsert_cooccurrences
from jarvis.processing.services.event_clustering import resolve_event_cluster_id
from jarvis.processing.nlp.keywords import extract_keywords


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessArticleResult:
    """Outcome of one article processing run."""

    news_id: int
    status: str
    chunk_count: int
    topic_count: int
    entity_count: int
    cooccurrence_edges: int


def _extract_source_categories(news: News) -> list[str]:
    raw_categories = (news.extra or {}).get("categories")
    if not isinstance(raw_categories, list):
        return []
    return [str(value) for value in raw_categories if isinstance(value, str) and value.strip()]


def _resolve_cluster_source_count(session, news: News) -> int:
    cluster_id = news.event_cluster_id or news.id
    stmt = select(func.count(func.distinct(News.source_id))).where(News.event_cluster_id == cluster_id)
    cluster_source_count = session.scalar(stmt)
    if cluster_source_count:
        return int(cluster_source_count)

    fallback_stmt = select(func.count(func.distinct(News.source_id))).where(News.id == news.id)
    fallback_count = session.scalar(fallback_stmt) or 1
    return int(fallback_count)


def _ensure_topics(session, topic_matches: list[TopicMatch]) -> dict[str, Topic]:
    if not topic_matches:
        return {}

    names = [match.name for match in topic_matches]
    existing = {
        topic.name: topic
        for topic in session.scalars(select(Topic).where(Topic.name.in_(names))).all()
    }

    for name in names:
        if name in existing:
            continue
        topic = Topic(name=name)
        session.add(topic)
        session.flush()
        existing[name] = topic

    return existing


def _build_chunk_payload(
    news: News,
    chunk,
    topic_names: list[str],
    *,
    source_name: str,
    trust_score: float,
    keyword_texts: list[str],
    entity_names: list[str],
    entity_ids: list[int],
) -> dict[str, object]:
    """Полный payload чанка для Qdrant (по FINAL_LAYER_2_GUIDE.md раздел 13.8)."""
    return {
        "news_id": news.id,
        "source_id": news.source_id,
        "source_name": source_name,
        "title": news.title,
        "text": chunk.text,
        "published_at": news.published_at.isoformat() if news.published_at else None,
        "url": news.canonical_url,
        "zone": chunk.zone,
        "chunk_index": chunk.chunk_index,
        "total_chunks": chunk.total_chunks,
        "language": news.language,
        "information_type": news.information_type,
        "urgency": news.urgency,
        "trust_score": trust_score,
        "content_grade": news.content_grade,
        "event_cluster_id": news.event_cluster_id or news.id,
        "entities": entity_names,
        "entity_ids": entity_ids,
        "topics": topic_names,
        "keywords": keyword_texts,
        "snippet_lead": news.snippet_lead or "",
        "lemma_text": chunk.lemma_text or chunk.text.lower(),
        "text_content": chunk.lemma_text or chunk.text,
        "embedding_model": "bge-m3",
        "chunking_version": "adaptive-v1",
        "nlp_enriched": True,
    }


def _build_entity_text(news: News) -> str:
    return "\n".join(
        part.strip()
        for part in [news.title, news.content or "", news.snippet_lead or ""]
        if part and part.strip()
    )


def _load_existing_entity_mentions(session, news_id: int) -> list[tuple[int, int]]:
    return list(
        session.execute(
            select(NewsEntity.entity_id, NewsEntity.mention_count).where(NewsEntity.news_id == news_id)
        ).all()
    )


def _apply_entity_mentions(session, news_id: int, extracted_entities: list[ExtractedEntity]) -> int:
    existing_mentions = _load_existing_entity_mentions(session, news_id)
    if existing_mentions:
        for entity_id, mention_count in existing_mentions:
            entity = session.get(Entity, entity_id)
            if entity is None:
                continue
            entity.mention_count = max(0, int(entity.mention_count) - int(mention_count))
        session.execute(delete(NewsEntity).where(NewsEntity.news_id == news_id))

    if not extracted_entities:
        return 0

    applied_count = 0
    for extracted in extracted_entities:
        entity = session.scalar(
            select(Entity).where(
                Entity.type == extracted.entity_type,
                Entity.normalized_name == extracted.normalized_name,
            )
        )
        if entity is None:
            entity = Entity(
                name=extracted.name,
                type=extracted.entity_type,
                normalized_name=extracted.normalized_name,
                mention_count=0,
            )
            session.add(entity)
            session.flush()

        entity.name = extracted.name
        entity.mention_count = int(entity.mention_count) + extracted.mention_count
        session.add(
            NewsEntity(
                news_id=news_id,
                entity_id=entity.id,
                mention_count=extracted.mention_count,
            )
        )
        applied_count += 1

    return applied_count


def process_one_news_article(news_id: int, *, qdrant_indexer: QdrantIndexer | None = None) -> ProcessArticleResult:
    """Process one article into topics, chunks and retrieval artifacts."""

    indexer = qdrant_indexer or QdrantIndexer()

    with SyncSessionLocal() as session:
        news = session.get(News, news_id)
        if news is None:
            return ProcessArticleResult(news_id=news_id, status="not_found", chunk_count=0, topic_count=0, entity_count=0, cooccurrence_edges=0)
        if news.processed:
            return ProcessArticleResult(news_id=news_id, status="already_processed", chunk_count=0, topic_count=0, entity_count=0, cooccurrence_edges=0)

        source = session.get(Source, news.source_id)
        reliability = source.reliability if source is not None else "C"
        trust_score = source.trust_score if source is not None else 0.5
        source_name = source.name if source is not None else "Unknown"
        cluster_source_count = _resolve_cluster_source_count(session, news)

        # === Ветка 2: NLP-обогащение ===
        entity_text = _build_entity_text(news)
        extracted_entities = extract_entities(entity_text)

        # Topics: rule-based → zero-shot fallback
        topic_matches = resolve_topics(
            source_categories=_extract_source_categories(news),
            title=news.title,
            body=news.content or "",
        )

        # Keywords: YAKE
        keyword_results = extract_keywords(entity_text)
        keyword_texts = [kw.text for kw in keyword_results]

        # === Event clustering ===
        # Определяем реальный event_cluster_id поверх tentative
        resolved_cluster_id = resolve_event_cluster_id(news)
        if resolved_cluster_id != (news.event_cluster_id or news.id):
            news.event_cluster_id = resolved_cluster_id
            log_event(
                logger,
                logging.INFO,
                "event_cluster_resolved",
                news_id=news.id,
                old_cluster_id=news.event_cluster_id,
                new_cluster_id=resolved_cluster_id,
            )
            # Пересчитаем cluster_source_count с новым cluster_id
            cluster_source_count = _resolve_cluster_source_count(session, news)

        # === Ветка 1: IR-лемматизация ===
        # Лемматизируем title и body для Qdrant full-text payload
        lemma_title = lemmatize_text(news.title)

        # Degraded-path: если content пуст, используем snippet_lead
        has_full_content = bool((news.content or "").strip())
        if has_full_content:
            lemma_body = lemmatize_text(news.content)
            entity_text_for_keywords = entity_text
        else:
            # Degraded: content отсутствует, используем snippet_lead
            lemma_body = lemmatize_text(news.snippet_lead or "")
            entity_text_for_keywords = "\n".join(
                part.strip()
                for part in [news.title, news.snippet_lead or ""]
                if part and part.strip()
            )
            # Перезапускаем keywords на доступном тексте
            keyword_results = extract_keywords(entity_text_for_keywords)
            keyword_texts = [kw.text for kw in keyword_results]

        # === Ветка 3: Чанкинг + Embeddings ===
        prepared_chunks = build_chunks(
            title=news.title,
            body=news.content,
            fallback_body=news.snippet_lead,
            lemma_title=lemma_title,
            lemma_body=lemma_body,
        )
        if not prepared_chunks:
            prepared_chunks = build_chunks(
                title=news.title,
                body=None,
                fallback_body=None,
                lemma_title=lemma_title,
                lemma_body="",
            )

        encoded_chunks = encode_texts(
            [chunk.text for chunk in prepared_chunks],
            sparse_texts=[chunk.lemma_text or chunk.text for chunk in prepared_chunks],
        )
        if len(encoded_chunks) != len(prepared_chunks):
            raise RuntimeError("Embedding runtime returned an unexpected number of vectors.")

        representative_vector = next(
            (
                embedding.dense_vector
                for chunk, embedding in zip(prepared_chunks, encoded_chunks, strict=True)
                if chunk.zone == "body"
            ),
            encoded_chunks[0].dense_vector if encoded_chunks else None,
        )
        resolved_cluster_id = resolve_event_cluster_id(
            news,
            current_dense_vector=representative_vector,
        )
        old_cluster_id = news.event_cluster_id or news.id
        if resolved_cluster_id != old_cluster_id:
            news.event_cluster_id = resolved_cluster_id
            log_event(
                logger,
                logging.INFO,
                "event_cluster_resolved",
                news_id=news.id,
                old_cluster_id=old_cluster_id,
                new_cluster_id=resolved_cluster_id,
            )
            cluster_source_count = _resolve_cluster_source_count(session, news)

        existing_point_ids = [
            str(point_id)
            for point_id in session.scalars(select(Chunk.qdrant_point_id).where(Chunk.news_id == news.id)).all()
        ]

        topic_names = [match.name for match in topic_matches]
        indexed_chunks: list[IndexedChunk] = []
        chunk_rows: list[Chunk] = []

        # Собираем entity names/ids для payload (после _apply_entity_mentions)
        # entity_ids_pre пустой — реальные id получаем только после flush entities в БД.
        # После commit вызываем indexer.update_entity_payload() вторым проходом.
        entity_names_pre = [e.name for e in extracted_entities]
        entity_ids_pre: list[int] = []  # заполним после insert

        # Инициализация — будут перезаписаны внутри try-блока после flush
        entity_ids_post: list[int] = []
        entity_names_post: list[str] = entity_names_pre

        for prepared_chunk, embedding_output in zip(prepared_chunks, encoded_chunks, strict=True):
            point_uuid = uuid4()
            point_id = str(point_uuid)
            # MVP payload: entity_names пока из extracted, entity_ids обновим позже
            payload = _build_chunk_payload(
                news,
                prepared_chunk,
                topic_names,
                source_name=source_name,
                trust_score=trust_score,
                keyword_texts=keyword_texts,
                entity_names=entity_names_pre,
                entity_ids=entity_ids_pre,
            )
            indexed_chunks.append(
                IndexedChunk(
                    point_id=point_id,
                    dense_vector=embedding_output.dense_vector,
                    sparse_indices=embedding_output.sparse_indices,
                    sparse_values=embedding_output.sparse_values,
                    payload=payload,
                )
            )
            chunk_rows.append(
                Chunk(
                    news_id=news.id,
                    qdrant_point_id=point_uuid,
                    chunk_index=prepared_chunk.chunk_index,
                    zone=prepared_chunk.zone,
                    char_start=prepared_chunk.char_start,
                    char_end=prepared_chunk.char_end,
                    token_count=prepared_chunk.token_count,
                )
            )

        indexer.ensure_collection()
        indexer.upsert_chunks(indexed_chunks)

        new_point_ids = [chunk.point_id for chunk in indexed_chunks]
        try:
            session.execute(delete(NewsTopic).where(NewsTopic.news_id == news.id))
            session.execute(delete(Chunk).where(Chunk.news_id == news.id))

            topics_by_name = _ensure_topics(session, topic_matches)
            for match in topic_matches:
                session.add(
                    NewsTopic(
                        news_id=news.id,
                        topic_id=topics_by_name[match.name].id,
                        confidence=match.confidence,
                    )
                )

            session.add_all(chunk_rows)
            entity_count = _apply_entity_mentions(session, news.id, extracted_entities)

            # Получаем реальные entity_ids после upsert (перезаписываем внешние переменные)
            entity_ids_post = list(
                session.scalars(
                    select(NewsEntity.entity_id).where(NewsEntity.news_id == news.id)
                ).all()
            )
            entity_names_post = [
                e.name for e in session.scalars(
                    select(Entity).where(Entity.id.in_(entity_ids_post))
                ).all()
            ] if entity_ids_post else entity_names_pre

            # === Граф знаний: co-occurrence рёбра ===
            # Собираем ID всех сущностей этой статьи и строим рёбра
            entity_ids = list(
                session.scalars(
                    select(NewsEntity.entity_id).where(NewsEntity.news_id == news.id)
                ).all()
            )
            coocc_edges = build_cooccurrence_edges(entity_ids)
            coocc_count = upsert_cooccurrences(session, coocc_edges)

            news.content_grade = derive_content_grade(
                reliability=reliability,
                cluster_source_count=cluster_source_count,
            )
            news.is_uncertain = derive_uncertainty(
                reliability=reliability,
                cluster_source_count=cluster_source_count,
            )
            # value_score: полезность статьи для retrieval (раздел 16.2)
            # formula: source_trust × freshness × completeness × cluster_support
            freshness = 1.0
            if news.published_at:
                age_hours = (datetime.now(timezone.utc) - news.published_at).total_seconds() / 3600
                # Экспоненциальное затухание: half-life = 24h для daily, 1h для breaking
                half_life = 1.0 if news.information_type == "breaking" else 24.0
                freshness = exp(-log(2) * age_hours / half_life)

            completeness = 1.0 if has_full_content else 0.3
            cluster_support = min(1.0, cluster_source_count / 3.0)  # нормализация

            value_score = round(trust_score * freshness * completeness * cluster_support, 4)

            news.processed = True
            extra = dict(news.extra or {})
            extra["processing"] = {
                "status": "processed",
                "chunk_count": len(chunk_rows),
                "topic_names": topic_names,
                "topic_method": "rule-based" if any(m.confidence >= 0.9 for m in topic_matches) else "zero-shot",
                "keywords": keyword_texts,
                "entity_count": entity_count,
                "cooccurrence_edges": coocc_count,
                "cluster_source_count": cluster_source_count,
                "value_score": value_score,
                "freshness": round(freshness, 4),
                "completeness": completeness,
                "cluster_support": round(cluster_support, 4),
                "fallback_body_used": not has_full_content and bool((news.snippet_lead or "").strip()),
            }
            news.extra = extra

            session.commit()
        except Exception:
            session.rollback()
            if new_point_ids:
                indexer.delete_points(new_point_ids)
            raise

        # Второй проход: обновляем entity payload в Qdrant реальными id из БД.
        # set_payload меняет только указанные поля без повторной передачи векторов.
        if new_point_ids and entity_ids_post:
            try:
                indexer.update_entity_payload(new_point_ids, entity_names_post, entity_ids_post)
            except Exception:
                log_event(
                    logger,
                    logging.WARNING,
                    "processing_entity_payload_update_failed",
                    news_id=news.id,
                    point_count=len(new_point_ids),
                )

        if existing_point_ids:
            try:
                indexer.delete_points(existing_point_ids)
            except Exception:
                log_event(
                    logger,
                    logging.WARNING,
                    "processing_stale_points_cleanup_failed",
                    news_id=news.id,
                    stale_point_count=len(existing_point_ids),
                )

        log_event(
            logger,
            logging.INFO,
            "processing_article_completed",
            news_id=news.id,
            chunk_count=len(chunk_rows),
            topic_count=len(topic_matches),
            entity_count=entity_count,
            cooccurrence_edges=coocc_count,
            content_grade=news.content_grade,
            is_uncertain=news.is_uncertain,
        )
        return ProcessArticleResult(
            news_id=news.id,
            status="processed",
            chunk_count=len(chunk_rows),
            topic_count=len(topic_matches),
            entity_count=entity_count,
            cooccurrence_edges=coocc_count,
        )
