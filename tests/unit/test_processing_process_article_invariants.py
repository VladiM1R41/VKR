"""Tests for Layer 2 article processing invariants."""

from types import SimpleNamespace

from jarvis.processing.services.process_article import (
    _build_chunk_payload,
    _deterministic_point_uuid,
)


def test_deterministic_point_uuid_is_stable() -> None:
    first = _deterministic_point_uuid(42, "body", 1)
    second = _deterministic_point_uuid(42, "body", 1)
    different = _deterministic_point_uuid(42, "body", 2)

    assert first == second
    assert first != different


def test_chunk_payload_contains_final_retrieval_signals() -> None:
    news = SimpleNamespace(
        id=42,
        source_id=7,
        title="Title",
        published_at=None,
        canonical_url="https://example.test/news",
        language="ru",
        information_type="regular",
        urgency="normal",
        content_grade=2,
        is_uncertain=False,
        event_cluster_id=40,
        snippet_lead="Lead",
    )
    chunk = SimpleNamespace(
        text="Chunk text",
        zone="body",
        chunk_index=1,
        total_chunks=2,
        lemma_text="chunk text",
    )

    payload = _build_chunk_payload(
        news,
        chunk,
        ["economy"],
        source_name="Source",
        trust_score=0.9,
        keyword_texts=["market"],
        entity_names=["Entity"],
        entity_ids=[1],
        value_score=0.7,
        freshness=0.8,
        completeness=1.0,
        cluster_support=0.66,
        nlp_enriched=True,
    )

    assert payload["content_grade"] == 2
    assert payload["is_uncertain"] is False
    assert payload["value_score"] == 0.7
    assert payload["freshness"] == 0.8
    assert payload["completeness"] == 1.0
    assert payload["cluster_support"] == 0.66
    assert payload["nlp_enriched"] is True
