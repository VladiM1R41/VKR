"""CLI command for daily Layer 1 health check."""

from __future__ import annotations

import argparse
import json

from jarvis.core.logging import configure_logging
from jarvis.ingestion.services.monitoring import run_daily_health_check


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run daily Layer 1 health check and cleanup.")
    parser.add_argument("--dry-run", action="store_true", help="Compute report without deleting old rows.")
    return parser


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    result = run_daily_health_check(dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
