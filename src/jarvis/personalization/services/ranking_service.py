"""Personalized reranking service for Layer 4."""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.db.models import Chunk, Entity, Topic, User, UserEntitySubscription, UserEntityWeight, UserSourcePreference, UserTopicWeight
from jarvis.personalization.models.ranking_models import PersonalizedResult, PersonalizedSearchResponse
from jarvis.personalization.services.interaction_service import SessionSeenHistory
from jarvis.personalization.services.profile_update_service import SessionProfileStore
from jarvis.personalization.services.user_embedding_service import QdrantVectorFetcher, UserEmbeddingService
from jarvis.retrieval.models.search_models import SearchResponse


class PersonalizedRankingService:
    """Apply Layer 4 personalization over Layer 3 search results."""

    def __init__(
        self,
        *,
        seen_history: SessionSeenHistory | None = None,
        session_profile_store: SessionProfileStore | None = None,
        user_embedding_service: UserEmbeddingService | None = None,
        vector_fetcher: QdrantVectorFetcher | None = None,
    ) -> None:
        self._seen_history = seen_history or SessionSeenHistory()
        self._session_profile_store = session_profile_store or SessionProfileStore()
        self._vector_fetcher = vector_fetcher or QdrantVectorFetcher()
        self._user_embedding_service = user_embedding_service or UserEmbeddingService(
            vector_fetcher=self._vector_fetcher
        )
        self._weights = {
            "topic": 0.18,
            "entity": 0.20,
            "source": 0.10,
            "session": 0.15,
            "embedding": 0.12,
            "seen": 0.30,
            "block": 1.00,
        }

    def rerank(self, session: Session, user_id: int, response: SearchResponse) -> PersonalizedSearchResponse:
        """Rerank Layer 3 results according to explicit and implicit profile state."""
        user = session.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        topic_weights = self._load_topic_weights(session, user_id)
        entity_weights = self._load_entity_weights(session, user_id)
        entity_subscriptions = self._load_entity_subscriptions(session, user_id)
        source_preferences = self._load_source_preferences(session, user_id)
        seen_news_ids = set(self._seen_history.get_seen_news_ids(user_id=user_id))
        session_profile = self._session_profile_store.load(user_id)
        user_embedding = self._user_embedding_service.load_user_embedding(session, user_id)
        article_vectors = (
            self._load_article_vectors(session, [result.news_id for result in response.results])
            if user_embedding
            else {}
        )
        session_topic_ids = set(int(value) for value in session_profile.get("recent_topic_ids", []))
        session_entity_ids = set(int(value) for value in session_profile.get("recent_entity_ids", []))
        topic_name_to_id = self._load_topic_name_to_id(session, [name for result in response.results for name in result.topics])
        entity_name_to_id = self._load_entity_name_to_id(session, [name for result in response.results for name in result.entities])
        ranked: list[PersonalizedResult] = []

        for result in sorted(response.results, key=lambda item: float(item.score), reverse=True):
            reasons: list[str] = []
            base_score = float(result.score)

            topic_affinity, topic_reasons = self._topic_affinity(
                result.topics,
                topic_name_to_id,
                topic_weights,
            )
            reasons.extend(topic_reasons)

            entity_affinity, entity_reasons = self._entity_affinity(
                result.entities,
                entity_name_to_id,
                entity_weights,
                entity_subscriptions,
            )
            reasons.extend(entity_reasons)

            source_affinity, source_reasons, is_blocked = self._source_affinity(
                result.source_id,
                result.source_name,
                source_preferences,
            )
            reasons.extend(source_reasons)

            session_affinity, session_reasons = self._session_affinity(
                result.topics,
                result.entities,
                topic_name_to_id,
                entity_name_to_id,
                session_topic_ids,
                session_entity_ids,
            )
            reasons.extend(session_reasons)

            embedding_affinity = self._embedding_affinity(
                user_embedding,
                article_vectors.get(result.news_id),
            )
            if embedding_affinity >= 0.55:
                reasons.append("embedding_match")

            seen_penalty = 1.0 if result.news_id in seen_news_ids else 0.0
            if seen_penalty:
                reasons.append("seen_penalty_applied")

            personalized_score = (
                base_score
                + self._weights["topic"] * topic_affinity
                + self._weights["entity"] * entity_affinity
                + self._weights["source"] * source_affinity
                + self._weights["session"] * session_affinity
                + self._weights["embedding"] * embedding_affinity
                - self._weights["seen"] * seen_penalty
                - self._weights["block"] * (1.0 if is_blocked else 0.0)
            )
            # Гарантируем [0.0, 1.0]: аддитивная формула может дать > 1 при высоком affinity
            personalized_score = max(0.0, min(1.0, personalized_score))

            ranked.append(
                PersonalizedResult(
                    news_id=result.news_id,
                    source_id=result.source_id,
                    source_name=result.source_name,
                    title=result.title,
                    snippet=result.snippet,
                    base_score=round(base_score, 4),
                    personalized_score=round(personalized_score, 4),
                    topics=list(result.topics),
                    entities=list(result.entities),
                    published_at=result.published_at,
                    explanation=result.explanation,
                    personalization_reasons=reasons,
                    chunk_id=result.chunk_id,
                    rerank_score=result.rerank_score,
                )
            )

        ranked.sort(key=lambda item: item.personalized_score, reverse=True)
        return PersonalizedSearchResponse(
            query=response.query,
            corrected_query=response.corrected_query,
            intent=response.intent,
            total=len(ranked),
            results=ranked,
        )

    @staticmethod
    def _load_topic_weights(session: Session, user_id: int) -> dict[int, float]:
        rows = session.scalars(select(UserTopicWeight).where(UserTopicWeight.user_id == user_id)).all()
        return {row.topic_id: float(row.weight) for row in rows}

    @staticmethod
    def _load_entity_weights(session: Session, user_id: int) -> dict[int, float]:
        rows = session.scalars(select(UserEntityWeight).where(UserEntityWeight.user_id == user_id)).all()
        return {row.entity_id: float(row.weight) for row in rows}

    @staticmethod
    def _load_entity_subscriptions(session: Session, user_id: int) -> set[int]:
        rows = session.scalars(
            select(UserEntitySubscription.entity_id).where(UserEntitySubscription.user_id == user_id)
        ).all()
        return {int(value) for value in rows}

    @staticmethod
    def _load_source_preferences(session: Session, user_id: int) -> dict[int, str]:
        rows = session.scalars(
            select(UserSourcePreference).where(UserSourcePreference.user_id == user_id)
        ).all()
        return {row.source_id: row.preference for row in rows}

    @staticmethod
    def _load_topic_name_to_id(session: Session, topic_names: list[str]) -> dict[str, int]:
        if not topic_names:
            return {}
        rows = session.scalars(select(Topic).where(Topic.name.in_(sorted(set(topic_names))))).all()
        return {str(row.name): int(row.id) for row in rows}

    @staticmethod
    def _load_entity_name_to_id(session: Session, entity_names: list[str]) -> dict[str, int]:
        if not entity_names:
            return {}
        rows = session.scalars(select(Entity).where(Entity.name.in_(sorted(set(entity_names))))).all()
        return {str(row.name): int(row.id) for row in rows}

    @staticmethod
    def _topic_affinity(
        topic_names: list[str],
        topic_name_to_id: dict[str, int],
        topic_weights: dict[int, float],
    ) -> tuple[float, list[str]]:
        weights = []
        reasons: list[str] = []
        for topic_name in topic_names:
            topic_id = topic_name_to_id.get(topic_name)
            if topic_id is None:
                continue
            value = topic_weights.get(topic_id)
            if value is None:
                continue
            weights.append(value)
            if value >= 0.55:
                reasons.append(f"topic_match: {topic_name}")
        if not weights:
            return 0.0, reasons
        return max(0.0, sum(weights) / len(weights) - 0.5), reasons

    @staticmethod
    def _entity_affinity(
        entity_names: list[str],
        entity_name_to_id: dict[str, int],
        entity_weights: dict[int, float],
        entity_subscriptions: set[int],
    ) -> tuple[float, list[str]]:
        weights = []
        reasons: list[str] = []
        for entity_name in entity_names:
            entity_id = entity_name_to_id.get(entity_name)
            if entity_id is None:
                continue
            value = entity_weights.get(entity_id)
            if value is not None:
                weights.append(value)
            if entity_id in entity_subscriptions:
                reasons.append(f"entity_subscription: {entity_name}")
                weights.append(1.0)
        if not weights:
            return 0.0, reasons
        return max(0.0, sum(weights) / len(weights) - 0.5), reasons

    @staticmethod
    def _source_affinity(
        source_id: int,
        source_name: str,
        source_preferences: dict[int, str],
    ) -> tuple[float, list[str], bool]:
        preference = source_preferences.get(source_id, "neutral")
        if preference == "preferred":
            return 1.0, [f"preferred_source: {source_name}"], False
        if preference == "blocked":
            return -1.0, [f"blocked_source: {source_name}"], True
        return 0.0, [], False

    @staticmethod
    def _session_affinity(
        topic_names: list[str],
        entity_names: list[str],
        topic_name_to_id: dict[str, int],
        entity_name_to_id: dict[str, int],
        session_topic_ids: set[int],
        session_entity_ids: set[int],
    ) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0

        for topic_name in topic_names:
            topic_id = topic_name_to_id.get(topic_name)
            if topic_id is not None and topic_id in session_topic_ids:
                reasons.append(f"session_interest: {topic_name}")
                score = max(score, 1.0)

        for entity_name in entity_names:
            entity_id = entity_name_to_id.get(entity_name)
            if entity_id is not None and entity_id in session_entity_ids:
                reasons.append(f"session_interest: {entity_name}")
                score = max(score, 1.0)

        return score, reasons

    def _load_article_vectors(self, session: Session, news_ids: list[int]) -> dict[int, list[float]]:
        if not news_ids:
            return {}

        stmt = (
            select(Chunk.news_id, Chunk.qdrant_point_id, Chunk.zone)
            .where(Chunk.news_id.in_(sorted(set(news_ids))))
            .order_by(Chunk.news_id.asc(), Chunk.zone.asc(), Chunk.chunk_index.asc())
        )
        rows = session.execute(stmt).all()
        best_point_by_news: dict[int, str] = {}
        for news_id, point_id, zone in rows:
            if int(news_id) in best_point_by_news:
                continue
            best_point_by_news[int(news_id)] = str(point_id)

        vectors_by_point = self._vector_fetcher.fetch_dense_vectors(list(best_point_by_news.values()))
        result: dict[int, list[float]] = {}
        for news_id, point_id in best_point_by_news.items():
            vector = vectors_by_point.get(point_id)
            if vector:
                result[news_id] = vector
        return result

    @staticmethod
    def _embedding_affinity(user_vector: list[float] | None, article_vector: list[float] | None) -> float:
        if not user_vector or not article_vector or len(user_vector) != len(article_vector):
            return 0.0
        dot = sum(float(left) * float(right) for left, right in zip(user_vector, article_vector))
        user_norm = math.sqrt(sum(float(value) * float(value) for value in user_vector))
        article_norm = math.sqrt(sum(float(value) * float(value) for value in article_vector))
        if user_norm <= 0.0 or article_norm <= 0.0:
            return 0.0
        cosine = dot / (user_norm * article_norm)
        return max(0.0, min(1.0, (cosine + 1.0) / 2.0))
