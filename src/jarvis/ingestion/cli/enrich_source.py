"""CLI entrypoint for HTML enrichment of pending articles."""

from __future__ import annotations

import argparse
import json

from jarvis.core.logging import configure_logging
from jarvis.ingestion.services.enrich_source import run_enrich_source_pending


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enrich pending HTML articles for one source.")
    parser.add_argument("--source", required=True, help="Exact source name from the sources table.")
    parser.add_argument("--limit", type=int, default=10, help="How many pending articles to enrich.")
    return parser


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    result = run_enrich_source_pending(source_name=args.source, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
