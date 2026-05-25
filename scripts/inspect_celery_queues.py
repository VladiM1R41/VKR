"""Inspect Redis-backed Celery queues used by the project."""

from __future__ import annotations

import argparse
import base64
import json
from typing import Any

from redis import Redis

from jarvis.core.settings import get_settings


DEFAULT_QUEUES = (
    "collector_queue",
    "enrichment_queue",
    "processing_queue",
    "analytics_queue",
    "generation_queue",
)


def _decode_message(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
        headers = payload.get("headers") or {}
        body = json.loads(base64.b64decode(payload.get("body") or "").decode("utf-8"))
        return {
            "task": headers.get("task"),
            "id": headers.get("id"),
            "retries": headers.get("retries"),
            "args": body[0] if isinstance(body, list) and body else None,
            "kwargs": body[1] if isinstance(body, list) and len(body) > 1 else None,
        }
    except Exception as exc:
        return {
            "decode_error": str(exc),
            "raw_preview": raw[:300],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Celery queue lengths and message previews.")
    parser.add_argument("--queue", action="append", choices=DEFAULT_QUEUES, help="Queue to inspect. Repeatable.")
    parser.add_argument("--limit", type=int, default=5, help="Preview message count per queue.")
    args = parser.parse_args()

    queues = tuple(args.queue or DEFAULT_QUEUES)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)

    result = {}
    for queue in queues:
        messages = redis.lrange(queue, 0, max(args.limit - 1, 0))
        result[queue] = {
            "length": redis.llen(queue),
            "preview": [_decode_message(message) for message in messages],
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
