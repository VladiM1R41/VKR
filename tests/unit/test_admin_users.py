from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException

from jarvis.app.api.v1.admin import update_user
from jarvis.app.schemas.admin import AdminUserUpdateRequest
from jarvis.db.models import User


class FakeSession:
    def __init__(self, users: list[User], *, admin_count: int) -> None:
        self.users = {int(user.id): user for user in users}
        self.admin_count = admin_count
        self.flush_count = 0

    def get(self, model: type, key: int) -> User | None:
        if model is not User:
            return None
        return self.users.get(int(key))

    def scalar(self, _statement: object) -> int:
        return self.admin_count

    def flush(self) -> None:
        self.flush_count += 1


def _user(user_id: int, *, is_admin: bool) -> User:
    return User(
        id=user_id,
        username=f"user-{user_id}",
        email=f"user-{user_id}@example.com",
        is_admin=is_admin,
        settings={},
        created_at=datetime(2026, 5, 30),
    )


def test_update_user_can_promote_regular_user() -> None:
    admin = _user(1, is_admin=True)
    target = _user(2, is_admin=False)
    session = FakeSession([admin, target], admin_count=1)

    response = update_user(
        2,
        AdminUserUpdateRequest(is_admin=True),
        session=session,  # type: ignore[arg-type]
        current_user=admin,
    )

    assert response.is_admin is True
    assert target.is_admin is True
    assert session.flush_count == 1


def test_update_user_prevents_self_demotion() -> None:
    admin = _user(1, is_admin=True)
    session = FakeSession([admin], admin_count=1)

    with pytest.raises(HTTPException) as exc:
        update_user(
            1,
            AdminUserUpdateRequest(is_admin=False),
            session=session,  # type: ignore[arg-type]
            current_user=admin,
        )

    assert exc.value.status_code == 400


def test_update_user_prevents_last_admin_removal() -> None:
    admin = _user(1, is_admin=True)
    target = _user(2, is_admin=True)
    session = FakeSession([admin, target], admin_count=1)

    with pytest.raises(HTTPException) as exc:
        update_user(
            2,
            AdminUserUpdateRequest(is_admin=False),
            session=session,  # type: ignore[arg-type]
            current_user=admin,
        )

    assert exc.value.status_code == 400
