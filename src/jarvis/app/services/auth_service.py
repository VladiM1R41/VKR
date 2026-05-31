"""Authentication service for local username/password accounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from jarvis.app.schemas.auth import AuthLoginRequest, AuthRegisterRequest
from jarvis.app.security import (
    AccessTokenPayload,
    InvalidCredentialsError,
    TokenValidationError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from jarvis.core.settings import Settings, get_settings
from jarvis.db.models import User


@dataclass(frozen=True, slots=True)
class AuthTokenResult:
    user: User
    access_token: str
    payload: AccessTokenPayload

    @property
    def expires_in(self) -> int:
        return max(0, int((self.payload.expires_at - self.payload.issued_at).total_seconds()))


class AuthService:
    """Register users, authenticate credentials and validate access tokens."""

    def register_user(
        self,
        session: Session,
        request: AuthRegisterRequest,
        *,
        settings: Settings | None = None,
    ) -> AuthTokenResult:
        settings = settings or get_settings()
        username = request.username.strip()
        email = request.email.strip().lower() if request.email else None

        if self._find_user_by_username_or_email(session, username=username, email=email) is not None:
            raise ValueError("User with this username or email already exists.")

        now = datetime.now(UTC)
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(request.password, settings=settings),
            is_admin=self._should_make_new_user_admin(session),
            settings={
                "diversity_slider": 0.3,
                "notify_channels": ["web"],
            },
            created_at=now,
            last_active_at=now,
        )
        session.add(user)
        session.flush()
        return self._issue_token(user, settings=settings)

    def login_user(
        self,
        session: Session,
        request: AuthLoginRequest,
        *,
        settings: Settings | None = None,
    ) -> AuthTokenResult:
        settings = settings or get_settings()
        user = self._find_user_by_login(session, request.login)
        if user is None or not verify_password(request.password, user.password_hash):
            raise InvalidCredentialsError("Invalid username/email or password.")

        user.last_active_at = datetime.now(UTC)
        session.flush()
        return self._issue_token(user, settings=settings)

    def get_user_from_token(
        self,
        session: Session,
        token: str,
        *,
        settings: Settings | None = None,
    ) -> User:
        settings = settings or get_settings()
        payload = decode_access_token(token, settings=settings)
        user = session.get(User, payload.user_id)
        if user is None:
            raise TokenValidationError("Token user does not exist.")
        return user

    def _issue_token(self, user: User, *, settings: Settings) -> AuthTokenResult:
        if user.id is None:
            raise ValueError("Cannot issue token before user id is assigned.")
        access_token = create_access_token(int(user.id), settings=settings)
        payload = decode_access_token(access_token, settings=settings)
        return AuthTokenResult(user=user, access_token=access_token, payload=payload)

    def _find_user_by_username_or_email(
        self,
        session: Session,
        *,
        username: str,
        email: str | None,
    ) -> User | None:
        clauses = [func.lower(User.username) == username.lower()]
        if email:
            clauses.append(func.lower(User.email) == email.lower())
        return session.scalar(select(User).where(or_(*clauses)).limit(1))

    def _find_user_by_login(self, session: Session, login: str) -> User | None:
        normalized = login.strip().lower()
        return session.scalar(
            select(User)
            .where(or_(func.lower(User.username) == normalized, func.lower(User.email) == normalized))
            .limit(1)
        )

    def _should_make_new_user_admin(self, session: Session) -> bool:
        """Make the first JWT-capable installation owner an admin to avoid lockout."""
        return (
            session.scalar(
                select(User.id)
                .where(User.is_admin.is_(True), User.password_hash.is_not(None))
                .limit(1)
            )
            is None
        )
