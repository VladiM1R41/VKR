from __future__ import annotations

from datetime import datetime
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from jarvis.app.dependencies import DEFAULT_USER_ID, get_db
from jarvis.app.main import app
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


def _override_db(session: FakeSession):
    def _dependency() -> Iterator[FakeSession]:
        yield session

    return _dependency


@pytest.fixture(autouse=True)
def clear_dependency_overrides() -> Iterator[None]:
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.openapi_schema = None


def test_me_returns_default_user_without_token_in_single_user_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: _settings(AUTH_MODE="single_user"))
    app.dependency_overrides[get_db] = _override_db(FakeSession([_user(DEFAULT_USER_ID)]))

    response = TestClient(app).get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == DEFAULT_USER_ID
    assert response.json()["is_admin"] is True


def test_me_requires_token_in_jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: _settings())
    app.dependency_overrides[get_db] = _override_db(FakeSession([_user(7)]))

    response = TestClient(app).get("/api/v1/auth/me")

    assert response.status_code == 401


def test_me_accepts_bearer_token_in_jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: settings)
    app.dependency_overrides[get_db] = _override_db(FakeSession([_user(7)]))
    token = create_access_token(7, settings=settings)

    response = TestClient(app).get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["id"] == 7
    assert response.json()["is_admin"] is False


def test_logout_accepts_bearer_token_in_jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: settings)
    app.dependency_overrides[get_db] = _override_db(FakeSession([_user(7)]))
    token = create_access_token(7, settings=settings)

    response = TestClient(app).post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"logged_out": True}


def test_admin_requires_token_in_jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: _settings())
    app.dependency_overrides[get_db] = _override_db(FakeSession([_user(7)]))

    response = TestClient(app).get("/api/v1/admin/overview")

    assert response.status_code == 401


def test_admin_rejects_non_admin_in_jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: settings)
    monkeypatch.setattr("jarvis.app.api.v1.admin.get_settings", lambda: settings)
    app.dependency_overrides[get_db] = _override_db(FakeSession([_user(7, is_admin=False)]))
    token = create_access_token(7, settings=settings)

    response = TestClient(app).get("/api/v1/admin/settings", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_admin_accepts_admin_in_jwt_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr("jarvis.app.dependencies.get_settings", lambda: settings)
    monkeypatch.setattr("jarvis.app.api.v1.admin.get_settings", lambda: settings)
    app.dependency_overrides[get_db] = _override_db(FakeSession([_user(7, is_admin=True)]))
    token = create_access_token(7, settings=settings)

    response = TestClient(app).get("/api/v1/admin/settings", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["auth"]["mode"] == "jwt"
