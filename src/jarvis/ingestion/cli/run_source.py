"""CLI command to run a single source collection cycle."""

from __future__ import annotations

import argparse
import json

from jarvis.core.logging import configure_logging
from jarvis.ingestion.services.collect_source import run_collect_source


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run a single Layer 1 source collection cycle.")
    parser.add_argument("--source", required=True, help="Exact source name from the sources table.")
    args = parser.parse_args()

    result = run_collect_source(args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
