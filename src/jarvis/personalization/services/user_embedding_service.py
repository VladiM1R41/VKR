"""User embedding builder for Layer 4."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import struct

from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.core.settings import get_settings
from jarvis.db.models import Chunk, User, UserEmbedding, UserInteraction


logger = logging.getLogger(__name__)


def _serialize_float32_vector(values: list[float]) -> bytes:
    """Serialize vector to BYTEA-compatible float32 payload."""
    return struct.pack(f"<{len(values)}f", *values)


def _deserialize_float32_vector(payload: bytes) -> list[float]:
    """Deserialize float32 BYTEA payload back to Python floats."""
    if not payload:
        return []
    if len(payload) % 4 != 0:
        raise ValueError("Invalid float32 payload length")
    count = len(payload) // 4
    return list(struct.unpack(f"<{count}f", payload))


@dataclass(frozen=True, slots=True)
class UserEmbeddingBuildResult:
    """Result of one user-embedding rebuild."""

    user_id: int
    article_count: int
    vector_dim: int
    updated: bool


class QdrantVectorFetcher:
    """Fetch dense vectors for chunk point ids from Qdrant."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def _client(self):
        from qdrant_client import QdrantClient

        return QdrantClient(url=self._settings.qdrant_url)

    def fetch_dense_vectors(self, point_ids: list[str]) -> dict[str, list[float]]:
        """Load dense vectors keyed by Qdrant point id."""
        if not point_ids:
            return {}

        client = self._client()
        points = client.retrieve(
            collection_name=self._settings.qdrant_collection_alias,
            ids=point_ids,
            with_vectors=True,
            with_payload=False,
        )

        result: dict[str, list[float]] = {}
        for point in points:
            vector = point.vector
            dense = None
            if isinstance(vector, dict):
                dense = vector.get("dense")
            elif isinstance(vector, list):
                dense = vector
            if dense:
                result[str(point.id)] = [float(value) for value in dense]
        return result


class UserEmbeddingService:
    """Build and persist centroid user embeddings from interaction history."""

    def __init__(self, *, vector_fetcher: QdrantVectorFetcher | None = None) -> None:
        self._vector_fetcher = vector_fetcher or QdrantVectorFetcher()
        self._positive_actions = {"like", "share", "save", "read"}
        self._article_weights = {
            "like": 1.0,
            "share": 1.0,
            "save": 0.8,
            "read": 0.6,
        }

    def rebuild_user_embedding(self, session: Session, user_id: int, *, limit: int = 50) -> UserEmbeddingBuildResult:
        """Rebuild one user's centroid embedding from positive interactions."""
        user = session.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        article_actions = self._load_positive_article_actions(session, user_id, limit=limit)
        if not article_actions:
            return UserEmbeddingBuildResult(user_id=user_id, article_count=0, vector_dim=0, updated=False)

        article_vectors = self._load_article_vectors(session, list(article_actions))
        if not article_vectors:
            return UserEmbeddingBuildResult(user_id=user_id, article_count=0, vector_dim=0, updated=False)

        centroid = self._build_centroid(article_vectors, article_actions)
        if not centroid:
            return UserEmbeddingBuildResult(user_id=user_id, article_count=0, vector_dim=0, updated=False)

        payload = _serialize_float32_vector(centroid)
        row = session.get(UserEmbedding, user_id)
        if row is None:
            row = UserEmbedding(user_id=user_id, embedding=payload)
            session.add(row)
        else:
            row.embedding = payload
        session.commit()

        return UserEmbeddingBuildResult(
            user_id=user_id,
            article_count=len(article_vectors),
            vector_dim=len(centroid),
            updated=True,
        )

    def load_user_embedding(self, session: Session, user_id: int) -> list[float] | None:
        """Load stored user embedding as floats."""
        row = session.get(UserEmbedding, user_id)
        if row is None:
            return None
        return _deserialize_float32_vector(bytes(row.embedding))

    def _load_positive_article_actions(self, session: Session, user_id: int, *, limit: int) -> dict[int, str]:
        stmt = (
            select(UserInteraction)
            .where(
                UserInteraction.user_id == user_id,
                UserInteraction.action.in_(sorted(self._positive_actions)),
            )
            .order_by(UserInteraction.created_at.desc())
            .limit(limit)
        )
        rows = session.scalars(stmt).all()
        article_actions: dict[int, str] = {}
        for row in rows:
            article_actions.setdefault(int(row.news_id), str(row.action))
        return article_actions

    def _load_article_vectors(self, session: Session, news_ids: list[int]) -> dict[int, list[float]]:
        stmt = (
            select(Chunk.news_id, Chunk.qdrant_point_id, Chunk.zone)
            .where(Chunk.news_id.in_(news_ids))
            .order_by(Chunk.news_id.asc(), Chunk.zone.asc(), Chunk.chunk_index.asc())
        )
        rows = session.execute(stmt).all()
        best_point_by_news: dict[int, str] = {}
        for news_id, point_id, zone in rows:
            if news_id in best_point_by_news:
                continue
            best_point_by_news[int(news_id)] = str(point_id)

        vectors_by_point = self._vector_fetcher.fetch_dense_vectors(list(best_point_by_news.values()))
        result: dict[int, list[float]] = {}
        for news_id, point_id in best_point_by_news.items():
            vector = vectors_by_point.get(point_id)
            if vector:
                result[news_id] = vector
            else:
                logger.warning(
                    "Qdrant vector not found for point_id=%s (news_id=%s), skipping",
                    point_id,
                    news_id,
                )
        return result

    def _build_centroid(self, article_vectors: dict[int, list[float]], article_actions: dict[int, str]) -> list[float]:
        weighted_vectors: list[tuple[list[float], float]] = []
        for news_id, vector in article_vectors.items():
            action = article_actions.get(news_id)
            if action is None:
                continue
            weight = self._article_weights.get(action, 0.0)
            if weight <= 0.0:
                continue
            weighted_vectors.append((vector, weight))

        if not weighted_vectors:
            return []

        dim = len(weighted_vectors[0][0])
        accum = [0.0] * dim
        total_weight = 0.0
        for vector, weight in weighted_vectors:
            if len(vector) != dim:
                continue
            total_weight += weight
            for idx, value in enumerate(vector):
                accum[idx] += float(value) * weight

        if total_weight <= 0.0:
            return []
        return [value / total_weight for value in accum]

    def rebuild_recent_user_embeddings(
        self,
        session: Session,
        *,
        limit_users: int = 100,
        per_user_limit: int = 50,
    ) -> list[UserEmbeddingBuildResult]:
        """Rebuild centroid embeddings for users with recent positive activity."""
        stmt = (
            select(UserInteraction.user_id)
            .where(UserInteraction.action.in_(sorted(self._positive_actions)))
            .distinct()
            .order_by(UserInteraction.user_id.asc())
            .limit(limit_users)
        )
        user_ids = [int(value) for value in session.scalars(stmt).all()]
        results: list[UserEmbeddingBuildResult] = []
        for user_id in user_ids:
            results.append(self.rebuild_user_embedding(session, user_id, limit=per_user_limit))
        return results
