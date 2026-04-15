from jarvis.processing.services import entity_extraction


def test_extract_entities_returns_empty_when_runtime_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(entity_extraction, "_runtime_with_tagger", lambda: None)

    assert entity_extraction.extract_entities("Some article text") == []
