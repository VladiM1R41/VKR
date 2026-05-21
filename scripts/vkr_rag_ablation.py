"""Small RAG ablation for the diploma experiments.

The script intentionally writes every row immediately, so interrupted LLM runs
do not lose already collected measurements.

Run from repository root:
    .\\.venv\\Scripts\\python.exe scripts\\run_with_layer_env.py -- .\\.venv\\Scripts\\python.exe scripts\\vkr_rag_ablation.py

Outputs:
    docs/experiments/vkr_rag/rag_ablation_current.csv
    docs/experiments/vkr_rag/rag_ablation_current.md
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
import statistics
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


QUERIES = (
    "Что известно о последних новостях, связанных с Трампом?",
    "Что сообщают источники о беспилотниках и ограничениях полетов?",
)

MODES = ("standard", "crag", "self_rag", "graph_rag")


@dataclass(slots=True)
class RagRow:
    query: str
    mode: str
    status: str
    latency_ms: int
    search_time_ms: int
    retrieval_mode: str
    confidence: str
    citation_valid: bool
    groundedness_score: float
    has_unsupported_claims: bool
    sources: int
    documents_used_count: int
    answer_words: int
    generation_log_id: int | None
    model_name: str
    error: str


def _write_rows(csv_path: Path, rows: list[RagRow]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 4) if values else 0.0


def _build_markdown(rows: list[RagRow]) -> str:
    lines = [
        "# RAG ablation: standard / CRAG / Self-RAG / GraphRAG",
        "",
        "Эксперимент выполнен на одном и том же корпусе и одинаковых пользовательских запросах. "
        "Для чистоты прогона response-cache отключён, а результаты фиксируются после каждого режима.",
        "",
        "## Aggregate metrics",
        "",
        "| Mode | OK runs | Mean latency, ms | Mean search, ms | Citation valid | Mean groundedness | Mean sources | Mean words | Model names |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for mode in MODES:
        mode_rows = [row for row in rows if row.mode == mode]
        ok_rows = [row for row in mode_rows if row.status == "ok"]
        citation_rate = _mean([1.0 if row.citation_valid else 0.0 for row in ok_rows])
        models = ", ".join(sorted({row.model_name for row in ok_rows if row.model_name})) or "-"
        lines.append(
            "| "
            f"{mode} | "
            f"{len(ok_rows)}/{len(mode_rows)} | "
            f"{_mean([row.latency_ms for row in ok_rows])} | "
            f"{_mean([row.search_time_ms for row in ok_rows])} | "
            f"{citation_rate} | "
            f"{_mean([row.groundedness_score for row in ok_rows])} | "
            f"{_mean([row.sources for row in ok_rows])} | "
            f"{_mean([row.answer_words for row in ok_rows])} | "
            f"{models} |"
        )

    lines.extend(
        [
            "",
            "## Detailed runs",
            "",
            "| Query | Mode | Status | Latency, ms | Confidence | Citation | Groundedness | Sources | Words | Model | Error |",
            "|---|---|---|---:|---|---|---:|---:|---:|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            f"{row.query[:55]} | {row.mode} | {row.status} | {row.latency_ms} | "
            f"{row.confidence} | {row.citation_valid} | {row.groundedness_score} | "
            f"{row.sources} | {row.answer_words} | {row.model_name or '-'} | {row.error[:80]} |"
        )
    return "\n".join(lines)


def _run() -> list[RagRow]:
    from jarvis.app.api.v1.chat import _search_context
    from jarvis.db.session import SyncSessionLocal
    from jarvis.generation.services.answer_generation_service import build_answer_generation_service
    from jarvis.generation.services.chat_memory_service import ChatMemoryService
    from jarvis.generation.services.chat_service import ChatService
    from jarvis.generation.services.providers.gigachat_provider import GigaChatProvider

    rows: list[RagRow] = []
    out_dir = ROOT / "docs" / "experiments" / "vkr_rag"
    csv_path = out_dir / "rag_ablation_current.csv"
    md_path = out_dir / "rag_ablation_current.md"

    for query in QUERIES:
        print(f"\nQUERY: {query}", flush=True)
        with SyncSessionLocal() as session:
            try:
                l3_response, _, context = _search_context(session, query=query, limit=5, user_id=1)
                retrieval_mode = (
                    l3_response.results[0].retrieval_mode
                    if l3_response.results
                    else "qdrant_hybrid"
                )
                search_time_ms = int(l3_response.search_time_ms)
            except Exception as exc:
                retrieval_mode = "error"
                search_time_ms = 0
                context = []
                print(f"  search error: {type(exc).__name__}: {exc}", flush=True)

            for mode in MODES:
                started = time.perf_counter()
                print(f"  RUN {mode}", flush=True)
                if not context:
                    row = RagRow(
                        query=query,
                        mode=mode,
                        status="error",
                        latency_ms=0,
                        search_time_ms=search_time_ms,
                        retrieval_mode=retrieval_mode,
                        confidence="ERROR",
                        citation_valid=False,
                        groundedness_score=0.0,
                        has_unsupported_claims=True,
                        sources=0,
                        documents_used_count=0,
                        answer_words=0,
                        generation_log_id=None,
                        model_name="",
                        error="no retrieval context",
                    )
                    rows.append(row)
                    _write_rows(csv_path, rows)
                    md_path.write_text(_build_markdown(rows), encoding="utf-8-sig")
                    continue

                try:
                    service = build_answer_generation_service(
                        provider=GigaChatProvider(),
                        chat_service=ChatService(),
                        chat_memory_service=ChatMemoryService(),
                    )
                    result = service.generate_chat_answer(
                        session,
                        user_query=query,
                        news_items=context,
                        user_id=1,
                        session_id=None,
                        session_title=f"RAG ablation: {mode}",
                        intent=l3_response.intent,
                        rag_mode_override=mode,
                    )
                    session.commit()
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    row = RagRow(
                        query=query,
                        mode=mode,
                        status="ok",
                        latency_ms=elapsed_ms,
                        search_time_ms=search_time_ms,
                        retrieval_mode=retrieval_mode,
                        confidence=result.confidence or "UNKNOWN",
                        citation_valid=bool(result.citation_valid),
                        groundedness_score=round(float(result.groundedness_score), 4),
                        has_unsupported_claims=bool(result.has_unsupported_claims),
                        sources=len(result.sources),
                        documents_used_count=int(result.documents_used_count),
                        answer_words=len(result.answer_text.split()),
                        generation_log_id=result.generation_log_id,
                        model_name=result.model_name,
                        error="",
                    )
                    print(
                        "    ok "
                        f"model={row.model_name} conf={row.confidence} "
                        f"citation={row.citation_valid} grounded={row.groundedness_score} "
                        f"sources={row.sources} latency={row.latency_ms}ms",
                        flush=True,
                    )
                except Exception as exc:
                    session.rollback()
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    row = RagRow(
                        query=query,
                        mode=mode,
                        status="error",
                        latency_ms=elapsed_ms,
                        search_time_ms=search_time_ms,
                        retrieval_mode=retrieval_mode,
                        confidence="ERROR",
                        citation_valid=False,
                        groundedness_score=0.0,
                        has_unsupported_claims=True,
                        sources=0,
                        documents_used_count=0,
                        answer_words=0,
                        generation_log_id=None,
                        model_name="",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    print(f"    ERROR {row.error}", flush=True)

                rows.append(row)
                _write_rows(csv_path, rows)
                md_path.write_text(_build_markdown(rows), encoding="utf-8-sig")

    return rows


def main() -> None:
    rows = _run()
    print("\nWritten:")
    print("  docs/experiments/vkr_rag/rag_ablation_current.csv")
    print("  docs/experiments/vkr_rag/rag_ablation_current.md")
    print(f"Rows: {len(rows)}")


if __name__ == "__main__":
    main()
