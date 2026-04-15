"""CLI command for the per-source health dashboard."""

from __future__ import annotations

import argparse
import json

from jarvis.core.logging import configure_logging
from jarvis.ingestion.services.monitoring import build_health_dashboard


def _format_table(rows: list[dict]) -> str:
    columns = [
        ("id", "id"),
        ("name", "source"),
        ("health_status", "health"),
        ("consecutive_failures", "fails"),
        ("parse_success", "parse"),
        ("extraction_success", "extract"),
        ("avg_latency_minutes", "latency_m"),
        ("source_utility", "utility"),
        ("latest_published_at", "latest_pub"),
        ("staleness_hours", "stale_h"),
        ("runs_24h", "runs24h"),
        ("items_new_24h", "new24h"),
        ("items_in_last_feed", "last_feed"),
    ]

    rendered_rows = []
    for row in rows:
        rendered = {label: "" if row.get(key) is None else str(row.get(key)) for key, label in columns}
        rendered_rows.append(rendered)

    widths = {
        label: max(len(label), *(len(rendered[label]) for rendered in rendered_rows)) if rendered_rows else len(label)
        for _, label in columns
    }

    header = " | ".join(label.ljust(widths[label]) for _, label in columns)
    separator = "-+-".join("-" * widths[label] for _, label in columns)
    body = [
        " | ".join(rendered[label].ljust(widths[label]) for _, label in columns)
        for rendered in rendered_rows
    ]
    return "\n".join([header, separator, *body])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show Layer 1 health dashboard per source.")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of a text table.")
    return parser


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    rows = build_health_dashboard()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return
    print(_format_table(rows))


if __name__ == "__main__":
    main()
