"""FastAPI dependencies for the Layer 6 web/API shell."""

from __future__ import annotations

import logging
from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from jarvis.app.security import AuthSecurityError, TokenValidationError
from jarvis.app.services.auth_service import AuthService
from jarvis.core.settings import get_settings
from jarvis.db.models import User
from jarvis.db.session import SyncSessionLocal

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = 1
bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """Provide a request-scoped SQLAlchemy session with a transaction boundary."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def resolve_current_user(session: Session, *, token: str | None = None) -> User:
    """Return the current user according to AUTH_MODE.

    AUTH_MODE=single_user preserves the original MVP behavior and always returns
    user_id=1. AUTH_MODE=jwt requires a Bearer access token.
    """
    settings = get_settings()
    if settings.auth_mode == "single_user":
        user = session.get(User, DEFAULT_USER_ID)
        if user is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Default user is not available.")
        return user

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization bearer token is required.")

    try:
        return AuthService().get_user_from_token(session, token, settings=settings)
    except TokenValidationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except AuthSecurityError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


def resolve_current_user_id(session: Session, *, token: str | None = None) -> int:
    """Resolve current user id for non-HTTP dependency contexts such as WebSocket handlers."""
    return int(resolve_current_user(session, token=token).id)


def get_current_user(
    session: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    """FastAPI dependency wrapper around current user resolution."""
    token = credentials.credentials if credentials is not None else None
    return resolve_current_user(session, token=token)


def get_current_user_id(user: User = Depends(get_current_user)) -> int:
    """Compatibility hook for existing endpoints that only need user_id."""
    return int(user.id)


def is_admin_user(user: User) -> bool:
    """Return whether the user may access admin-only API in the active auth mode."""
    if get_settings().auth_mode == "single_user":
        return True
    return bool(user.is_admin)


def require_admin_user(user: User = Depends(get_current_user)) -> User:
    """Require admin privileges while preserving single-user MVP compatibility."""
    if not is_admin_user(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges are required.")
    return user


def seed_default_user() -> None:
    """Create the default MVP user if Postgres is reachable."""
    try:
        with SyncSessionLocal() as session:
            user = session.get(User, DEFAULT_USER_ID)
            if user is None:
                session.add(
                    User(
                        id=DEFAULT_USER_ID,
                        username="jarvis-user",
                        email="user@jarvis.local",
                        is_admin=True,
                        settings={
                            "diversity_slider": 0.3,
                            "notify_channels": ["web"],
                        },
                    )
                )
                session.commit()
            elif not user.is_admin:
                user.is_admin = True
                session.commit()
    except SQLAlchemyError as exc:
        logger.warning("default_user_seed_skipped: %s", exc)
