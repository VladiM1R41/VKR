"""Authentication endpoints for Layer 6."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from jarvis.app.dependencies import get_current_user, get_db, is_admin_user
from jarvis.app.schemas.auth import (
    AuthLoginRequest,
    AuthLogoutResponse,
    AuthRegisterRequest,
    AuthTokenResponse,
    AuthUserResponse,
)
from jarvis.app.security import AuthSecurityError, InvalidCredentialsError
from jarvis.app.services.auth_service import AuthService, AuthTokenResult
from jarvis.db.models import User

router = APIRouter()


def _user_response(user: User) -> AuthUserResponse:
    return AuthUserResponse(
        id=int(user.id),
        username=user.username,
        email=user.email,
        is_admin=is_admin_user(user),
        created_at=user.created_at,
        last_active_at=user.last_active_at,
    )


def _token_response(result: AuthTokenResult) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=_user_response(result.user),
    )


@router.post("/register", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: AuthRegisterRequest,
    session: Session = Depends(get_db),
) -> AuthTokenResponse:
    try:
        result = AuthService().register_user(session, request)
        session.commit()
        return _token_response(result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AuthSecurityError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/login", response_model=AuthTokenResponse)
def login(
    request: AuthLoginRequest,
    session: Session = Depends(get_db),
) -> AuthTokenResponse:
    try:
        result = AuthService().login_user(session, request)
        session.commit()
        return _token_response(result)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except AuthSecurityError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/me", response_model=AuthUserResponse)
def me(user: User = Depends(get_current_user)) -> AuthUserResponse:
    return _user_response(user)


@router.post("/logout", response_model=AuthLogoutResponse)
def logout(_user: User = Depends(get_current_user)) -> AuthLogoutResponse:
    """Frontend-friendly logout endpoint for stateless JWT sessions."""
    return AuthLogoutResponse()
