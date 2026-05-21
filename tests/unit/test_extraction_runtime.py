import pytest

from jarvis.ingestion import extraction


def test_ensure_lxml_available_passes_when_dependency_exists(monkeypatch) -> None:
    monkeypatch.setattr(extraction, "find_spec", lambda name: object() if name == "lxml" else None)

    extraction.ensure_lxml_available()


def test_ensure_lxml_available_fails_fast_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(extraction, "find_spec", lambda name: None)

    with pytest.raises(RuntimeError, match="requires lxml"):
        extraction.ensure_lxml_available()
