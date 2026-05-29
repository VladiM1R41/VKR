from __future__ import annotations

from jarvis.generation.services.context_assembler import (
    NewsWithContext,
    assemble_context_for_digest,
    assemble_context_for_chat,
    group_by_event_clusters,
    trim_documents_to_budget,
)
from jarvis.generation.services.prompt_builder import DocumentContext, estimate_token_count
from jarvis.generation.services.prompt_builder import build_prompt


def _item(
    news_id: int,
    *,
    score: float = 0.8,
    personalized_score: float | None = None,
    trust_score: float = 0.5,
    published_at: str = "2026-05-01T10:00:00",
    urgency: str = "normal",
    cluster_id: int | None = None,
    content: str | None = None,
    snippet_lead: str | None = None,
    topics: list[str] | None = None,
    entities: list[str] | None = None,
) -> NewsWithContext:
    return NewsWithContext(
        news_id=news_id,
        source_id=news_id,
        source_name=f"source-{news_id}",
        title=f"title-{news_id}",
        content=content if content is not None else f"content-{news_id}",
        snippet_lead=snippet_lead,
        score=score,
        rerank_score=None,
        personalized_score=personalized_score,
        topics=topics if topics is not None else ["economy"],
        entities=entities if entities is not None else ["ЦБ"],
        published_at_str=published_at,
        trust_score=trust_score,
        urgency=urgency,
        event_cluster_id=cluster_id,
        url=f"https://example.test/{news_id}",
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
    assert assembled.documents[0].url == "https://example.test/2"


def test_prompt_context_contains_url_and_sources_instruction() -> None:
    assembled = assemble_context_for_chat([_item(1)], max_input_tokens=1000)
    prompt = build_prompt(
        mode="factual",
        user_query="Что произошло?",
        documents=assembled.documents,
    )

    assert "url: https://example.test/1" in prompt.context_block
    assert "Источники:" in prompt.user_prompt
    assert "[Doc N]" in prompt.user_prompt


def test_digest_prompt_requests_large_structured_overview() -> None:
    assembled = assemble_context_for_digest([_item(1), _item(2)], max_input_tokens=1000)
    prompt = build_prompt(
        mode="digest",
        user_query="Составь большой дайджест из 2 источников ниже.",
        documents=assembled.documents,
    )

    assert "полноценного редакторского материала" in prompt.user_prompt
    assert "не считай символы" in prompt.user_prompt
    assert "тематических разделов" in prompt.user_prompt
    assert "Не добавляй в конце отдельный блок «Источники»" in prompt.user_prompt
    assert "интерфейс покажет использованные статьи" in prompt.user_prompt


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


def test_digest_context_compacts_long_articles_to_keep_many_sources() -> None:
    long_text = "важный текст " * 400
    items = [
        _item(
            news_id,
            content=long_text,
            snippet_lead=f"lead-{news_id}",
            cluster_id=news_id,
        )
        for news_id in range(1, 31)
    ]

    assembled = assemble_context_for_digest(items, max_input_tokens=20000)

    assert len(assembled.documents) >= 20
    assert "lead-" in assembled.documents[0].content
    assert "topics:" in assembled.documents[0].content
    assert len(assembled.documents[0].content) <= 1500


def test_digest_context_exposes_topics_and_entities_for_sectioning() -> None:
    assembled = assemble_context_for_digest(
        [
            _item(
                1,
                content="ЦБ сохранил ставку.",
                snippet_lead="Решение ЦБ стало главным событием дня.",
            )
        ],
        max_input_tokens=20000,
    )

    assert "topics:" in assembled.documents[0].content
    assert "entities:" in assembled.documents[0].content


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
