#!/usr/bin/env python
"""End-to-end smoke test for Layers 1 -> 5."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from time import perf_counter

sys.path.insert(0, "src")

from sqlalchemy import func, select

from jarvis.db.models import (
    ChatMessage,
    ChatSession,
    Chunk,
    Digest,
    Entity,
    GenerationLog,
    News,
    SearchLog,
    SearchResult,
    Source,
    Topic,
    User,
    UserEntityWeight,
    UserSourcePreference,
    UserTopicWeight,
)
from jarvis.db.session import SyncSessionLocal
from jarvis.generation.models.generation_models import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    ProviderConfig,
)
from jarvis.generation.services import (
    AnswerGenerationService,
    ChatMemoryService,
    ChatService,
    CRAGService,
    GenerationConfig,
    GenerationEvaluationScenario,
    GenerationEvaluationService,
    GraphRAGLightService,
    RetrievalBridge,
    SelfRAGLightService,
)
from jarvis.generation.services.context_assembler import NewsWithContext, enrich_with_db_data
from jarvis.generation.services.providers.base import LLMProvider
from jarvis.generation.services.providers.factory import build_primary_provider
from jarvis.ingestion.services.collect_source import run_collect_source
from jarvis.personalization.services.digest_service import DigestOrchestrationService
from jarvis.personalization.services.ranking_service import PersonalizedRankingService
from jarvis.processing.services.process_article import process_one_news_article
from jarvis.retrieval.models.search_models import SearchFilters, SearchRequest
from jarvis.retrieval.services.search_service import SearchService


_PROXY_VARS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "GIT_HTTP_PROXY",
    "GIT_HTTPS_PROXY",
]


@dataclass(frozen=True, slots=True)
class SmokeStats:
    news_total: int
    news_processed: int
    chunks_rows: int
    search_logs: int
    search_results: int
    users: int
    chat_sessions: int
    chat_messages: int
    generation_logs: int
    digests: int


class _SmokeFakeProvider(LLMProvider):
    """Deterministic provider for smoke runs when real LLM is unavailable."""

    def __init__(self) -> None:
        super().__init__(ProviderConfig(provider_name="smoke-fake", model_name="smoke-fake-model"))

    async def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        sources = re.findall(r"source:\s*(.+)", request.context)
        titles = re.findall(r"title:\s*(.+)", request.context)
        contents = re.findall(r"content:\s*(.+)", request.context)
        source_a = sources[0].strip() if sources else "источник"
        source_b = sources[1].strip() if len(sources) > 1 else source_a
        lead = contents[0].strip() if contents else (titles[0].strip() if titles else request.user_prompt.strip())
        lead = " ".join(lead.split()[:16])
        mode = str((request.metadata or {}).get("mode", "standard"))
        if mode == "digest":
            content = f"Главное за период: {lead} ({source_a}). Дополнительное подтверждение: {source_b}."
        elif mode == "alert":
            content = f"{lead} ({source_a})."
        else:
            content = f"По данным {source_a}, {lead}. Дополнительный контекст подтверждает {source_b}."
        return LLMGenerationResponse(
            provider_name="smoke-fake",
            model_name="smoke-fake-model",
            content=content,
            input_tokens=120,
            output_tokens=40,
            latency_ms=10,
        )


def _clear_bad_proxy_env() -> None:
    for key in _PROXY_VARS:
        value = os.environ.get(key, "")
        if value.startswith("http://127.0.0.1:9"):
            os.environ.pop(key, None)


def _get_source(source_name: str) -> Source:
    with SyncSessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == source_name))
    if source is None:
        raise RuntimeError(f"Source not found: {source_name}")
    return source


def _collect_stats() -> SmokeStats:
    with SyncSessionLocal() as session:
        return SmokeStats(
            news_total=int(session.scalar(select(func.count()).select_from(News)) or 0),
            news_processed=int(session.scalar(select(func.count()).select_from(News).where(News.processed.is_(True))) or 0),
            chunks_rows=int(session.scalar(select(func.count()).select_from(Chunk)) or 0),
            search_logs=int(session.scalar(select(func.count()).select_from(SearchLog)) or 0),
            search_results=int(session.scalar(select(func.count()).select_from(SearchResult)) or 0),
            users=int(session.scalar(select(func.count()).select_from(User)) or 0),
            chat_sessions=int(session.scalar(select(func.count()).select_from(ChatSession)) or 0),
            chat_messages=int(session.scalar(select(func.count()).select_from(ChatMessage)) or 0),
            generation_logs=int(session.scalar(select(func.count()).select_from(GenerationLog)) or 0),
            digests=int(session.scalar(select(func.count()).select_from(Digest)) or 0),
        )


def _print_stats(label: str, stats: SmokeStats) -> None:
    print(
        f"{label}: "
        f"news_total={stats.news_total}, processed={stats.news_processed}, chunks={stats.chunks_rows}, "
        f"search_logs={stats.search_logs}, search_results={stats.search_results}, users={stats.users}, "
        f"chat_sessions={stats.chat_sessions}, chat_messages={stats.chat_messages}, "
        f"generation_logs={stats.generation_logs}, digests={stats.digests}"
    )


def _load_fresh_pending_ids(source_id: int, *, min_news_id: int, limit: int) -> list[int]:
    with SyncSessionLocal() as session:
        stmt = (
            select(News.id)
            .where(
                News.source_id == source_id,
                News.processed.is_(False),
                News.id > min_news_id,
            )
            .order_by(News.id.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())


def _load_latest_pending_ids(source_id: int, *, limit: int) -> list[int]:
    with SyncSessionLocal() as session:
        stmt = (
            select(News.id)
            .where(News.source_id == source_id, News.processed.is_(False))
            .order_by(News.id.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())


def _load_news(news_id: int) -> News:
    with SyncSessionLocal() as session:
        news = session.get(News, news_id)
    if news is None:
        raise RuntimeError(f"News not found: {news_id}")
    return news


def _derive_query_from_title(title: str) -> str:
    normalized = re.sub(r"[^\w\s]+", " ", title, flags=re.UNICODE)
    tokens = [token for token in normalized.split() if len(token) >= 4]
    return " ".join(tokens[:6]) if tokens else title


def _ensure_smoke_user_and_preferences(
    *,
    source_id: int,
    topic_names: list[str],
    entity_names: list[str],
) -> int:
    with SyncSessionLocal() as session:
        user = session.scalar(select(User).where(User.username == "smoke-layer5"))
        if user is None:
            user = User(username="smoke-layer5", email="smoke-layer5@example.local", settings={})
            session.add(user)
            session.flush()

        source_pref = session.get(UserSourcePreference, {"user_id": user.id, "source_id": source_id})
        if source_pref is None:
            session.add(UserSourcePreference(user_id=user.id, source_id=source_id, preference="preferred"))
        else:
            source_pref.preference = "preferred"

        if topic_names:
            topic = session.scalar(select(Topic).where(Topic.name == topic_names[0]))
            if topic is not None:
                existing = session.get(UserTopicWeight, {"user_id": user.id, "topic_id": topic.id})
                if existing is None:
                    session.add(UserTopicWeight(user_id=user.id, topic_id=topic.id, weight=0.95))
                else:
                    existing.weight = 0.95

        if entity_names:
            entity = session.scalar(select(Entity).where(Entity.name == entity_names[0]))
            if entity is not None:
                existing = session.get(UserEntityWeight, {"user_id": user.id, "entity_id": entity.id})
                if existing is None:
                    session.add(UserEntityWeight(user_id=user.id, entity_id=entity.id, weight=0.95))
                else:
                    existing.weight = 0.95

        session.commit()
        return int(user.id)


def _personalized_to_news_context(results) -> list[NewsWithContext]:
    news_ids = [item.news_id for item in results]
    source_ids = {item.source_id for item in results}
    titles = {item.news_id: item.title for item in results}
    snippets = {item.news_id: item.snippet for item in results}
    scores = {item.news_id: item.base_score for item in results}
    rerank_scores = {item.news_id: item.base_score for item in results}
    personalized_scores = {item.news_id: item.personalized_score for item in results}
    topics_map = {item.news_id: list(item.topics) for item in results}
    entities_map = {item.news_id: list(item.entities) for item in results}
    published_map = {
        item.news_id: item.published_at.isoformat() if item.published_at else ""
        for item in results
    }
    trust_map = {item.news_id: 0.6 for item in results}
    grade_map = {item.news_id: 3 for item in results}
    info_type_map = {item.news_id: "daily" for item in results}
    urgency_map = {item.news_id: "normal" for item in results}
    cluster_map = {item.news_id: None for item in results}
    return enrich_with_db_data(
        news_ids=news_ids,
        source_ids=source_ids,
        titles=titles,
        snippets=snippets,
        scores=scores,
        rerank_scores=rerank_scores,
        personalized_scores=personalized_scores,
        topics_map=topics_map,
        entities_map=entities_map,
        published_map=published_map,
        trust_map=trust_map,
        grade_map=grade_map,
        info_type_map=info_type_map,
        urgency_map=urgency_map,
        cluster_map=cluster_map,
    )


def _build_provider(mode: str) -> tuple[LLMProvider, str]:
    if mode == "fake":
        return _SmokeFakeProvider(), "fake"
    try:
        provider = build_primary_provider()
        return provider, "real"
    except Exception:
        return _SmokeFakeProvider(), "fake-fallback"


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Layers 1 -> 5 on live-ish data.")
    parser.add_argument("--source", default="ТАСС")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--skip-collect", action="store_true")
    parser.add_argument("--provider", choices=["auto", "fake"], default="auto")
    args = parser.parse_args()

    _clear_bad_proxy_env()

    source = _get_source(args.source)
    before = _collect_stats()
    _print_stats("Before", before)

    latest_news_id_before = before.news_total
    if not args.skip_collect:
        t0 = perf_counter()
        collect_result = run_collect_source(args.source)
        print(f"[Layer 1] collect {args.source}: {collect_result} ({perf_counter() - t0:.1f}s)")

    target_ids = _load_fresh_pending_ids(source.id, min_news_id=latest_news_id_before, limit=args.limit)
    if not target_ids:
        target_ids = _load_latest_pending_ids(source.id, limit=args.limit)
        print("[Layer 2] no fresh pending articles, using latest pending for the source.")
    if not target_ids:
        raise RuntimeError("No pending articles available for processing.")

    processed_ids: list[int] = []
    for news_id in sorted(target_ids):
        result = process_one_news_article(news_id)
        print(f"[Layer 2] processed news_id={news_id}: {result}")
        if result.status == "processed":
            processed_ids.append(news_id)
    if not processed_ids:
        raise RuntimeError("Layer 2 did not process any article.")

    focus_news = _load_news(processed_ids[-1])
    query = _derive_query_from_title(focus_news.title)
    print(f"[Layer 3] query={query}")

    search_service = SearchService()
    search_response = search_service.search(
        SearchRequest(
            query=query,
            limit=args.top_k,
            filters=SearchFilters(language=focus_news.language or "ru"),
        ),
        user_id="smoke-user-layer5",
    )
    if not search_response.results:
        raise RuntimeError("Layer 3 returned no results.")
    print(f"[Layer 3] total={search_response.total}, intent={search_response.intent}")
    for index, item in enumerate(search_response.results[: args.top_k], start=1):
        print(f"  search #{index}: news_id={item.news_id} source={item.source_name} title={item.title}")

    focus_result = search_response.results[0]
    user_id = _ensure_smoke_user_and_preferences(
        source_id=focus_result.source_id,
        topic_names=list(focus_result.topics),
        entity_names=list(focus_result.entities),
    )

    with SyncSessionLocal() as session:
        personalized = PersonalizedRankingService().rerank(session, user_id, search_response)
        print(f"[Layer 4] personalized total={personalized.total}")
        for index, item in enumerate(personalized.results[: args.top_k], start=1):
            print(
                f"  personalized #{index}: news_id={item.news_id} "
                f"score={item.personalized_score:.4f} reasons={item.personalization_reasons}"
            )

    news_items_for_generation = _personalized_to_news_context(personalized.results[: args.top_k])
    if not news_items_for_generation:
        raise RuntimeError("Could not build Layer 5 context from personalized results.")

    provider, provider_mode = _build_provider(args.provider)
    print(f"[Layer 5] provider mode={provider_mode}")
    chat_service = ChatService()
    chat_memory_service = ChatMemoryService(chat_service=chat_service)
    answer_service = AnswerGenerationService(
        provider=provider,
        config=GenerationConfig(enable_logging=True),
        chat_service=chat_service,
        chat_memory_service=chat_memory_service,
    )

    with SyncSessionLocal() as session:
        standard_result = answer_service.generate_chat_answer(
            db_session=session,
            user_query=query,
            news_items=news_items_for_generation,
            user_id=user_id,
            session_id=None,
            intent=search_response.intent,
            rag_mode_override="standard",
        )
        session.commit()

    print(f"[Layer 5][standard] confidence={standard_result.confidence} answer={standard_result.answer_text}")

    bridge = RetrievalBridge(search_service=search_service)
    retrieval_fn = lambda refined_query: bridge.retrieve_news_context(query=refined_query, limit=args.top_k)

    crag_result = CRAGService().generate(
        answer_service=answer_service,
        user_query=query,
        news_items=news_items_for_generation,
        retrieval_fn=retrieval_fn,
        user_id=user_id,
        intent=search_response.intent,
    )
    print(
        f"[Layer 5][crag] used_retry={crag_result.decision.used_retry} "
        f"quality={crag_result.decision.initial_quality_score}->{crag_result.decision.retry_quality_score}"
    )

    self_rag_result = SelfRAGLightService().generate(
        answer_service=answer_service,
        user_query=query,
        news_items=news_items_for_generation,
        retrieval_fn=retrieval_fn,
        user_id=user_id,
        intent=search_response.intent,
    )
    print(
        f"[Layer 5][self-rag] retrieve_needed={self_rag_result.decision.retrieve_needed} "
        f"used_retrieval={self_rag_result.decision.used_retrieval}"
    )

    with SyncSessionLocal() as session:
        graph_rag_result = GraphRAGLightService().generate(
            session=session,
            answer_service=answer_service,
            user_query=query,
            news_items=news_items_for_generation,
            user_id=user_id,
            intent=search_response.intent,
        )
    print(
        f"[Layer 5][graph-rag] seed={graph_rag_result.expansion.seed_entities} "
        f"related={graph_rag_result.expansion.related_entities} added_news={graph_rag_result.expansion.added_news_ids}"
    )

    evaluator = GenerationEvaluationService()
    crag_cmp = evaluator.compare(
        GenerationEvaluationScenario(mode_name="standard", result=standard_result),
        GenerationEvaluationScenario(mode_name="crag", result=crag_result.answer),
    )
    self_cmp = evaluator.compare(
        GenerationEvaluationScenario(mode_name="standard", result=standard_result),
        GenerationEvaluationScenario(mode_name="self_rag", result=self_rag_result.answer),
    )
    graph_cmp = evaluator.compare(
        GenerationEvaluationScenario(mode_name="standard", result=standard_result),
        GenerationEvaluationScenario(mode_name="graph_rag", result=graph_rag_result.answer),
    )
    print(f"[Layer 5][eval] standard->crag: {crag_cmp}")
    print(f"[Layer 5][eval] standard->self_rag: {self_cmp}")
    print(f"[Layer 5][eval] standard->graph_rag: {graph_cmp}")

    with SyncSessionLocal() as session:
        digest_service = DigestOrchestrationService()
        shortlist = digest_service.build_shortlist(
            session,
            user_id=user_id,
            digest_type="on_demand",
            ranked_response=personalized,
            limit=min(args.top_k, 5),
        )
        digest_text, generation_log_id = digest_service.generate_digest_text(
            session,
            shortlist=shortlist,
            generation_service=answer_service,
            continuity_context="",
        )
        digest = digest_service.persist_shortlist(
            session,
            shortlist=shortlist,
            content_text=digest_text,
            generation_log_id=generation_log_id,
        )
        print(
            f"[Layer 5][digest] digest_id={digest.id} generation_log_id={digest.generation_log_id} "
            f"news_count={digest.news_count}"
        )

    after = _collect_stats()
    _print_stats("After", after)

    if after.chat_sessions <= before.chat_sessions:
        raise RuntimeError("Smoke failed: chat session count did not grow.")
    if after.chat_messages <= before.chat_messages:
        raise RuntimeError("Smoke failed: chat message count did not grow.")
    if after.generation_logs <= before.generation_logs:
        raise RuntimeError("Smoke failed: generation logs did not grow.")
    if after.digests <= before.digests:
        raise RuntimeError("Smoke failed: digests did not grow.")

    print("SMOKE OK: Layers 1 -> 5 completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
