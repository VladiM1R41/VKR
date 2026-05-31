from __future__ import annotations

from typing import Any

import pytest

from jarvis.app.schemas.auth import AuthLoginRequest, AuthRegisterRequest
from jarvis.app.security import InvalidCredentialsError, TokenValidationError, verify_password
from jarvis.app.services.auth_service import AuthService
from jarvis.core.settings import Settings
from jarvis.db.models import User


class FakeSession:
    def __init__(self) -> None:
        self.users: list[User] = []
        self._next_id = 1
        self.flush_count = 0

    def add(self, value: Any) -> None:
        if isinstance(value, User):
            if value.id is None:
                value.id = self._next_id
                self._next_id += 1
            else:
                self._next_id = max(self._next_id, int(value.id) + 1)
            self.users.append(value)

    def flush(self) -> None:
        self.flush_count += 1

    def get(self, model: type, key: int) -> User | None:
        if model is not User:
            return None
        return next((user for user in self.users if user.id == key), None)

    def scalar(self, _statement: Any) -> int | None:
        return next(
            (
                int(user.id)
                for user in self.users
                if user.is_admin and user.password_hash is not None
            ),
            None,
        )


class FakeAuthService(AuthService):
    def _find_user_by_username_or_email(
        self,
        session: FakeSession,
        *,
        username: str,
        email: str | None,
    ) -> User | None:
        username_key = username.lower()
        email_key = email.lower() if email else None
        return next(
            (
                user
                for user in session.users
                if user.username.lower() == username_key or (email_key and user.email and user.email.lower() == email_key)
            ),
            None,
        )

    def _find_user_by_login(self, session: FakeSession, login: str) -> User | None:
        login_key = login.strip().lower()
        return next(
            (
                user
                for user in session.users
                if user.username.lower() == login_key or (user.email and user.email.lower() == login_key)
            ),
            None,
        )


def _settings() -> Settings:
    return Settings(_env_file=None, AUTH_MODE="jwt", JWT_SECRET_KEY="x" * 32)


def test_register_user_hashes_password_and_issues_token() -> None:
    session = FakeSession()
    service = FakeAuthService()

    result = service.register_user(
        session,
        AuthRegisterRequest(username="alice", email="Alice@Example.com", password="correct-horse"),
        settings=_settings(),
    )

    assert result.user.id == 1
    assert result.user.email == "alice@example.com"
    assert result.user.is_admin is True
    assert result.user.password_hash != "correct-horse"
    assert verify_password("correct-horse", result.user.password_hash)
    assert result.payload.user_id == 1
    assert result.access_token
    assert result.expires_in == 120 * 60


def test_register_user_makes_only_first_admin() -> None:
    session = FakeSession()
    service = FakeAuthService()

    first = service.register_user(
        session,
        AuthRegisterRequest(username="alice", email=None, password="correct-horse"),
        settings=_settings(),
    )
    second = service.register_user(
        session,
        AuthRegisterRequest(username="bob", email=None, password="correct-horse"),
        settings=_settings(),
    )

    assert first.user.is_admin is True
    assert second.user.is_admin is False


def test_register_user_ignores_passwordless_default_admin_for_owner_selection() -> None:
    session = FakeSession()
    session.add(
        User(
            id=1,
            username="jarvis-user",
            email="user@jarvis.local",
            is_admin=True,
            password_hash=None,
            settings={},
        )
    )
    service = FakeAuthService()

    result = service.register_user(
        session,
        AuthRegisterRequest(username="alice", email=None, password="correct-horse"),
        settings=_settings(),
    )

    assert result.user.id == 2
    assert result.user.is_admin is True


def test_register_user_rejects_duplicate_username_or_email() -> None:
    session = FakeSession()
    service = FakeAuthService()
    request = AuthRegisterRequest(username="alice", email="alice@example.com", password="correct-horse")

    service.register_user(session, request, settings=_settings())

    with pytest.raises(ValueError, match="already exists"):
        service.register_user(
            session,
            AuthRegisterRequest(username="ALICE", email="other@example.com", password="correct-horse"),
            settings=_settings(),
        )


def test_login_user_accepts_username_or_email_and_updates_activity() -> None:
    session = FakeSession()
    service = FakeAuthService()
    service.register_user(
        session,
        AuthRegisterRequest(username="alice", email="alice@example.com", password="correct-horse"),
        settings=_settings(),
    )
    session.users[0].last_active_at = None

    result = service.login_user(
        session,
        AuthLoginRequest(login="alice@example.com", password="correct-horse"),
        settings=_settings(),
    )

    assert result.user.id == 1
    assert result.user.last_active_at is not None
    assert result.payload.user_id == 1


def test_login_user_rejects_wrong_password() -> None:
    session = FakeSession()
    service = FakeAuthService()
    service.register_user(
        session,
        AuthRegisterRequest(username="alice", email=None, password="correct-horse"),
        settings=_settings(),
    )

    with pytest.raises(InvalidCredentialsError):
        service.login_user(
            session,
            AuthLoginRequest(login="alice", password="wrong-password"),
            settings=_settings(),
        )


def test_get_user_from_token_rejects_missing_user() -> None:
    session = FakeSession()
    service = FakeAuthService()
    result = service.register_user(
        session,
        AuthRegisterRequest(username="alice", email=None, password="correct-horse"),
        settings=_settings(),
    )
    session.users.clear()

    with pytest.raises(TokenValidationError, match="does not exist"):
        service.get_user_from_token(session, result.access_token, settings=_settings())
