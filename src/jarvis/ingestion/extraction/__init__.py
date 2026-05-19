"""Extraction helpers for HTML and RSS full-text pipelines."""

from __future__ import annotations

from importlib.util import find_spec


def ensure_lxml_available() -> None:
    """Fail fast when the XML parser required by RSS collection is missing."""
    if find_spec("lxml") is None:
        raise RuntimeError(
            "Layer 1 RSS parsing requires lxml. Install the project requirements "
            "before running ingestion."
        )
