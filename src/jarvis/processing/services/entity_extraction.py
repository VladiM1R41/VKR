"""Named entity extraction for Layer 2."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging

from jarvis.core.logging import log_event


logger = logging.getLogger(__name__)
_DEPENDENCY_WARNING_EMITTED = False


@dataclass(frozen=True, slots=True)
class ExtractedEntity:
    """One normalized entity mention aggregated within an article."""

    name: str
    normalized_name: str
    entity_type: str
    mention_count: int


@lru_cache(maxsize=1)
def _load_natasha_runtime():
    from natasha import Doc, MorphVocab, NewsEmbedding, NewsNERTagger, Segmenter

    return {
        "Doc": Doc,
        "morph_vocab": MorphVocab(),
        "ner_tagger": NewsNERTagger(NewsEmbedding()),
        "segmenter": Segmenter(),
    }


def _runtime_with_tagger() -> dict[str, object] | None:
    global _DEPENDENCY_WARNING_EMITTED

    try:
        runtime = _load_natasha_runtime()
    except ImportError:
        if not _DEPENDENCY_WARNING_EMITTED:
            _DEPENDENCY_WARNING_EMITTED = True
            log_event(
                logger,
                logging.WARNING,
                "processing_entities_dependency_missing",
                dependency="natasha",
            )
        return None
    return runtime


def extract_entities(text: str) -> list[ExtractedEntity]:
    """Extract aggregated PER/ORG/LOC entities from article text."""

    normalized_text = " ".join(text.split())
    if not normalized_text:
        return []

    runtime = _runtime_with_tagger()
    if runtime is None:
        return []

    doc_cls = runtime["Doc"]
    morph_vocab = runtime["morph_vocab"]
    ner_tagger = runtime["ner_tagger"]
    segmenter = runtime["segmenter"]

    doc = doc_cls(normalized_text)
    doc.segment(segmenter)
    doc.tag_ner(ner_tagger)

    mention_counts: dict[tuple[str, str], int] = {}
    display_names: dict[tuple[str, str], str] = {}
    for span in doc.spans:
        if span.type not in {"PER", "ORG", "LOC"}:
            continue
        span.normalize(morph_vocab)
        normalized_name = (span.normal or span.text).strip()
        display_name = span.text.strip()
        if not normalized_name or not display_name:
            continue
        entity_type = {
            "PER": "person",
            "ORG": "organization",
            "LOC": "location",
        }[span.type]
        key = (normalized_name, entity_type)
        mention_counts[key] = mention_counts.get(key, 0) + 1
        display_names.setdefault(key, display_name)

    return [
        ExtractedEntity(
            name=display_names[(normalized_name, entity_type)],
            normalized_name=normalized_name,
            entity_type=entity_type,
            mention_count=mention_count,
        )
        for (normalized_name, entity_type), mention_count in mention_counts.items()
    ]
