from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.app.security import (
    InvalidCredentialsError,
    TokenValidationError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from jarvis.core.settings import Settings


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "AUTH_MODE": "jwt",
        "JWT_SECRET_KEY": "x" * 32,
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def test_hash_password_uses_bcrypt_and_verifies_password() -> None:
    password_hash = hash_password("correct-horse", settings=_settings())

    assert password_hash.startswith("$2")
    assert verify_password("correct-horse", password_hash) is True
    assert verify_password("wrong-password", password_hash) is False


def test_hash_password_rejects_short_password() -> None:
    with pytest.raises(InvalidCredentialsError, match="at least 8"):
        hash_password("short", settings=_settings())


def test_verify_password_handles_empty_or_malformed_hash() -> None:
    assert verify_password("password", None) is False
    assert verify_password("password", "not-a-bcrypt-hash") is False


def test_create_and_decode_access_token_roundtrip() -> None:
    settings = _settings()
    now = (datetime.now(UTC) - timedelta(minutes=1)).replace(microsecond=0)

    token = create_access_token(42, settings=settings, now=now, expires_delta=timedelta(minutes=30))
    payload = decode_access_token(token, settings=settings)

    assert payload.user_id == 42
    assert payload.issued_at == now
    assert payload.expires_at == now + timedelta(minutes=30)


def test_decode_access_token_rejects_wrong_secret() -> None:
    token = create_access_token(42, settings=_settings(JWT_SECRET_KEY="x" * 32))

    with pytest.raises(TokenValidationError, match="invalid"):
        decode_access_token(token, settings=_settings(JWT_SECRET_KEY="y" * 32))


def test_decode_access_token_rejects_expired_token() -> None:
    token = create_access_token(
        42,
        settings=_settings(),
        now=datetime(2020, 1, 1, tzinfo=UTC),
        expires_delta=timedelta(seconds=1),
    )

    with pytest.raises(TokenValidationError, match="expired"):
        decode_access_token(token, settings=_settings())
