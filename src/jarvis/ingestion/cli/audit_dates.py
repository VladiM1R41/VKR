"""CLI command for publication-date audit."""

from __future__ import annotations

import json

from jarvis.core.logging import configure_logging
from jarvis.ingestion.services.monitoring import run_date_audit


def main() -> None:
    configure_logging()
    result = run_date_audit()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
