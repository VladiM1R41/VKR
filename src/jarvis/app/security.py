"""Password hashing and JWT helpers for Layer 6 authentication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jarvis.core.settings import Settings, get_settings


class AuthSecurityError(RuntimeError):
    """Base error for local authentication security helpers."""


class InvalidCredentialsError(AuthSecurityError):
    """Raised when a password or token cannot be verified."""


class TokenValidationError(AuthSecurityError):
    """Raised when an access token is invalid or expired."""


@dataclass(frozen=True, slots=True)
class AccessTokenPayload:
    """Validated JWT access token payload."""

    user_id: int
    issued_at: datetime
    expires_at: datetime


def _import_bcrypt():
    try:
        import bcrypt
    except ImportError as exc:
        raise AuthSecurityError("bcrypt is required for password hashing. Install project requirements.") from exc
    return bcrypt


def _import_jwt():
    try:
        import jwt
    except ImportError as exc:
        raise AuthSecurityError("PyJWT is required for token handling. Install project requirements.") from exc
    return jwt


def hash_password(password: str, *, settings: Settings | None = None) -> str:
    """Hash a plaintext password with bcrypt."""
    settings = settings or get_settings()
    if len(password) < settings.auth_password_min_length:
        raise InvalidCredentialsError(
            f"Password must contain at least {settings.auth_password_min_length} characters."
        )

    bcrypt = _import_bcrypt()
    password_bytes = password.encode("utf-8")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Return True when the plaintext password matches a stored bcrypt hash."""
    if not password_hash:
        return False

    bcrypt = _import_bcrypt()
    try:
        return bool(bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")))
    except ValueError:
        return False


def create_access_token(
    user_id: int,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token for a user."""
    settings = settings or get_settings()
    jwt = _import_jwt()

    issued_at = now or datetime.now(UTC)
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    expires_at = issued_at + (expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes))

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return str(jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm))


def decode_access_token(token: str, *, settings: Settings | None = None) -> AccessTokenPayload:
    """Validate a JWT access token and return its typed payload."""
    settings = settings or get_settings()
    jwt = _import_jwt()

    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenValidationError("Access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenValidationError("Access token is invalid.") from exc

    if payload.get("type") != "access":
        raise TokenValidationError("Token type is not access.")

    raw_user_id = payload.get("sub")
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError) as exc:
        raise TokenValidationError("Token subject is not a valid user id.") from exc

    issued_raw = payload.get("iat")
    expires_raw = payload.get("exp")
    if not isinstance(issued_raw, int) or not isinstance(expires_raw, int):
        raise TokenValidationError("Token timestamps are invalid.")

    return AccessTokenPayload(
        user_id=user_id,
        issued_at=datetime.fromtimestamp(issued_raw, UTC),
        expires_at=datetime.fromtimestamp(expires_raw, UTC),
    )
