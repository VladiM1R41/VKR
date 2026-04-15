"""Digest shortlist orchestration for Layer 4."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.generation.services.answer_generation_service import AnswerGenerationService

from sqlalchemy import select
from sqlalchemy.orm import Session

from jarvis.core.logging import log_event
from jarvis.db.models import Digest, DigestItem, News, Source
from jarvis.generation.services.context_assembler import NewsWithContext
from jarvis.personalization.models.digest_models import DigestCandidate, DigestShortlist
from jarvis.personalization.models.ranking_models import PersonalizedSearchResponse


logger = logging.getLogger(__name__)


class DigestOrchestrationService:
    """Assemble digest shortlists with dedup and continuity rules."""

    def build_shortlist(
        self,
        session: Session,
        *,
        user_id: int,
        digest_type: str,
        ranked_response: PersonalizedSearchResponse,
        limit: int = 7,
        history_lookback: int = 3,
    ) -> DigestShortlist:
        """Build a digest shortlist from personalized ranking results."""
        previous_digests = self._load_previous_digests(
            session,
            user_id=user_id,
            digest_type=digest_type,
            limit=history_lookback,
        )
        previous_news_ids = self._load_previous_news_ids(session, previous_digests)
        previous_topics = self._collect_previous_topics(previous_digests)

        selected: list[DigestCandidate] = []
        topic_counter: Counter[str] = Counter()

        for result in ranked_response.results:
            if len(selected) >= limit:
                break
            if result.news_id in previous_news_ids:
                continue

            reasons = list(result.personalization_reasons)
            fresh_topics = [topic for topic in result.topics if topic not in previous_topics]
            if fresh_topics:
                reasons.append(f"continuity_new_topic: {fresh_topics[0]}")

            if result.topics and any(topic_counter[topic] >= 2 for topic in result.topics):
                continue

            selected.append(
                DigestCandidate(
                    news_id=result.news_id,
                    title=result.title,
                    source_name=result.source_name,
                    position=len(selected) + 1,
                    score=result.personalized_score,
                    topics=list(result.topics),
                    snippet=result.snippet,
                    reasons=reasons,
                )
            )
            for topic in result.topics:
                topic_counter[topic] += 1

        if len(selected) < limit:
            for result in ranked_response.results:
                if len(selected) >= limit:
                    break
                if result.news_id in {item.news_id for item in selected}:
                    continue
                selected.append(
                    DigestCandidate(
                        news_id=result.news_id,
                        title=result.title,
                        source_name=result.source_name,
                        position=len(selected) + 1,
                        score=result.personalized_score,
                        topics=list(result.topics),
                        snippet=result.snippet,
                        reasons=[*result.personalization_reasons, "fallback_fill"],
                    )
                )

        topics_covered = sorted({topic for item in selected for topic in item.topics})
        content_hash = self._build_content_hash(digest_type, [item.news_id for item in selected])
        duplicate = self._content_hash_exists(
            session,
            user_id=user_id,
            digest_type=digest_type,
            content_hash=content_hash,
        )

        return DigestShortlist(
            user_id=user_id,
            digest_type=digest_type,
            candidates=selected,
            topics_covered=topics_covered,
            content_hash=content_hash,
            is_duplicate_of_existing=duplicate,
        )

    def persist_shortlist(
        self,
        session: Session,
        *,
        shortlist: DigestShortlist,
        content_text: str = "",
        generation_log_id: int | None = None,
    ) -> Digest:
        """Persist digest shortlist as digests + digest_items rows.

        Args:
            session: DB session.
            shortlist: shortlist из build_shortlist.
            content_text: сгенерированный текст дайджеста (из L5).
            generation_log_id: ссылка на generation_logs (из L5).
        """
        existing = self._load_digest_by_content_hash(
            session,
            user_id=shortlist.user_id,
            digest_type=shortlist.digest_type,
            content_hash=shortlist.content_hash,
        )
        if existing is not None:
            return existing

        digest = Digest(
            user_id=shortlist.user_id,
            digest_type=shortlist.digest_type,
            content_text=content_text,
            news_count=len(shortlist.candidates),
            topics_covered=list(shortlist.topics_covered),
            content_hash=shortlist.content_hash,
            generation_log_id=generation_log_id,
        )
        session.add(digest)
        session.flush()

        for item in shortlist.candidates:
            session.add(
                DigestItem(
                    digest_id=digest.id,
                    news_id=item.news_id,
                    position=item.position,
                    snippet=item.snippet,
                )
            )

        session.commit()
        return digest

    @staticmethod
    def _load_previous_digests(
        session: Session,
        *,
        user_id: int,
        digest_type: str,
        limit: int,
    ) -> list[Digest]:
        stmt = (
            select(Digest)
            .where(Digest.user_id == user_id, Digest.digest_type == digest_type)
            .order_by(Digest.generated_at.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

    @staticmethod
    def _load_previous_news_ids(session: Session, digests: list[Digest]) -> set[int]:
        digest_ids = [digest.id for digest in digests]
        if not digest_ids:
            return set()
        stmt = select(DigestItem.news_id).where(DigestItem.digest_id.in_(digest_ids))
        return {int(value) for value in session.scalars(stmt).all()}

    @staticmethod
    def _collect_previous_topics(digests: list[Digest]) -> set[str]:
        result: set[str] = set()
        for digest in digests:
            for topic in digest.topics_covered or []:
                result.add(str(topic))
        return result

    @staticmethod
    def _build_content_hash(digest_type: str, news_ids: list[int]) -> str:
        payload = f"{digest_type}:{','.join(str(news_id) for news_id in news_ids)}"
        return sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _content_hash_exists(
        session: Session,
        *,
        user_id: int,
        digest_type: str,
        content_hash: str,
    ) -> bool:
        stmt = select(Digest.id).where(
            Digest.user_id == user_id,
            Digest.digest_type == digest_type,
            Digest.content_hash == content_hash,
        )
        return session.scalar(stmt) is not None

    @staticmethod
    def _load_digest_by_content_hash(
        session: Session,
        *,
        user_id: int,
        digest_type: str,
        content_hash: str,
    ) -> Digest | None:
        stmt = select(Digest).where(
            Digest.user_id == user_id,
            Digest.digest_type == digest_type,
            Digest.content_hash == content_hash,
        )
        return session.scalar(stmt)

    # ───────────────────────────────────────────────────────
    # Связь со Слоем 5: генерация текста дайджеста
    # ───────────────────────────────────────────────────────

    def generate_digest_text(
        self,
        session: Session,
        shortlist: DigestShortlist,
        generation_service: AnswerGenerationService,
        continuity_context: str = "",
    ) -> tuple[str, int | None]:
        """Сгенерировать текст дайджеста через L5 и обновить digest.

        Args:
            session: DB session.
            shortlist: shortlist кандидатов из build_shortlist.
            generation_service: AnswerGenerationService из Слоя 5.
            continuity_context: контекст предыдущих дайджестов (опционально).

        Returns:
            (digest_text, generation_log_id)
        """
        # Загружаем полные данные новостей для NewsWithContext
        news_ids = [item.news_id for item in shortlist.candidates]
        news_rows = session.scalars(select(News).where(News.id.in_(news_ids))).all()
        news_by_id = {news.id: news for news in news_rows}

        # Загружаем источники для source_name
        source_ids = {news.source_id for news in news_rows}
        sources = session.scalars(select(Source).where(Source.id.in_(source_ids))).all()
        source_by_id = {source.id: source.name for source in sources}

        # Строим NewsWithContext
        news_items: list[NewsWithContext] = []
        for candidate in shortlist.candidates:
            news = news_by_id.get(candidate.news_id)
            if news is None:
                continue
            news_items.append(
                NewsWithContext(
                    news_id=news.id,
                    source_id=news.source_id,
                    source_name=source_by_id.get(news.source_id, "Unknown"),
                    title=news.title,
                    content=news.content or "",
                    snippet_lead=news.snippet_lead or "",
                    score=float(candidate.score),
                    rerank_score=float(candidate.score),
                    personalized_score=float(candidate.score),
                    topics=list(candidate.topics),
                    entities=[],
                    published_at_str=str(news.published_at or ""),
                    trust_score=float((news.extra or {}).get("trust_score", 0.5)),
                    content_grade=int(news.content_grade or 6),
                    information_type=str((news.extra or {}).get("information_type", "daily")),
                    urgency=str((news.extra or {}).get("urgency", "normal")),
                    event_cluster_id=getattr(news, "event_cluster_id", None),
                )
            )

        if not news_items:
            log_event(
                logger,
                logging.WARNING,
                "digest_generation_no_news",
                user_id=shortlist.user_id,
                digest_type=shortlist.digest_type,
            )
            return "", None

        # Вызываем L5
        result = generation_service.generate_digest(
            news_items=news_items,
            user_id=shortlist.user_id,
            continuity_context=continuity_context,
        )

        log_event(
            logger,
            logging.INFO,
            "digest_text_generated",
            user_id=shortlist.user_id,
            digest_type=shortlist.digest_type,
            document_count=result.documents_used_count,
            model_name=result.model_name,
            generation_log_id=result.generation_log_id,
        )

        return result.digest_text, result.generation_log_id
