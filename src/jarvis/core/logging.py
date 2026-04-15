"""Structured logging bootstrap for Layer 1."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from jarvis.core.settings import get_settings


_LOGGING_CONFIGURED = False

_RESERVED_LOG_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    """Serialize records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "event": getattr(record, "event_name", record.getMessage()),
            "logger": record.name,
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_FIELDS or key.startswith("_") or key == "event_name":
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timestamp = super().formatTime(record, datefmt or "%Y-%m-%dT%H:%M:%S")
        return f"{timestamp}Z"


class ConsoleFormatter(logging.Formatter):
    """Readable local formatter when JSON console logs are disabled."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event_name", record.getMessage())
        base = f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S')}Z {record.levelname} {event}"
        extras: list[str] = []
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_FIELDS or key.startswith("_") or key == "event_name":
                continue
            extras.append(f"{key}={value}")
        if extras:
            return f"{base} " + " ".join(extras)
        return base


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Emit one structured log event."""

    logger.log(level, event, extra={"event_name": event, **fields})


def configure_logging() -> None:
    """Configure root logging once for CLI, workers and beat."""

    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    settings = get_settings()
    log_level_name = str(settings.app_log_level).upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    log_dir = Path(settings.app_log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "collector.log"

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(JsonFormatter())

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    if settings.app_log_json:
        console_handler.setFormatter(JsonFormatter())
    else:
        console_handler.setFormatter(ConsoleFormatter())

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    _LOGGING_CONFIGURED = True
