"""FastAPI dependency injection для Layer 6.

Single-user режим: все запросы приходят от пользователя с id=DEFAULT_USER_ID.
Функция seed_default_user() вызывается при старте приложения (lifespan).
"""

from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy.orm import Session

from jarvis.db.models import User
from jarvis.db.session import SyncSessionLocal

logger = logging.getLogger(__name__)

DEFAULT_USER_ID: int = 1


def get_db() -> Generator[Session, None, None]:
    """Dependency: синхронная сессия PostgreSQL."""
    with SyncSessionLocal() as session:
        yield session


def get_default_user_id() -> int:
    """Dependency: id единственного пользователя в single-user режиме."""
    return DEFAULT_USER_ID


def seed_default_user() -> None:
    """Гарантирует существование пользователя с id=DEFAULT_USER_ID.

    Вызывается в lifespan при старте приложения.
    """
    with SyncSessionLocal() as session:
        user = session.get(User, DEFAULT_USER_ID)
        if user is None:
            user = User(
                username="jarvis-user",
                email="user@jarvis.local",
                settings={},
            )
            session.add(user)
            session.commit()
            logger.info("Создан пользователь по умолчанию user_id=%s", DEFAULT_USER_ID)
        else:
            logger.info("Пользователь по умолчанию user_id=%s уже существует", DEFAULT_USER_ID)
