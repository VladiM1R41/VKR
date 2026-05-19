"""Profile endpoints over Layer 4 preferences."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_current_user_id, get_db
from jarvis.app.schemas.profile import InteractionItem, InteractionsResponse
from jarvis.db.models import News, UserInteraction
from jarvis.personalization.models.preferences_models import (
    ExplicitPreferencesResponse,
    ExplicitPreferencesUpdateRequest,
)
from jarvis.personalization.services.preferences_service import ExplicitPreferencesService

router = APIRouter()


@router.get("", response_model=ExplicitPreferencesResponse)
def get_profile(
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ExplicitPreferencesResponse:
    try:
        return ExplicitPreferencesService().get_preferences(session, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/preferences", response_model=ExplicitPreferencesResponse)
def update_preferences(
    payload: ExplicitPreferencesUpdateRequest,
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ExplicitPreferencesResponse:
    data = payload.model_copy(deep=True)
    data.profile.user_id = data.profile.user_id or user_id
    try:
        result = ExplicitPreferencesService().update_preferences(session, data)
        session.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/interactions", response_model=InteractionsResponse)
def interactions(
    session: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> InteractionsResponse:
    total = session.scalar(
        select(func.count()).select_from(UserInteraction).where(UserInteraction.user_id == user_id)
    ) or 0
    rows = session.execute(
        select(UserInteraction, News.title)
        .join(News, News.id == UserInteraction.news_id)
        .where(UserInteraction.user_id == user_id)
        .order_by(desc(UserInteraction.created_at))
        .limit(limit)
        .offset(offset)
    ).all()
    return InteractionsResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            InteractionItem(
                id=interaction.id,
                news_id=interaction.news_id,
                title=title,
                action=interaction.action,
                dwell_time_sec=interaction.dwell_time_sec,
                search_log_id=interaction.search_log_id,
                created_at=interaction.created_at,
            )
            for interaction, title in rows
        ],
    )

