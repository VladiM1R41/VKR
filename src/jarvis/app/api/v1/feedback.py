"""POST /feedback — запись взаимодействия пользователя с новостью."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_db, get_default_user_id

router = APIRouter(prefix="/feedback", tags=["Feedback"])

VALID_ACTIONS = {"like", "dislike", "save", "hide", "click", "read_long", "click_short", "skip"}


class FeedbackIn(BaseModel):
    news_id: int
    action: str


class FeedbackOut(BaseModel):
    recorded: bool
    news_id: int
    action: str


@router.post(
    "",
    response_model=FeedbackOut,
    summary="Записать взаимодействие с новостью",
    description="Фиксирует действие пользователя (like/dislike/save/hide/click/read_long). "
                "Автоматически обновляет профиль пользователя через EMA-механизм Layer 4.",
)
def record_feedback(
    body: FeedbackIn,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_default_user_id),
) -> FeedbackOut:
    from jarvis.personalization.services.interaction_service import InteractionService
    from jarvis.personalization.services.profile_update_service import ProfileUpdateService

    action = body.action if body.action in VALID_ACTIONS else "click"

    interaction_service = InteractionService()
    interaction_service.record_interaction(
        db,
        user_id=user_id,
        news_id=body.news_id,
        action=action,
    )

    profile_service = ProfileUpdateService()
    profile_service.update_from_interaction(
        db,
        user_id=user_id,
        news_id=body.news_id,
        action=action,
    )

    return FeedbackOut(recorded=True, news_id=body.news_id, action=action)
