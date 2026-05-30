from __future__ import annotations

import pytest
from pydantic import ValidationError

from jarvis.core.settings import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_auth_settings_default_to_single_user_mode() -> None:
    settings = _settings()

    assert settings.auth_mode == "single_user"
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_access_token_expire_minutes == 120
    assert settings.auth_password_min_length == 8


def test_auth_settings_accept_jwt_mode_with_strong_secret() -> None:
    settings = _settings(
        AUTH_MODE="jwt",
        JWT_SECRET_KEY="x" * 32,
    )

    assert settings.auth_mode == "jwt"
    assert settings.jwt_secret_key == "x" * 32


def test_auth_settings_reject_unknown_auth_mode() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE"):
        _settings(AUTH_MODE="oauth")


def test_auth_settings_reject_weak_jwt_secret_when_jwt_enabled() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        _settings(AUTH_MODE="jwt", JWT_SECRET_KEY="short")


def test_auth_settings_reject_too_short_password_policy() -> None:
    with pytest.raises(ValidationError, match="AUTH_PASSWORD_MIN_LENGTH"):
        _settings(AUTH_PASSWORD_MIN_LENGTH=6)
