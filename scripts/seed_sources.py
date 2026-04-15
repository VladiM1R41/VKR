"""Seed the MVP sources registry."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jarvis.db.models import Source
from jarvis.db.session import SyncSessionLocal
from jarvis.ingestion.bootstrap.source_seed_data import SOURCE_SEED_DATA


def main() -> None:
    with SyncSessionLocal() as session:
        for payload in SOURCE_SEED_DATA:
            existing = session.scalar(select(Source).where(Source.name == payload["name"]))
            if existing:
                for key, value in payload.items():
                    setattr(existing, key, value)
            else:
                session.add(Source(**payload))
        session.commit()
    print(f"Seeded {len(SOURCE_SEED_DATA)} sources.")


if __name__ == "__main__":
    main()
