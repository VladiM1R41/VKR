"""Explicitly purge one Redis-backed Celery queue after inspection."""

from __future__ import annotations

import argparse
import json

from redis import Redis

from jarvis.core.settings import get_settings


DEFAULT_QUEUES = (
    "collector_queue",
    "enrichment_queue",
    "processing_queue",
    "analytics_queue",
    "generation_queue",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge a single Celery queue. Inspect first, purge second.")
    parser.add_argument("--queue", required=True, choices=DEFAULT_QUEUES)
    parser.add_argument("--yes", action="store_true", help="Actually delete the Redis queue key.")
    args = parser.parse_args()

    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    length = redis.llen(args.queue)
    if not args.yes:
        print(
            json.dumps(
                {
                    "queue": args.queue,
                    "length": length,
                    "purged": False,
                    "message": "Re-run with --yes to purge this queue.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    deleted = redis.delete(args.queue)
    print(
        json.dumps(
            {
                "queue": args.queue,
                "length_before": length,
                "redis_key_deleted": bool(deleted),
                "purged": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
