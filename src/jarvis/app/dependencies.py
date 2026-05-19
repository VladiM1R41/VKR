"""FastAPI dependencies for the Layer 6 web/API shell."""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from jarvis.db.models import User
from jarvis.db.session import SyncSessionLocal

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = 1


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


def get_current_user_id() -> int:
    """Single-user MVP hook; keeps the API auth-ready for the future."""
    return DEFAULT_USER_ID


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
                        settings={
                            "diversity_slider": 0.3,
                            "notify_channels": ["web"],
                        },
                    )
                )
                session.commit()
    except SQLAlchemyError as exc:
        logger.warning("default_user_seed_skipped: %s", exc)

