from __future__ import annotations

from jarvis.generation.services.context_assembler import (
    NewsWithContext,
    assemble_context_for_chat,
    group_by_event_clusters,
    trim_documents_to_budget,
)
from jarvis.generation.services.prompt_builder import DocumentContext, estimate_token_count


def _item(
    news_id: int,
    *,
    score: float = 0.8,
    personalized_score: float | None = None,
    trust_score: float = 0.5,
    published_at: str = "2026-05-01T10:00:00",
    urgency: str = "normal",
    cluster_id: int | None = None,
) -> NewsWithContext:
    return NewsWithContext(
        news_id=news_id,
        source_id=news_id,
        source_name=f"source-{news_id}",
        title=f"title-{news_id}",
        content=f"content-{news_id}",
        snippet_lead=None,
        score=score,
        rerank_score=None,
        personalized_score=personalized_score,
        published_at_str=published_at,
        trust_score=trust_score,
        urgency=urgency,
        event_cluster_id=cluster_id,
    )


def test_chat_context_prefers_trusted_source_when_relevance_ties() -> None:
    assembled = assemble_context_for_chat(
        [
            _item(1, score=0.9, trust_score=0.4),
            _item(2, score=0.9, trust_score=0.9),
        ],
        max_input_tokens=1000,
    )

    assert [doc.news_id for doc in assembled.documents] == [2, 1]


def test_chat_context_uses_freshness_then_urgency_as_tiebreakers() -> None:
    assembled = assemble_context_for_chat(
        [
            _item(1, score=0.9, trust_score=0.8, published_at="2026-05-01T10:00:00"),
            _item(2, score=0.9, trust_score=0.8, published_at="2026-05-02T10:00:00"),
            _item(3, score=0.9, trust_score=0.8, published_at="2026-05-01T10:00:00", urgency="high"),
        ],
        max_input_tokens=1000,
    )

    assert [doc.news_id for doc in assembled.documents] == [2, 3, 1]


def test_digest_cluster_representative_uses_same_priority_order() -> None:
    clusters = group_by_event_clusters(
        [
            _item(1, score=0.8, trust_score=0.3, cluster_id=10),
            _item(2, score=0.8, trust_score=0.9, cluster_id=10),
        ]
    )

    assert len(clusters) == 1
    assert clusters[0].representatives[0].news_id == 2
    assert [item.news_id for item in clusters[0].supporting] == [1]


def test_trimmed_document_stays_inside_remaining_budget() -> None:
    doc = DocumentContext(
        index=1,
        news_id=1,
        source_name="source",
        published_at="2026-05-02",
        title="title",
        content="а" * 200,
    )

    trimmed = trim_documents_to_budget(
        [doc],
        max_context_tokens=35,
        system_tokens=0,
        user_tokens=0,
    )

    assert len(trimmed) == 1
    assert trimmed[0].content.endswith("...")
    overhead = estimate_token_count("source: source date: 2026-05-02 title: title")
    assert estimate_token_count(trimmed[0].content) + overhead <= 35
