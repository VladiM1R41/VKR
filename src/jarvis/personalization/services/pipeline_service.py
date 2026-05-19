"""Core Layer 4 personalization pipeline."""

from __future__ import annotations

from sqlalchemy.orm import Session

from jarvis.db.models import User
from jarvis.personalization.models.ranking_models import PersonalizedSearchResponse
from jarvis.personalization.services.diversity_service import DiversityService
from jarvis.personalization.services.ranking_service import PersonalizedRankingService
from jarvis.retrieval.models.search_models import SearchResponse


class PersonalizationPipelineService:
    """Apply the full Layer 4 online path over Layer 3 search output.

    The service intentionally stays API-agnostic: it takes an objective Layer 3
    response and returns a personalized shortlist with diversity applied.
    """

    def __init__(
        self,
        *,
        ranking_service: PersonalizedRankingService | None = None,
        diversity_service: DiversityService | None = None,
    ) -> None:
        self._ranking_service = ranking_service or PersonalizedRankingService()
        self._diversity_service = diversity_service or DiversityService()

    def personalize(
        self,
        session: Session,
        *,
        user_id: int,
        response: SearchResponse,
    ) -> PersonalizedSearchResponse:
        """Rerank and diversify Layer 3 candidates for one user."""
        ranked = self._ranking_service.rerank(session, user_id, response)
        diversity_slider = self._resolve_diversity_slider(session, user_id)
        return self._diversity_service.apply(ranked, diversity_slider=diversity_slider)

    @staticmethod
    def _resolve_diversity_slider(session: Session, user_id: int) -> float:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        settings = dict(user.settings or {})
        try:
            return max(0.0, min(1.0, float(settings.get("diversity_slider", 0.3))))
        except (TypeError, ValueError):
            return 0.3
