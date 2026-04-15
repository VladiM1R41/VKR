import json
import logging
from pathlib import Path
from uuid import uuid4

from jarvis.core import logging as project_logging


def test_json_formatter_renders_structured_record() -> None:
    formatter = project_logging.JsonFormatter()
    record = logging.LogRecord(
        name="jarvis.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="source_run_completed",
        args=(),
        exc_info=None,
    )
    record.event_name = "source_run_completed"
    record.source_id = 13
    record.source_name = "BFM.ru"
    record.run_id = 99

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "source_run_completed"
    assert payload["level"] == "INFO"
    assert payload["source_id"] == 13
    assert payload["source_name"] == "BFM.ru"
    assert payload["run_id"] == 99


def test_configure_logging_creates_rotating_log_file(monkeypatch) -> None:
    tmp_path = Path("tests") / f".tmp_logging_{uuid4().hex}"
    for handler in logging.getLogger().handlers[:]:
        handler.close()
        logging.getLogger().removeHandler(handler)
    tmp_path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("APP_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("APP_LOG_JSON", "true")
    monkeypatch.setenv("APP_LOG_LEVEL", "INFO")
    project_logging._LOGGING_CONFIGURED = False
    project_logging.get_settings.cache_clear()

    project_logging.configure_logging()
    project_logging.log_event(logging.getLogger("jarvis.test"), logging.INFO, "test_event", source_id=1)

    log_file = tmp_path / "collector.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "test_event" in content
    assert "\"source_id\": 1" in content

    for handler in logging.getLogger().handlers[:]:
        handler.close()
        logging.getLogger().removeHandler(handler)
    project_logging.get_settings.cache_clear()
    project_logging._LOGGING_CONFIGURED = False
