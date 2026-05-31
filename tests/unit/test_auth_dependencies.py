from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from jarvis.app.dependencies import (
    DEFAULT_USER_ID,
    get_current_user,
    get_current_user_id,
    is_admin_user,
    require_admin_user,
    resolve_current_user_id,
)
from jarvis.app.security import create_access_token
from jarvis.core.settings import Settings
from jarvis.db.models import User


class FakeSession:
    def __init__(self, users: list[User]) -> None:
        self.users = {int(user.id): user for user in users}

    def get(self, model: type, key: int) -> User | None:
        if model is not User:
            return None
        return self.users.get(int(key))


def _user(user_id: int = DEFAULT_USER_ID, *, is_admin: bool = False) -> User:
    return User(
        id=user_id,
        username=f"user-{user_id}",
        email=f"user-{user_id}@example.com",
        is_admin=is_admin,
        settings={},
        created_at=datetime(2026, 5, 29),
    )


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "AUTH_MODE": "jwt",
        "JWT_SECRET_KEY": "x" * 32,
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def test_get_current_user_returns_default_user_in_single_user_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: _settings(AUTH_MODE="single_user"))
    session = FakeSession([_user(DEFAULT_USER_ID)])

    user = get_current_user(session=session, credentials=None)

    assert user.id == DEFAULT_USER_ID


def test_single_user_mode_treats_default_user_as_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: _settings(AUTH_MODE="single_user"))

    assert is_admin_user(_user(DEFAULT_USER_ID, is_admin=False)) is True


def test_require_admin_user_rejects_non_admin_in_jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: _settings())

    with pytest.raises(HTTPException) as exc:
        require_admin_user(_user(7, is_admin=False))

    assert exc.value.status_code == 403


def test_require_admin_user_accepts_admin_in_jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: _settings())

    user = require_admin_user(_user(7, is_admin=True))

    assert user.id == 7


def test_get_current_user_id_wraps_current_user() -> None:
    assert get_current_user_id(_user(7)) == 7


def test_get_current_user_requires_token_in_jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: _settings())
    session = FakeSession([_user(7)])

    with pytest.raises(HTTPException) as exc:
        get_current_user(session=session, credentials=None)

    assert exc.value.status_code == 401


def test_get_current_user_accepts_valid_token_in_jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: settings)
    session = FakeSession([_user(7)])
    token = create_access_token(7, settings=settings)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = get_current_user(session=session, credentials=credentials)

    assert user.id == 7


def test_resolve_current_user_id_accepts_token_in_direct_context(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: settings)
    session = FakeSession([_user(8)])
    token = create_access_token(8, settings=settings)

    assert resolve_current_user_id(session, token=token) == 8


def test_get_current_user_rejects_token_for_missing_user(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: settings)
    session = FakeSession([])
    token = create_access_token(7, settings=settings)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc:
        get_current_user(session=session, credentials=credentials)

    assert exc.value.status_code == 401
