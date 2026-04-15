"""Tests for Layer 3 search logging service."""

from jarvis.db.models.search_log import SearchLog
from jarvis.db.models.search_result import SearchResult as SearchResultRow
from jarvis.retrieval.services.search_logger import SearchLogger


class _FakeSession:
    def __init__(self, scalar_result=None):
        self.scalar_result = scalar_result
        self.added = []
        self.flushed = False
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed = True
        for obj in self.added:
            if isinstance(obj, SearchLog) and getattr(obj, "id", None) is None:
                obj.id = 123

    def scalar(self, stmt):
        return self.scalar_result

    def commit(self):
        self.committed = True


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        return False


def test_log_search_persists_search_and_ranked_rows(monkeypatch) -> None:
    session = _FakeSession()
    monkeypatch.setattr(
        "jarvis.retrieval.services.search_logger.SyncSessionLocal",
        lambda: _FakeSessionContext(session),
    )

    logger = SearchLogger()
    logger.log_search(
        query_text="ключевая ставка",
        resolved_query="ключевая ставка цб",
        intent="FACTUAL",
        num_results=2,
        retrieval_time_ms=41,
        top_result_ids=[11, 22],
    )

    assert session.flushed is True
    assert session.committed is True

    search_logs = [obj for obj in session.added if isinstance(obj, SearchLog)]
    result_rows = [obj for obj in session.added if isinstance(obj, SearchResultRow)]

    assert len(search_logs) == 1
    assert search_logs[0].resolved_query == "ключевая ставка цб"
    assert len(result_rows) == 2
    assert [row.rank_position for row in result_rows] == [1, 2]
    assert [row.news_id for row in result_rows] == [11, 22]


def test_log_click_updates_existing_result(monkeypatch) -> None:
    existing = SearchResultRow(search_id=55, news_id=77, was_clicked=False)
    session = _FakeSession(scalar_result=existing)
    monkeypatch.setattr(
        "jarvis.retrieval.services.search_logger.SyncSessionLocal",
        lambda: _FakeSessionContext(session),
    )

    logger = SearchLogger()
    logger.log_click(search_id=55, news_id=77, dwell_time_sec=12.5)

    assert session.committed is True
    assert existing.was_clicked is True
    assert existing.dwell_time_sec == 12.5
