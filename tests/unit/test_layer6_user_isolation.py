from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from jarvis.app.api.v1.profile import update_preferences
from jarvis.app.api.v1.search import search_logs
from jarvis.db.models.search_log import SearchLog
from jarvis.personalization.models.preferences_models import ExplicitPreferencesUpdateRequest, UserProfilePatch


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _SearchLogSession:
    def __init__(self, rows: list[SearchLog]) -> None:
        self.rows = rows
        self.scalar_stmt = None
        self.scalars_stmt = None

    def scalar(self, stmt):
        self.scalar_stmt = stmt
        return len(self.rows)

    def scalars(self, stmt):
        self.scalars_stmt = stmt
        return _ScalarRows(self.rows)


def test_update_preferences_rejects_payload_user_id_mismatch() -> None:
    payload = ExplicitPreferencesUpdateRequest(profile=UserProfilePatch(user_id=99, username="mallory"))

    with pytest.raises(HTTPException) as exc:
        update_preferences(payload, session=Mock(), user_id=7)

    assert exc.value.status_code == 403


def test_search_logs_are_filtered_by_current_user() -> None:
    row = SearchLog(
        id=1,
        user_id=7,
        query_text="test",
        intent="FACTUAL",
        num_results=3,
        retrieval_time_ms=42,
        cache_hit=False,
        retrieval_mode="qdrant_hybrid",
        top_result_ids=[10, 11],
        created_at=datetime(2026, 5, 30, tzinfo=UTC),
    )
    session = _SearchLogSession([row])

    response = search_logs(session=session, user_id=7, limit=20, offset=0)

    assert response.total == 1
    assert response.items[0].id == 1
    assert response.items[0].top_result_ids == [10, 11]
    count_sql = str(session.scalar_stmt.compile(compile_kwargs={"literal_binds": True}))
    rows_sql = str(session.scalars_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "search_logs.user_id = 7" in count_sql
    assert "search_logs.user_id = 7" in rows_sql
