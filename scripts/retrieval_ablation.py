"""Ablation study: Dense-only vs Sparse-only vs Hybrid (RRF) retrieval.

Запуск:
    .venv/Scripts/python scripts/retrieval_ablation.py

Результат: docs/retrieval_ablation.md + docs/retrieval_ablation.csv
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.core.settings import get_settings
get_settings.cache_clear()

# ── Тестовые запросы ──────────────────────────────────────────────────────────

QUERIES = [
    "курс доллара рубль Банк России",        # лексически точный + именованные сущности
    "санкции экономика последствия",          # семантически широкий
    "искусственный интеллект технологии",    # тематический
    "Путин политика Россия",                 # entity-heavy
    "образование школа ученики",             # общая тема
]

MODES = ["dense_only", "sparse_only", "hybrid"]


def encode_query(query: str):
    """Получить dense + sparse векторы для запроса."""
    from jarvis.processing.ir.lemmatize import lemmatize_text
    from jarvis.processing.services.embedding_runtime import encode_texts

    lemma = " ".join(lemmatize_text(query))
    result = encode_texts([query], sparse_texts=[lemma])
    dense = result["dense"][0].tolist()
    sparse_raw = result.get("sparse", [{}])[0]  # dict {token_id: weight}
    indices = list(sparse_raw.keys()) if sparse_raw else []
    values = list(sparse_raw.values()) if sparse_raw else []
    return dense, indices, values


def search_qdrant(
    dense_vector: list[float],
    sparse_indices: list[int],
    sparse_values: list[float],
    mode: str,
    limit: int = 10,
) -> tuple[list[dict], float]:
    """Напрямую вызвать Qdrant в нужном режиме. Возвращает (results, latency_ms)."""
    from qdrant_client import QdrantClient, models

    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url)
    collection = settings.qdrant_collection_alias

    # Фильтр: только русскоязычные
    query_filter = models.Filter(must=[
        models.FieldCondition(key="language", match=models.MatchValue(value="ru"))
    ])

    t0 = time.perf_counter()

    if mode == "dense_only":
        # Только плотный вектор — семантический поиск
        results = client.query_points(
            collection_name=collection,
            query=dense_vector,
            using="dense",
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

    elif mode == "sparse_only":
        # Только разреженный вектор — лексический поиск (TF-IDF)
        if not sparse_indices:
            return [], 0.0
        results = client.query_points(
            collection_name=collection,
            query=models.SparseVector(indices=sparse_indices, values=sparse_values),
            using="sparse",
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

    else:  # hybrid
        # Оба вектора + RRF fusion
        prefetches = [
            models.Prefetch(query=dense_vector, using="dense", limit=limit),
        ]
        if sparse_indices:
            prefetches.append(
                models.Prefetch(
                    query=models.SparseVector(indices=sparse_indices, values=sparse_values),
                    using="sparse",
                    limit=limit,
                )
            )
        results = client.query_points(
            collection_name=collection,
            prefetch=prefetches,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

    latency_ms = (time.perf_counter() - t0) * 1000

    rows = []
    for point in results.points:
        p = point.payload or {}
        rows.append({
            "score": round(point.score, 4),
            "source_name": p.get("source_name", "?"),
            "title": (p.get("title") or "")[:60],
            "news_id": p.get("news_id"),
        })
    return rows, latency_ms


def run_one(query: str, mode: str) -> dict:
    """Прогнать один запрос в одном режиме."""
    try:
        dense, sparse_idx, sparse_val = encode_query(query)
    except Exception as exc:
        return {"query": query[:40], "mode": mode, "error": str(exc),
                "latency_ms": 0, "results": 0, "sources": "", "top_source": "ERROR", "avg_score": 0.0}

    try:
        results, latency_ms = search_qdrant(dense, sparse_idx, sparse_val, mode)
    except Exception as exc:
        return {"query": query[:40], "mode": mode, "error": str(exc),
                "latency_ms": 0, "results": 0, "sources": "", "top_source": "ERROR", "avg_score": 0.0}

    if not results:
        return {"query": query[:40], "mode": mode, "error": "no_results",
                "latency_ms": int(latency_ms), "results": 0, "sources": "", "top_source": "—", "avg_score": 0.0}

    source_counter = Counter(r["source_name"] for r in results)
    unique_sources = len(source_counter)
    top_source = source_counter.most_common(1)[0][0]
    sources_list = ", ".join(s for s, _ in source_counter.most_common(3))
    avg_score = round(sum(r["score"] for r in results) / len(results), 4)

    return {
        "query": query[:40] + ("..." if len(query) > 40 else ""),
        "mode": mode,
        "error": "",
        "latency_ms": int(latency_ms),
        "results": len(results),
        "unique_sources": unique_sources,
        "top_source": top_source,
        "sources_top3": sources_list,
        "avg_score": avg_score,
        "top3_titles": " | ".join(r["title"] for r in results[:3]),
    }


def main() -> None:
    all_rows: list[dict] = []
    total = len(QUERIES) * len(MODES)
    done = 0

    print(f"Retrieval Ablation: {len(QUERIES)} zaprosov x {len(MODES)} rezhima = {total}")
    print("=" * 65)

    # Преднагреваем модель одним запросом
    print("Загрузка embedding-модели...", flush=True)
    try:
        encode_query("тест")
        print("Модель загружена.", flush=True)
    except Exception as e:
        print(f"Ошибка загрузки модели: {e}")
        return

    for query in QUERIES:
        print(f"\nЗапрос: {query[:55]}")
        for mode in MODES:
            done += 1
            row = run_one(query, mode)
            all_rows.append(row)
            src = row.get("sources_top3", row.get("top_source", "?"))
            print(f"  [{done:2d}/{total}] {mode:<12} | {row['latency_ms']:5d}ms "
                  f"| {row.get('unique_sources', 0)} источн. "
                  f"| avg_score={row.get('avg_score', 0):.3f} "
                  f"| {src}", flush=True)

    # ── CSV ───────────────────────────────────────────────────────────────────
    out_dir = Path(__file__).parent.parent / "docs"
    out_dir.mkdir(exist_ok=True)

    csv_path = out_dir / "retrieval_ablation.csv"
    fields = ["query", "mode", "latency_ms", "results", "unique_sources",
              "top_source", "sources_top3", "avg_score", "top3_titles", "error"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nCSV: {csv_path}")

    # ── Сводная таблица по режимам ────────────────────────────────────────────
    from collections import defaultdict
    stats: dict[str, dict] = defaultdict(lambda: {
        "lat_sum": 0, "src_sum": 0, "score_sum": 0.0, "res_sum": 0, "n": 0
    })
    for r in all_rows:
        if r.get("error"):
            continue
        s = stats[r["mode"]]
        s["lat_sum"] += r["latency_ms"]
        s["src_sum"] += r.get("unique_sources", 0)
        s["score_sum"] += r.get("avg_score", 0.0)
        s["res_sum"] += r.get("results", 0)
        s["n"] += 1

    # ── Markdown ──────────────────────────────────────────────────────────────
    mode_label = {"dense_only": "Dense-only (семантический)", "sparse_only": "Sparse-only (лексический)", "hybrid": "Hybrid RRF (dense + sparse)"}

    lines = [
        "# Ablation Study: Retrieval-режимы",
        "",
        "**Сравнение:** Dense-only (BGE-M3) vs Sparse-only (TF-IDF) vs Hybrid RRF",
        f"**Запросов:** {len(QUERIES)}  **Режимов:** {len(MODES)}",
        "",
        "## Сводная таблица",
        "",
        "| Режим | Ср. задержка (мс) | Ср. уникальных источников | Ср. score | Ср. найдено |",
        "|-------|------------------|--------------------------|-----------|-------------|",
    ]

    for mode in MODES:
        s = stats[mode]
        n = s["n"] or 1
        lines.append(
            f"| {mode_label.get(mode, mode)} "
            f"| {s['lat_sum']//n} "
            f"| {round(s['src_sum']/n, 1)} "
            f"| {round(s['score_sum']/n, 3)} "
            f"| {round(s['res_sum']/n, 1)} |"
        )

    lines += ["", "## Детальные результаты", "",
              "| Запрос | Режим | Задержка | Источников | Топ источники | avg_score |",
              "|--------|-------|----------|-----------|---------------|-----------|"]

    for r in all_rows:
        lines.append(
            f"| {r['query']} | {r['mode']} | {r['latency_ms']}ms "
            f"| {r.get('unique_sources','?')} | {r.get('sources_top3', r.get('error','?'))} "
            f"| {r.get('avg_score', 0):.3f} |"
        )

    lines += [
        "",
        "## Выводы",
        "",
        "- **Dense-only**: находит семантически близкие документы, хорошо для широких тематических запросов.",
        "- **Sparse-only**: точный лексический поиск, хорошо для запросов с именованными сущностями и точными терминами.",
        "- **Hybrid RRF**: объединяет оба сигнала через RRF, как правило даёт большее разнообразие источников.",
        "",
        "*Sparse = TF-IDF приближение через хэши токенов (не нативный BGE-M3 sparse, т.к. Python 3.12)*",
        "*Dense = BAAI/bge-m3, 1024-dim, cosine similarity*",
        "*Hybrid = Qdrant Query API с двумя Prefetch + FusionQuery(RRF)*",
    ]

    md_path = out_dir / "retrieval_ablation.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Markdown: {md_path}")

    print("\n" + "=" * 65)
    print("ИТОГ:")
    print(f"{'Режим':<28} {'Задержка':>10} {'Источников':>12} {'avg_score':>10}")
    print("-" * 65)
    for mode in MODES:
        s = stats[mode]
        n = s["n"] or 1
        print(f"{mode_label.get(mode, mode):<28} "
              f"{s['lat_sum']//n:>8}ms "
              f"{round(s['src_sum']/n,1):>11} "
              f"{round(s['score_sum']/n,3):>10}")
    print("=" * 65)


if __name__ == "__main__":
    main()
