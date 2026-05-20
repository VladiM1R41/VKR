from jarvis.ingestion.extraction import trafilatura_extractor as extractor


def test_extract_with_precision_passes_russian_target_language(monkeypatch) -> None:
    calls: list[dict] = []

    def _fake_extract(html, *, target_language=None, **kwargs):
        calls.append({"target_language": target_language, **kwargs})
        return "Текст статьи. " * 30

    extractor._supports_target_language.cache_clear()
    monkeypatch.setattr(extractor.trafilatura, "extract", _fake_extract)

    content = extractor.extract_with_precision("<html></html>")

    assert content is not None
    assert calls[0]["target_language"] == "ru"
    assert calls[0]["favor_precision"] is True


def test_extract_with_recall_keeps_compatibility_when_target_language_missing(monkeypatch) -> None:
    calls: list[dict] = []

    def _fake_extract(html, **kwargs):
        calls.append(kwargs)
        return "Текст. " * 30

    extractor._supports_target_language.cache_clear()
    monkeypatch.setattr(extractor.trafilatura, "extract", _fake_extract)

    content = extractor.extract_with_recall("<html></html>")

    assert content is not None
    assert "target_language" not in calls[0]
    assert calls[0]["favor_recall"] is True
