"""Feedback endpoint over Layer 4 interaction logging."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_current_user_id, get_db
from jarvis.app.schemas.profile import FeedbackRequest, FeedbackResponse
from jarvis.personalization.models.interaction_models import InteractionEventRequest
from jarvis.personalization.services.interaction_service import InteractionLoggingService
from jarvis.personalization.services.profile_update_service import ProfileUpdateService

router = APIRouter()


@router.post("", response_model=FeedbackResponse)
def feedback(
    request: FeedbackRequest,
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> FeedbackResponse:
    try:
        event = InteractionEventRequest(
            user_id=user_id,
            news_id=request.news_id,
            action=request.action,
            dwell_time_sec=request.dwell_time_sec,
            search_log_id=request.search_log_id,
            session_id=request.session_id,
        )
        response = InteractionLoggingService().log_interaction(session, event, commit=False)
        ProfileUpdateService().update_from_interaction(session, response.interaction_id, commit=False)
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FeedbackResponse(
        recorded=True,
        interaction_id=response.interaction_id,
        stored_action=response.stored_action,
        derived_signal=response.derived_signal,
    )
