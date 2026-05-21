"""Retrieval ablation study: dense-only vs sparse-only vs hybrid RRF.

The script is intentionally outside the runtime API. It directly queries the
existing Qdrant index in three modes and writes reproducible experiment tables.

Run from repository root:
    .\\.venv\\Scripts\\python.exe scripts\\run_with_layer_env.py -- .\\.venv\\Scripts\\python.exe scripts\\retrieval_ablation.py

Outputs:
    docs/experiments/retrieval_ablation_summary.csv
    docs/experiments/retrieval_ablation_results.csv
    docs/experiments/retrieval_ablation.md
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


MODES = ("dense_only", "sparse_only", "hybrid")
MODE_LABELS = {
    "dense_only": "Dense-only semantic search",
    "sparse_only": "Sparse-only lexical search",
    "hybrid": "Hybrid RRF dense+sparse",
}


@dataclass(frozen=True, slots=True)
class QueryCase:
    """One evaluation query with lightweight relevance hints."""

    query_id: str
    query: str
    relevant_terms: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class RetrievedItem:
    """One raw Qdrant hit normalized for reporting."""

    rank: int
    point_id: str
    news_id: int
    score: float
    source_name: str
    title: str
    text: str
    url: str
    topics: tuple[str, ...]
    entities: tuple[str, ...]
    keywords: tuple[str, ...]
    published_at: str
    relevance: int
    matched_terms: tuple[str, ...]


DEFAULT_QUERIES: tuple[QueryCase, ...] = (
    QueryCase(
        query_id="q01_trump",
        query="Трамп",
        relevant_terms=("трамп",),
        description="Entity-heavy query; lexical channel should be strong.",
    ),
    QueryCase(
        query_id="q02_bank_russia_rate",
        query="ключевая ставка Банк России",
        relevant_terms=("ставк", "банк россии", "центробанк", "цб"),
        description="Exact economic terms and organization aliases.",
    ),
    QueryCase(
        query_id="q03_ai",
        query="искусственный интеллект технологии",
        relevant_terms=("искусствен", "интеллект", "технолог", "ai"),
        description="Broad semantic technology query.",
    ),
    QueryCase(
        query_id="q04_sanctions",
        query="санкции экономика последствия",
        relevant_terms=("санкц", "эконом", "последств"),
        description="Broad political/economic topic query.",
    ),
    QueryCase(
        query_id="q05_mvd",
        query="МВД расследование",
        relevant_terms=("мвд", "расслед"),
        description="Named entity plus event/action query.",
    ),
)


def _load_queries(path: Path | None) -> tuple[QueryCase, ...]:
    if path is None:
        return DEFAULT_QUERIES

    payload = json.loads(path.read_text(encoding="utf-8"))
    cases: list[QueryCase] = []
    for index, item in enumerate(payload, start=1):
        cases.append(
            QueryCase(
                query_id=str(item.get("query_id") or f"q{index:02d}"),
                query=str(item["query"]),
                relevant_terms=tuple(str(term).lower() for term in item.get("relevant_terms", [])),
                description=str(item.get("description") or ""),
            )
        )
    return tuple(cases)


def _encode_query(query: str):
    """Return dense and sparse vectors using the same runtime as Layers 2/3."""
    from jarvis.processing.ir.lemmatize import lemmatize_text
    from jarvis.processing.services.embedding_runtime import encode_texts

    lemma_text = lemmatize_text(query)
    encoded = encode_texts([query], sparse_texts=[lemma_text])[0]
    return encoded.dense_vector, encoded.sparse_indices, encoded.sparse_values


def _query_qdrant(
    *,
    dense_vector: list[float],
    sparse_indices: list[int],
    sparse_values: list[float],
    mode: str,
    limit: int,
) -> tuple[list[Any], float]:
    """Run one direct Qdrant query mode and return raw points + latency."""
    from jarvis.core.settings import get_settings
    from qdrant_client import QdrantClient, models

    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url)
    query_filter = models.Filter(
        must=[
            models.FieldCondition(key="language", match=models.MatchValue(value="ru")),
        ]
    )

    start = time.perf_counter()
    if mode == "dense_only":
        response = client.query_points(
            collection_name=settings.qdrant_collection_alias,
            query=dense_vector,
            using="dense",
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
    elif mode == "sparse_only":
        if not sparse_indices or not sparse_values:
            return [], 0.0
        response = client.query_points(
            collection_name=settings.qdrant_collection_alias,
            query=models.SparseVector(indices=sparse_indices, values=sparse_values),
            using="sparse",
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
    elif mode == "hybrid":
        prefetch = [
            models.Prefetch(query=dense_vector, using="dense", limit=limit),
        ]
        if sparse_indices and sparse_values:
            prefetch.append(
                models.Prefetch(
                    query=models.SparseVector(indices=sparse_indices, values=sparse_values),
                    using="sparse",
                    limit=limit,
                )
            )
        response = client.query_points(
            collection_name=settings.qdrant_collection_alias,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
    else:
        raise ValueError(f"Unknown mode: {mode}")

    latency_ms = (time.perf_counter() - start) * 1000
    return list(response.points), latency_ms


def _normalize_text(value: object) -> str:
    return str(value or "").lower().replace("ё", "е")


def _score_relevance(payload: dict[str, Any], relevant_terms: tuple[str, ...]) -> tuple[int, tuple[str, ...]]:
    """Lightweight automatic relevance label for early experiments.

    2 = expected term/entity appears in title, entities, topics or keywords.
    1 = expected term appears only in chunk/article text.
    0 = no expected term found.
    """
    if not relevant_terms:
        return 0, ()

    title = _normalize_text(payload.get("title") or payload.get("snippet_lead"))
    strong_fields = " ".join(
        [
            title,
            _normalize_text(" ".join(payload.get("entities") or [])),
            _normalize_text(" ".join(payload.get("topics") or [])),
            _normalize_text(" ".join(payload.get("keywords") or [])),
        ]
    )
    weak_fields = " ".join(
        [
            strong_fields,
            _normalize_text(payload.get("text") or payload.get("text_content")),
            _normalize_text(payload.get("lemma_text")),
        ]
    )

    matched_strong = tuple(term for term in relevant_terms if _normalize_text(term) in strong_fields)
    if matched_strong:
        return 2, matched_strong

    matched_weak = tuple(term for term in relevant_terms if _normalize_text(term) in weak_fields)
    if matched_weak:
        return 1, matched_weak

    return 0, ()


def _normalize_hit(rank: int, point: Any, case: QueryCase) -> RetrievedItem:
    payload = point.payload or {}
    relevance, matched_terms = _score_relevance(payload, case.relevant_terms)
    return RetrievedItem(
        rank=rank,
        point_id=str(point.id),
        news_id=int(payload.get("news_id") or 0),
        score=round(float(point.score or 0.0), 6),
        source_name=str(payload.get("source_name") or ""),
        title=str(payload.get("title") or payload.get("snippet_lead") or ""),
        text=str(payload.get("text") or payload.get("text_content") or ""),
        url=str(payload.get("url") or ""),
        topics=tuple(str(item) for item in payload.get("topics") or []),
        entities=tuple(str(item) for item in payload.get("entities") or []),
        keywords=tuple(str(item) for item in payload.get("keywords") or []),
        published_at=str(payload.get("published_at") or ""),
        relevance=relevance,
        matched_terms=matched_terms,
    )


def _precision_at(items: list[RetrievedItem], k: int) -> float:
    window = items[:k]
    if not window:
        return 0.0
    return sum(1 for item in window if item.relevance > 0) / len(window)


def _mrr(items: list[RetrievedItem]) -> float:
    for item in items:
        if item.relevance > 0:
            return 1.0 / item.rank
    return 0.0


def _dcg(relevances: list[int]) -> float:
    return sum((2**rel - 1) / math.log2(index + 2) for index, rel in enumerate(relevances))


def _ndcg_at(items: list[RetrievedItem], k: int) -> float:
    relevances = [item.relevance for item in items[:k]]
    if not relevances:
        return 0.0
    ideal = sorted(relevances, reverse=True)
    ideal_dcg = _dcg(ideal)
    if ideal_dcg == 0:
        return 0.0
    return _dcg(relevances) / ideal_dcg


def _source_diversity(items: list[RetrievedItem], k: int) -> int:
    return len({item.source_name for item in items[:k] if item.source_name})


def _run_case(case: QueryCase, *, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dense_vector, sparse_indices, sparse_values = _encode_query(case.query)
    result_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    for mode in MODES:
        points, latency_ms = _query_qdrant(
            dense_vector=dense_vector,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            mode=mode,
            limit=limit,
        )
        items = [_normalize_hit(rank, point, case) for rank, point in enumerate(points, start=1)]
        summary_rows.append(
            {
                "query_id": case.query_id,
                "query": case.query,
                "mode": mode,
                "mode_label": MODE_LABELS[mode],
                "latency_ms": round(latency_ms, 1),
                "results": len(items),
                "precision_at_5": round(_precision_at(items, 5), 4),
                "precision_at_10": round(_precision_at(items, 10), 4),
                "mrr": round(_mrr(items), 4),
                "ndcg_at_10": round(_ndcg_at(items, 10), 4),
                "source_diversity_at_10": _source_diversity(items, 10),
                "top1_news_id": items[0].news_id if items else None,
                "top1_title": items[0].title if items else "",
                "top1_relevance": items[0].relevance if items else 0,
                "error": "",
            }
        )

        for item in items:
            result_rows.append(
                {
                    "query_id": case.query_id,
                    "query": case.query,
                    "mode": mode,
                    "rank": item.rank,
                    "news_id": item.news_id,
                    "point_id": item.point_id,
                    "score": item.score,
                    "auto_relevance": item.relevance,
                    "matched_terms": ", ".join(item.matched_terms),
                    "source_name": item.source_name,
                    "title": item.title,
                    "url": item.url,
                    "topics": ", ".join(item.topics),
                    "entities": ", ".join(item.entities[:8]),
                    "published_at": item.published_at,
                }
            )

    return summary_rows, result_rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _mean(rows: list[dict[str, Any]], mode: str, key: str) -> float:
    values = [float(row[key]) for row in rows if row["mode"] == mode and row.get("error", "") == ""]
    return round(statistics.mean(values), 4) if values else 0.0


def _build_markdown(
    *,
    cases: tuple[QueryCase, ...],
    summary_rows: list[dict[str, Any]],
    result_rows: list[dict[str, Any]],
) -> str:
    lines = [
        "# Retrieval ablation: dense-only vs sparse-only vs hybrid",
        "",
        f"Дата запуска: {datetime.now(UTC).isoformat(timespec='seconds')}",
        "",
        "Эксперимент сравнивает только первый этап поиска по индексу Qdrant. Переранжирование кросс-кодером,",
        "персонализация и кэш здесь намеренно отключены, чтобы изолировать вклад retrieval-каналов.",
        "",
        "Автоматическая релевантность является предварительной эвристикой:",
        "",
        "- `2`: ожидаемый термин найден в заголовке, сущностях, темах или ключевых словах;",
        "- `1`: ожидаемый термин найден только в тексте фрагмента;",
        "- `0`: ожидаемый термин не найден.",
        "",
        "Для итоговой дипломной оценки этот CSV удобно дополнить ручной экспертной разметкой `0/1/2` и пересчитать nDCG.",
        "",
        "## Aggregate metrics",
        "",
        "| Mode | Mean latency, ms | P@5 | P@10 | MRR | nDCG@10 | Source diversity@10 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        lines.append(
            "| "
            f"{MODE_LABELS[mode]} | "
            f"{_mean(summary_rows, mode, 'latency_ms')} | "
            f"{_mean(summary_rows, mode, 'precision_at_5')} | "
            f"{_mean(summary_rows, mode, 'precision_at_10')} | "
            f"{_mean(summary_rows, mode, 'mrr')} | "
            f"{_mean(summary_rows, mode, 'ndcg_at_10')} | "
            f"{_mean(summary_rows, mode, 'source_diversity_at_10')} |"
        )

    lines.extend(
        [
            "",
            "## Query-level metrics",
            "",
            "| Query | Mode | P@5 | MRR | nDCG@10 | Top-1 relevance | Top-1 title |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in summary_rows:
        lines.append(
            "| "
            f"{row['query']} | {row['mode']} | {row['precision_at_5']} | {row['mrr']} | "
            f"{row['ndcg_at_10']} | {row['top1_relevance']} | {str(row['top1_title'])[:90]} |"
        )

    lines.extend(["", "## Query set", ""])
    for case in cases:
        lines.append(
            f"- `{case.query_id}`: {case.query}. Terms: {', '.join(case.relevant_terms)}. {case.description}"
        )

    lines.extend(
        [
            "",
            "## Sample top results",
            "",
            "| Query | Mode | Rank | Relevance | Source | Title |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    for row in result_rows:
        if int(row["rank"]) > 3:
            continue
        lines.append(
            "| "
            f"{row['query']} | {row['mode']} | {row['rank']} | {row['auto_relevance']} | "
            f"{row['source_name']} | {str(row['title'])[:110]} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation hints",
            "",
            "- Dense-only обычно лучше ловит смысловые связи, но может приводить тематически близкие, но лексически неточные документы.",
            "- Sparse-only обычно сильнее на именах, организациях, числах и точных формулировках.",
            "- Hybrid RRF должен давать более устойчивый результат, потому что объединяет оба сигнала без приведения score к одной шкале.",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, default=None, help="Optional JSON query set.")
    parser.add_argument("--limit", type=int, default=10, help="Top-K per query/mode.")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "docs" / "experiments")
    args = parser.parse_args()

    cases = _load_queries(args.queries)
    summary_rows: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []

    print(f"Retrieval ablation: {len(cases)} queries x {len(MODES)} modes, limit={args.limit}", flush=True)
    print("Loading embedding backend on first query may take time, but offline cache should be used.", flush=True)

    for case_index, case in enumerate(cases, start=1):
        print(f"\n[{case_index}/{len(cases)}] {case.query}", flush=True)
        try:
            case_summary, case_results = _run_case(case, limit=args.limit)
        except Exception as exc:
            print(f"  ERROR: {exc}", flush=True)
            for mode in MODES:
                summary_rows.append(
                    {
                        "query_id": case.query_id,
                        "query": case.query,
                        "mode": mode,
                        "mode_label": MODE_LABELS[mode],
                        "latency_ms": 0,
                        "results": 0,
                        "precision_at_5": 0,
                        "precision_at_10": 0,
                        "mrr": 0,
                        "ndcg_at_10": 0,
                        "source_diversity_at_10": 0,
                        "top1_news_id": None,
                        "top1_title": "",
                        "top1_relevance": 0,
                        "error": str(exc),
                    }
                )
            continue

        summary_rows.extend(case_summary)
        result_rows.extend(case_results)
        for row in case_summary:
            print(
                "  "
                f"{row['mode']:<12} latency={row['latency_ms']:>7}ms "
                f"P@5={row['precision_at_5']:.2f} "
                f"MRR={row['mrr']:.2f} "
                f"nDCG@10={row['ndcg_at_10']:.2f}",
                flush=True,
            )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.out_dir / "retrieval_ablation_summary.csv"
    results_path = args.out_dir / "retrieval_ablation_results.csv"
    report_path = args.out_dir / "retrieval_ablation.md"
    _write_csv(summary_path, summary_rows)
    _write_csv(results_path, result_rows)
    report_path.write_text(
        _build_markdown(cases=cases, summary_rows=summary_rows, result_rows=result_rows),
        encoding="utf-8",
    )

    print("\nWritten:")
    print(f"  {summary_path}")
    print(f"  {results_path}")
    print(f"  {report_path}")


if __name__ == "__main__":
    main()
