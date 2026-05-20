from __future__ import annotations

from jarvis.personalization.models.alert_models import AlertBatch, AlertCandidate
from jarvis.personalization.tasks import personalization_tasks


class ScalarRows:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def scalars(self, stmt):
        text = str(stmt)
        if "FROM news" in text:
            return ScalarRows([101, 102])
        if "FROM users" in text:
            return ScalarRows([1, 2])
        raise AssertionError(text)


class FakeAlertService:
    def __init__(self) -> None:
        self.marked_batches = 0

    def build_alert_batch(self, session, *, user_id: int, news_ids: list[int]) -> AlertBatch:
        return AlertBatch(
            user_id=user_id,
            alerts=[
                AlertCandidate(
                    user_id=user_id,
                    news_id=news_ids[0],
                    alert_type="alert_news",
                    title="t",
                    body="b",
                )
            ],
        )

    def mark_alerts_sent(self, batch: AlertBatch) -> int:
        self.marked_batches += 1
        return len(batch.alerts)


def test_build_alert_batch_task_marks_generated_alerts(monkeypatch) -> None:
    service = FakeAlertService()
    import jarvis.personalization.services.alert_service as alert_module

    monkeypatch.setattr(personalization_tasks, "SyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(alert_module, "AlertService", lambda: service)

    result = personalization_tasks.build_alert_batch_task.run(lookback_minutes=10, limit_users=2)

    assert result == {
        "users_processed": 2,
        "alerts_generated": 2,
        "alerts_marked_sent": 2,
    }
    assert service.marked_batches == 2
