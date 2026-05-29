from jarvis.processing.services import entity_extraction
from jarvis.processing.services.entity_extraction import ExtractedEntity


def test_extract_entities_returns_empty_when_runtime_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(entity_extraction, "_runtime_with_tagger", lambda: None)

    assert entity_extraction.extract_entities("Some article text") == []


def test_entity_aliases_are_aggregated(monkeypatch) -> None:
    class FakeSpan:
        def __init__(self, text: str, span_type: str, normal: str) -> None:
            self.text = text
            self.type = span_type
            self.normal = normal

        def normalize(self, morph_vocab) -> None:
            return None

    class FakeDoc:
        def __init__(self, text: str) -> None:
            self.spans = [
                FakeSpan("ЦБ", "ORG", "ЦБ"),
                FakeSpan("Банк России", "ORG", "Банк России"),
                FakeSpan("Центробанк", "ORG", "Центробанк"),
                FakeSpan("Минфин", "ORG", "Минфин"),
                FakeSpan("Министерство финансов", "ORG", "Министерство финансов"),
            ]

        def segment(self, segmenter) -> None:
            return None

        def tag_ner(self, ner_tagger) -> None:
            return None

    monkeypatch.setattr(
        entity_extraction,
        "_runtime_with_tagger",
        lambda: {
            "Doc": FakeDoc,
            "morph_vocab": object(),
            "ner_tagger": object(),
            "segmenter": object(),
        },
    )

    assert entity_extraction.extract_entities("ignored") == [
        ExtractedEntity(
            name="Банк России",
            normalized_name="Банк России",
            entity_type="organization",
            mention_count=3,
        ),
        ExtractedEntity(
            name="Министерство финансов России",
            normalized_name="Министерство финансов России",
            entity_type="organization",
            mention_count=2,
        ),
    ]


def test_common_entity_aliases_normalize_cases_and_last_names(monkeypatch) -> None:
    class FakeSpan:
        def __init__(self, text: str, span_type: str, normal: str) -> None:
            self.text = text
            self.type = span_type
            self.normal = normal

        def normalize(self, morph_vocab) -> None:
            return None

    class FakeDoc:
        def __init__(self, text: str) -> None:
            self.spans = [
                FakeSpan("России", "LOC", "России"),
                FakeSpan("РФ", "LOC", "РФ"),
                FakeSpan("Трамп", "PER", "Трамп"),
                FakeSpan("Дональд Трамп", "PER", "Дональд Трамп"),
                FakeSpan("Израиля", "LOC", "Израиля"),
            ]

        def segment(self, segmenter) -> None:
            return None

        def tag_ner(self, ner_tagger) -> None:
            return None

    monkeypatch.setattr(
        entity_extraction,
        "_runtime_with_tagger",
        lambda: {
            "Doc": FakeDoc,
            "morph_vocab": object(),
            "ner_tagger": object(),
            "segmenter": object(),
        },
    )

    assert entity_extraction.extract_entities("ignored") == [
        ExtractedEntity(
            name="Россия",
            normalized_name="Россия",
            entity_type="location",
            mention_count=2,
        ),
        ExtractedEntity(
            name="Дональд Трамп",
            normalized_name="Дональд Трамп",
            entity_type="person",
            mention_count=2,
        ),
        ExtractedEntity(
            name="Израиль",
            normalized_name="Израиль",
            entity_type="location",
            mention_count=1,
        ),
    ]
