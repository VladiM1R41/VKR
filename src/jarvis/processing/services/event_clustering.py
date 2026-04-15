"""Event clustering for Layer 2.

Слой 1 ставит tentative event_cluster_id = news.id (одиночный кластер).
Слой 2 находит статьи про одно событие и объединяет их.

Алгоритм MVP (по FINAL_LAYER_2_GUIDE.md раздел 14):
1. Взять dense embedding текущей статьи
2. Найти кандидатов за окно 48 часов
3. Отфильтровать по cosine similarity > threshold
4. Выбрать representative (самый ранний news.id в кластере)
5. Обновить news.event_cluster_id

External signals (усиливают confidence):
- extra.yandex_story_tag (AIF)
- extra.source_related_urls
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from math import sqrt

from sqlalchemy import select

from jarvis.db.models import Chunk, News
from jarvis.db.session import SyncSessionLocal


logger = logging.getLogger(__name__)

# Порог cosine similarity для объединения в кластер
_SIMILARITY_THRESHOLD = 0.75

# Временное окно для поиска кандидатов (часы)
_TEMPORAL_WINDOW_HOURS = 48


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Вычислить cosine similarity между двумя векторами."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = sqrt(sum(a * a for a in vec_a))
    norm_b = sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_article_dense_vector(news_id: int) -> list[float] | None:
    """Получить dense vector первого body-чанка статьи из Qdrant.

    Для MVP используем stored dense vector из Qdrant payload.
    Альтернатива: перекодировать title — но это лишний вызов модели.
    """
    from jarvis.processing.services.qdrant_index import QdrantIndexer
    from jarvis.core.settings import get_settings

    settings = get_settings()
    qdrant_indexer = QdrantIndexer()
    client = qdrant_indexer._client()

    # Находим чанки этой статьи
    with SyncSessionLocal() as session:
        chunk_points = list(
            session.execute(
                select(Chunk.qdrant_point_id).where(
                    Chunk.news_id == news_id,
                    Chunk.zone == "body",
                )
            )
        )

    if not chunk_points:
        # Нет body чанков — пробуем title
        with SyncSessionLocal() as session:
            chunk_points = list(
                session.execute(
                    select(Chunk.qdrant_point_id).where(
                        Chunk.news_id == news_id,
                    )
                )
            )

    if not chunk_points:
        return None

    # Берём первый чанк как representative вектор
    point_id = str(chunk_points[0][0])
    try:
        points = client.retrieve(
            collection_name=settings.qdrant_collection_alias,
            ids=[point_id],
            with_vectors=True,
        )
        if points and points[0].vector:
            vec = points[0].vector
            if isinstance(vec, dict):
                return vec.get("dense")
            return vec
    except Exception as exc:
        logger.warning("failed to retrieve vector from Qdrant: %s", exc)

    return None


def find_cluster_candidates(news: News) -> list[News]:
    """Найти потенциальные статьи для объединения в кластер.

    Критерии:
    - published_at в окне ±48 часов
    - тот же language
    - тот же information_type (опционально, для ускорения)
    """
    if news.published_at is None:
        return []

    window_start = news.published_at - timedelta(hours=_TEMPORAL_WINDOW_HOURS)
    window_end = news.published_at + timedelta(hours=_TEMPORAL_WINDOW_HOURS)

    with SyncSessionLocal() as session:
        stmt = (
            select(News)
            .where(
                News.id != news.id,
                News.published_at >= window_start,
                News.published_at <= window_end,
                News.language == news.language,
                News.processed.is_(True),  # только обработанные статьи
            )
            .order_by(News.published_at.desc())
            .limit(100)  # ограничиваем для производительности
        )
        return list(session.scalars(stmt).all())


def find_best_cluster_match(
    news: News,
    candidates: list[News],
    *,
    current_dense_vector: list[float] | None = None,
) -> News | None:
    """Найти наиболее похожую статью из кандидатов.

    Сравниваем dense vectors через cosine similarity.
    """
    news_vector = current_dense_vector or _get_article_dense_vector(news.id)
    if news_vector is None:
        return None

    best_match: News | None = None
    best_score = 0.0

    for candidate in candidates:
        candidate_vector = _get_article_dense_vector(candidate.id)
        if candidate_vector is None:
            continue

        score = _cosine_similarity(news_vector, candidate_vector)
        if score > best_score:
            best_score = score
            best_match = candidate

    if best_score >= _SIMILARITY_THRESHOLD:
        logger.info(
            "event clustering match: news_id=%d → cluster_id=%d (similarity=%.3f)",
            news.id,
            best_match.id,
            best_score,
        )
        return best_match

    return None


def resolve_event_cluster_id(news: News, *, current_dense_vector: list[float] | None = None) -> int:
    """Определить event_cluster_id для статьи.

    Алгоритм:
    1. Найти кандидатов за 48 часов
    2. Сравнить dense vectors
    3. Если match найден → вернуть его cluster_id (или его самого)
    4. Если нет → вернуть news.id (одиночный кластер)

    Representative кластера = самый ранний news.id.
    """
    candidates = find_cluster_candidates(news)
    if not candidates:
        return news.id

    best_match = find_best_cluster_match(
        news,
        candidates,
        current_dense_vector=current_dense_vector,
    )
    if best_match is None:
        return news.id

    # Representative = самый ранний id в кластере
    cluster_id = min(news.id, best_match.event_cluster_id or best_match.id)
    return cluster_id
