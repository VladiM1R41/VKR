#!/usr/bin/env python
"""End-to-end smoke test for Layers 1 -> 2 -> 3."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from time import perf_counter

sys.path.insert(0, "src")

from sqlalchemy import func, select

from jarvis.db.models import Chunk, News, SearchLog, SearchResult, Source
from jarvis.db.session import SyncSessionLocal
from jarvis.ingestion.services.collect_source import run_collect_source
from jarvis.processing.services.process_article import process_one_news_article
from jarvis.retrieval.models.search_models import SearchFilters, SearchRequest
from jarvis.retrieval.services.search_service import SearchService


_PROXY_VARS = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "GIT_HTTP_PROXY",
    "GIT_HTTPS_PROXY",
]


@dataclass(frozen=True, slots=True)
class SmokeStats:
    news_total: int
    news_processed: int
    news_pending: int
    chunks_rows: int
    search_logs: int
    search_results: int


def _clear_bad_proxy_env() -> None:
    for key in _PROXY_VARS:
        value = os.environ.get(key, "")
        if value.startswith("http://127.0.0.1:9"):
            os.environ.pop(key, None)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("PROCESSING_EMBEDDING_BACKEND", "flagembedding")


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
            news_processed=int(
                session.scalar(select(func.count()).select_from(News).where(News.processed.is_(True))) or 0
            ),
            news_pending=int(
                session.scalar(select(func.count()).select_from(News).where(News.processed.is_(False))) or 0
            ),
            chunks_rows=int(session.scalar(select(func.count()).select_from(Chunk)) or 0),
            search_logs=int(session.scalar(select(func.count()).select_from(SearchLog)) or 0),
            search_results=int(session.scalar(select(func.count()).select_from(SearchResult)) or 0),
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
            .where(
                News.source_id == source_id,
                News.processed.is_(False),
            )
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
    if not tokens:
        return title
    return " ".join(tokens[:6])


def _print_stats(label: str, stats: SmokeStats) -> None:
    print(
        f"{label}: "
        f"news_total={stats.news_total}, "
        f"processed={stats.news_processed}, "
        f"pending={stats.news_pending}, "
        f"chunks={stats.chunks_rows}, "
        f"search_logs={stats.search_logs}, "
        f"search_results={stats.search_results}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Layers 1 -> 2 -> 3 on a live source.")
    parser.add_argument("--source", default="ТАСС", help="Exact source name from the sources table.")
    parser.add_argument("--limit", type=int, default=3, help="How many fresh articles to process.")
    parser.add_argument("--top-k", type=int, default=5, help="How many search results to request.")
    parser.add_argument("--skip-collect", action="store_true", help="Skip Layer 1 and use existing pending articles.")
    parser.add_argument("--query", default=None, help="Explicit search query. Defaults to a query derived from a processed title.")
    args = parser.parse_args()

    _clear_bad_proxy_env()

    source = _get_source(args.source)
    before = _collect_stats()
    _print_stats("Before", before)

    latest_news_id_before = before.news_total
    collect_result: dict[str, object] | None = None
    if not args.skip_collect:
        t0 = perf_counter()
        collect_result = run_collect_source(args.source)
        print(f"Layer 1 collect result ({perf_counter() - t0:.1f}s): {collect_result}")

    target_ids = _load_fresh_pending_ids(source.id, min_news_id=latest_news_id_before, limit=args.limit)
    if not target_ids:
        target_ids = _load_latest_pending_ids(source.id, limit=args.limit)
        print("No fresh pending articles from this run; falling back to latest pending articles for the source.")

    if not target_ids:
        raise RuntimeError("No pending articles available for processing.")

    target_ids = sorted(target_ids)
    print(f"Layer 2 targets: {target_ids}")

    processed_ids: list[int] = []
    for news_id in target_ids:
        t0 = perf_counter()
        result = process_one_news_article(news_id)
        print(f"Processed news_id={news_id} in {perf_counter() - t0:.1f}s -> {result}")
        if result.status == "processed":
            processed_ids.append(news_id)

    if not processed_ids:
        raise RuntimeError("Layer 2 did not process any target article.")

    focus_news = _load_news(processed_ids[-1])
    query = args.query or _derive_query_from_title(focus_news.title)
    print(f"Layer 3 query: {query}")
    print(f"Expected article: news_id={focus_news.id}, title={focus_news.title}")

    search_service = SearchService()
    t0 = perf_counter()
    response = search_service.search(
        SearchRequest(
            query=query,
            limit=args.top_k,
            filters=SearchFilters(language=focus_news.language or "ru"),
        ),
        user_id="smoke-user",
    )
    print(f"Layer 3 search completed in {perf_counter() - t0:.1f}s; total={response.total}, intent={response.intent}")
    if response.corrected_query:
        print(f"Corrected query: {response.corrected_query}")

    hit_position: int | None = None
    for index, item in enumerate(response.results, start=1):
        print(
            f"  #{index}: news_id={item.news_id} score={item.score:.4f} "
            f"rerank={item.rerank_score} source={item.source_name} title={item.title}"
        )
        if item.news_id == focus_news.id and hit_position is None:
            hit_position = index

    after = _collect_stats()
    _print_stats("After", after)

    if hit_position is None:
        print("SMOKE FAILED: processed article was not found in top-k search results.")
        return 1

    print(f"SMOKE OK: processed article found at rank #{hit_position}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
