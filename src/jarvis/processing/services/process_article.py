"""Core article processing flow for Layer 2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from math import exp, log
import time
from uuid import UUID, uuid5

from sqlalchemy import delete, func, select

from jarvis.core.logging import log_event
from jarvis.db.models import Chunk, Entity, News, NewsEntity, NewsTopic, Source, Topic
from jarvis.db.session import SyncSessionLocal
from jarvis.processing.ir.lemmatize import lemmatize_text
from jarvis.processing.nlp.keywords import extract_keywords
from jarvis.processing.services.chunking import build_chunks
from jarvis.processing.services.cooccurrence import (
    build_cooccurrence_edges,
    decrement_cooccurrences,
    upsert_cooccurrences,
)
from jarvis.processing.services.embedding_runtime import encode_texts
from jarvis.processing.services.entity_extraction import ExtractedEntity, extract_entities
from jarvis.processing.services.event_clustering import resolve_event_cluster_id
from jarvis.processing.services.grading import derive_content_grade, derive_uncertainty
from jarvis.processing.services.qdrant_index import IndexedChunk, QdrantIndexer
from jarvis.processing.services.topic_mapping import TopicMatch, resolve_topics


logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "bge-m3"
CHUNKING_VERSION = "adaptive-v1"
POINT_ID_NAMESPACE = UUID("4c55f341-0db8-4e71-8c2d-d82bb8e522b5")


@dataclass(frozen=True, slots=True)
class ProcessArticleResult:
    """Outcome of one article processing run."""

    news_id: int
    status: str
    chunk_count: int
    topic_count: int
    entity_count: int
    cooccurrence_edges: int


def _deterministic_point_uuid(news_id: int, zone: str, chunk_index: int) -> UUID:
    """Stable Qdrant point id for idempotent reprocessing."""

    key = f"{news_id}|{zone}|{chunk_index}|{EMBEDDING_MODEL}|{CHUNKING_VERSION}"
    return uuid5(POINT_ID_NAMESPACE, key)


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


def _resolve_cluster_article_count(session, cluster_id: int) -> int:
    return int(
        session.scalar(select(func.count(News.id)).where(News.event_cluster_id == cluster_id))
        or 0
    )


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
    value_score: float,
    freshness: float,
    completeness: float,
    cluster_support: float,
    nlp_enriched: bool,
) -> dict[str, object]:
    """Full Qdrant payload for one chunk."""

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
        "is_uncertain": bool(news.is_uncertain),
        "value_score": value_score,
        "freshness": freshness,
        "completeness": completeness,
        "cluster_support": cluster_support,
        "event_cluster_id": news.event_cluster_id or news.id,
        "entities": entity_names,
        "entity_ids": entity_ids,
        "topics": topic_names,
        "keywords": keyword_texts,
        "snippet_lead": news.snippet_lead or "",
        "lemma_text": chunk.lemma_text or chunk.text.lower(),
        "text_content": chunk.lemma_text or chunk.text,
        "embedding_model": EMBEDDING_MODEL,
        "chunking_version": CHUNKING_VERSION,
        "nlp_enriched": nlp_enriched,
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


def _load_existing_entity_ids(session, news_id: int) -> list[int]:
    return list(session.scalars(select(NewsEntity.entity_id).where(NewsEntity.news_id == news_id)).all())


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


def _value_metrics(
    *,
    news: News,
    trust_score: float,
    has_full_content: bool,
    cluster_source_count: int,
) -> tuple[float, float, float, float]:
    freshness = 1.0
    if news.published_at:
        age_hours = (datetime.now(timezone.utc) - news.published_at).total_seconds() / 3600
        half_life = 1.0 if news.information_type == "breaking" else 24.0
        freshness = exp(-log(2) * age_hours / half_life)

    completeness = 1.0 if has_full_content else 0.3
    cluster_support = min(1.0, cluster_source_count / 3.0)
    value_score = round(trust_score * freshness * completeness * cluster_support, 4)
    return value_score, round(freshness, 4), completeness, round(cluster_support, 4)


def _topic_method(topic_matches: list[TopicMatch]) -> str:
    return "rule-based" if any(match.confidence >= 0.9 for match in topic_matches) else "zero-shot"


def _refresh_cluster_grade_payloads(cluster_id: int, indexer: QdrantIndexer) -> None:
    """Recalculate grade/uncertainty for all articles in a cluster."""

    qdrant_updates: list[tuple[list[str], dict[str, object]]] = []
    with SyncSessionLocal() as session:
        news_items = list(session.scalars(select(News).where(News.event_cluster_id == cluster_id)).all())
        if not news_items:
            return

        cluster_source_count = int(
            session.scalar(
                select(func.count(func.distinct(News.source_id))).where(News.event_cluster_id == cluster_id)
            )
            or 1
        )
        cluster_support = round(min(1.0, cluster_source_count / 3.0), 4)
        for item in news_items:
            source = session.get(Source, item.source_id)
            reliability = source.reliability if source is not None else "C"
            item.content_grade = derive_content_grade(
                reliability=reliability,
                cluster_source_count=cluster_source_count,
            )
            item.is_uncertain = derive_uncertainty(
                reliability=reliability,
                cluster_source_count=cluster_source_count,
            )
            point_ids = [
                str(point_id)
                for point_id in session.scalars(
                    select(Chunk.qdrant_point_id).where(Chunk.news_id == item.id)
                ).all()
            ]
            if point_ids:
                qdrant_updates.append(
                    (
                        point_ids,
                        {
                            "content_grade": item.content_grade,
                            "is_uncertain": bool(item.is_uncertain),
                            "cluster_support": cluster_support,
                            "event_cluster_id": cluster_id,
                        },
                    )
                )
        session.commit()

    for point_ids, payload in qdrant_updates:
        indexer.update_payload(point_ids, payload)


def process_one_news_article(
    news_id: int,
    *,
    qdrant_indexer: QdrantIndexer | None = None,
    force: bool = False,
) -> ProcessArticleResult:
    """Process one article into PostgreSQL side tables and Qdrant retrieval points."""

    t_start = time.monotonic()
    timings: dict[str, float] = {}

    def record_timing(name: str, stage_start: float) -> None:
        timings[name] = round(time.monotonic() - stage_start, 3)

    indexer = qdrant_indexer or QdrantIndexer()

    with SyncSessionLocal() as session:
        stage_start = time.monotonic()
        news = session.get(News, news_id)
        if news is None:
            return ProcessArticleResult(news_id, "not_found", 0, 0, 0, 0)
        if news.processed and not force:
            return ProcessArticleResult(news_id, "already_processed", 0, 0, 0, 0)

        source = session.get(Source, news.source_id)
        reliability = source.reliability if source is not None else "C"
        trust_score = source.trust_score if source is not None else 0.5
        source_name = source.name if source is not None else "Unknown"
        record_timing("load_article", stage_start)

        entity_text = _build_entity_text(news)
        stage_start = time.monotonic()
        extracted_entities = extract_entities(entity_text)
        record_timing("extract_entities", stage_start)

        stage_start = time.monotonic()
        topic_matches = resolve_topics(
            source_categories=_extract_source_categories(news),
            title=news.title,
            body=news.content or "",
        )
        record_timing("resolve_topics", stage_start)

        stage_start = time.monotonic()
        keyword_results = extract_keywords(entity_text)
        keyword_texts = [kw.text for kw in keyword_results]
        record_timing("extract_keywords", stage_start)

        stage_start = time.monotonic()
        lemma_title = lemmatize_text(news.title)
        has_full_content = bool((news.content or "").strip())
        lemma_body = ""
        if not has_full_content:
            fallback_text = "\n".join(
                part.strip()
                for part in [news.title, news.snippet_lead or ""]
                if part and part.strip()
            )
            keyword_results = extract_keywords(fallback_text)
            keyword_texts = [kw.text for kw in keyword_results]
        record_timing("prepare_text", stage_start)

        stage_start = time.monotonic()
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
        record_timing("build_chunks", stage_start)

        stage_start = time.monotonic()
        encoded_chunks = encode_texts(
            [chunk.text for chunk in prepared_chunks],
            sparse_texts=[chunk.lemma_text or chunk.text for chunk in prepared_chunks],
        )
        if len(encoded_chunks) != len(prepared_chunks):
            raise RuntimeError("Embedding runtime returned an unexpected number of vectors.")
        record_timing("encode_chunks", stage_start)

        representative_vector = next(
            (
                embedding.dense_vector
                for chunk, embedding in zip(prepared_chunks, encoded_chunks, strict=True)
                if chunk.zone == "body"
            ),
            encoded_chunks[0].dense_vector if encoded_chunks else None,
        )
        old_cluster_id = news.event_cluster_id or news.id
        stage_start = time.monotonic()
        resolved_cluster_id = resolve_event_cluster_id(news, current_dense_vector=representative_vector)
        record_timing("resolve_event_cluster", stage_start)
        news.event_cluster_id = resolved_cluster_id
        session.flush()

        if resolved_cluster_id != old_cluster_id:
            log_event(
                logger,
                logging.INFO,
                "event_cluster_resolved",
                news_id=news.id,
                old_cluster_id=old_cluster_id,
                new_cluster_id=resolved_cluster_id,
            )

        cluster_source_count = _resolve_cluster_source_count(session, news)
        cluster_article_count = _resolve_cluster_article_count(session, news.event_cluster_id or news.id)
        news.content_grade = derive_content_grade(
            reliability=reliability,
            cluster_source_count=cluster_source_count,
        )
        news.is_uncertain = derive_uncertainty(
            reliability=reliability,
            cluster_source_count=cluster_source_count,
        )
        value_score, freshness, completeness, cluster_support = _value_metrics(
            news=news,
            trust_score=trust_score,
            has_full_content=has_full_content,
            cluster_source_count=cluster_source_count,
        )
        nlp_enriched = bool(extracted_entities or topic_matches or keyword_texts)

        topic_names = [match.name for match in topic_matches]
        entity_names_pre = [entity.name for entity in extracted_entities]
        existing_point_ids = {
            str(point_id)
            for point_id in session.scalars(select(Chunk.qdrant_point_id).where(Chunk.news_id == news.id)).all()
        }
        indexed_chunks: list[IndexedChunk] = []
        chunk_rows: list[Chunk] = []

        for prepared_chunk, embedding_output in zip(prepared_chunks, encoded_chunks, strict=True):
            point_uuid = _deterministic_point_uuid(news.id, prepared_chunk.zone, prepared_chunk.chunk_index)
            point_id = str(point_uuid)
            payload = _build_chunk_payload(
                news,
                prepared_chunk,
                topic_names,
                source_name=source_name,
                trust_score=trust_score,
                keyword_texts=keyword_texts,
                entity_names=entity_names_pre,
                entity_ids=[],
                value_score=value_score,
                freshness=freshness,
                completeness=completeness,
                cluster_support=cluster_support,
                nlp_enriched=nlp_enriched,
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

        stage_start = time.monotonic()
        indexer.ensure_collection()
        record_timing("qdrant_ensure_collection", stage_start)

        stage_start = time.monotonic()
        indexer.upsert_chunks(indexed_chunks)
        record_timing("qdrant_upsert_chunks", stage_start)
        new_point_ids = [chunk.point_id for chunk in indexed_chunks]

        try:
            stage_start = time.monotonic()
            old_entity_ids = _load_existing_entity_ids(session, news.id)
            if old_entity_ids:
                decrement_cooccurrences(session, build_cooccurrence_edges(old_entity_ids))

            session.execute(delete(NewsTopic).where(NewsTopic.news_id == news.id))
            session.execute(delete(Chunk).where(Chunk.news_id == news.id))
            session.flush()

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
            entity_ids_post = _load_existing_entity_ids(session, news.id)
            entity_names_post = (
                [
                    entity.name
                    for entity in session.scalars(select(Entity).where(Entity.id.in_(entity_ids_post))).all()
                ]
                if entity_ids_post
                else entity_names_pre
            )

            coocc_edges = build_cooccurrence_edges(entity_ids_post)
            coocc_count = upsert_cooccurrences(session, coocc_edges)

            news.processed = True
            processed_at = datetime.now(timezone.utc).isoformat()
            processing_seconds = round(time.monotonic() - t_start, 3)
            record_timing("db_persist", stage_start)
            extra = dict(news.extra or {})
            extra["processing"] = {
                "status": "processed",
                "processed_at": processed_at,
                "processing_seconds": processing_seconds,
                "chunk_count": len(chunk_rows),
                "topic_names": topic_names,
                "topic_method": _topic_method(topic_matches),
                "keywords": keyword_texts,
                "entity_count": entity_count,
                "cooccurrence_edges": coocc_count,
                "cluster_source_count": cluster_source_count,
                "cluster_article_count": cluster_article_count,
                "value_score": value_score,
                "freshness": freshness,
                "completeness": completeness,
                "cluster_support": cluster_support,
                "fallback_body_used": not has_full_content and bool((news.snippet_lead or "").strip()),
                "timings": dict(timings),
            }
            news.extra = extra

            session.commit()
        except Exception:
            session.rollback()
            if new_point_ids:
                created_point_ids = [point_id for point_id in new_point_ids if point_id not in existing_point_ids]
                indexer.delete_points(created_point_ids)
            raise

        if new_point_ids:
            try:
                stage_start = time.monotonic()
                indexer.update_payload(
                    new_point_ids,
                    {
                        "entities": entity_names_post,
                        "entity_ids": entity_ids_post,
                        "content_grade": news.content_grade,
                        "is_uncertain": bool(news.is_uncertain),
                        "value_score": value_score,
                        "freshness": freshness,
                        "completeness": completeness,
                        "cluster_support": cluster_support,
                        "event_cluster_id": news.event_cluster_id or news.id,
                        "nlp_enriched": nlp_enriched,
                    },
                )
                record_timing("qdrant_update_payload", stage_start)
            except Exception:
                log_event(
                    logger,
                    logging.WARNING,
                    "processing_payload_update_failed",
                    news_id=news.id,
                    point_count=len(new_point_ids),
                )

            if existing_point_ids:
                try:
                    stage_start = time.monotonic()
                    indexer.delete_stale_points_for_news(news.id, keep_point_ids=set(new_point_ids))
                    record_timing("qdrant_stale_cleanup", stage_start)
                except Exception:
                    log_event(
                        logger,
                        logging.WARNING,
                        "processing_stale_points_cleanup_failed",
                        news_id=news.id,
                    )
            else:
                timings["qdrant_stale_cleanup"] = 0.0

        cluster_id = news.event_cluster_id or news.id
        if cluster_article_count > 1:
            try:
                stage_start = time.monotonic()
                _refresh_cluster_grade_payloads(cluster_id, indexer)
                record_timing("cluster_grade_refresh", stage_start)
            except Exception:
                log_event(
                    logger,
                    logging.WARNING,
                    "processing_cluster_grade_refresh_failed",
                    news_id=news.id,
                    cluster_id=cluster_id,
                )
        else:
            timings["cluster_grade_refresh"] = 0.0

        timings["total"] = round(time.monotonic() - t_start, 3)
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
            processing_timings=timings,
        )
        return ProcessArticleResult(
            news_id=news.id,
            status="processed",
            chunk_count=len(chunk_rows),
            topic_count=len(topic_matches),
            entity_count=entity_count,
            cooccurrence_edges=coocc_count,
        )
