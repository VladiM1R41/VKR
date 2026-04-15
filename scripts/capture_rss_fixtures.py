"""Capture point-in-time RSS snapshots for all MVP sources."""

from __future__ import annotations

from pathlib import Path

import httpx

from jarvis.ingestion.bootstrap.source_seed_data import SOURCE_SEED_DATA


USER_AGENT = "JarvisLayer1/0.1 (+research project; fixtures capture)"
FIXTURES_DIR = Path("tests/fixtures/rss")


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    rows = [row for row in SOURCE_SEED_DATA if row["type"] == "rss"]

    with httpx.Client(follow_redirects=True, timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
        for row in rows:
            source_key = row["config"]["source_key"]
            feed_url = row["config"]["feed_url"]
            target = FIXTURES_DIR / f"{source_key}_sample.xml"

            response = client.get(feed_url)
            response.raise_for_status()
            target.write_bytes(response.content)
            print(
                f"{source_key:20} -> {response.status_code} "
                f"{len(response.content):8d} bytes -> {target.as_posix()}"
            )


if __name__ == "__main__":
    main()
