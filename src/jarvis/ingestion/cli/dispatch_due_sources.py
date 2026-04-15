"""CLI entrypoint for scheduler dry-runs and manual dispatch."""

from __future__ import annotations

import argparse
import json

from jarvis.core.logging import configure_logging
from jarvis.ingestion.services.scheduler import run_dispatch_due_sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dispatch due Layer 1 sources according to crawl schedule.")
    parser.add_argument("--source", help="Optional exact source name to evaluate.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show due sources, do not enqueue Celery tasks.",
    )
    return parser


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    result = run_dispatch_due_sources(source_name=args.source, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
