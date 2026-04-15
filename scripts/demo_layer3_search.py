#!/usr/bin/env python
r"""
Наглядный тест Слоя 3 — Hybrid Retrieval

Запуск:
    cd c:\code\diplom
    .venv\Scripts\activate
    python scripts\demo_layer3_search.py

Что показывает:
    1. Preprocessing запроса (лемматизация, intent, embedding)
    2. Autocorrect (если есть опечатки)
    3. Retrieval (dense + sparse -> RRF)
    4. Reranking (cross-encoder)
    5. Финальные результаты с объяснениями
"""

from __future__ import annotations

import sys
sys.path.insert(0, "src")

# ===== Цвета =====
class C:
    H = '\033[95m'
    B = '\033[94m'
    C = '\033[96m'
    G = '\033[92m'
    Y = '\033[93m'
    R = '\033[91m'
    D = '\033[2m'
    BOLD = '\033[1m'
    END = '\033[0m'

def section(title):
    print(f"\n{C.H}{'=' * 60}")
    print(f"  {C.BOLD}{title}{C.END}")
    print(f"{C.H}{'=' * 60}{C.END}")

def step(num, title):
    print(f"\n{C.Y}  [Шаг {num}] {C.BOLD}{title}{C.END}")

def info(label, value):
    print(f"    {C.D}{label}:{C.END} {value}")

def result_item(n, item):
    print(f"\n    {C.G}#{n}. {C.BOLD}{item['title']}{C.END}")
    print(f"       {C.D}Источник:{C.END} {item.get('source_name', '?')}")
    print(f"       {C.D}Оценка:{C.END} {item.get('score', 0):.4f}")
    if item.get('rerank_score') is not None:
        print(f"       {C.D}Rerank:{C.END} {item['rerank_score']:.4f}")
    if item.get('topics'):
        print(f"       {C.D}Темы:{C.END} {', '.join(item['topics'][:3])}")
    if item.get('entities'):
        print(f"       {C.D}Сущности:{C.END} {', '.join(item['entities'][:3])}")
    if item.get('explanation'):
        print(f"       {C.D}Почему:{C.END} {item['explanation']}")
    if item.get('snippet'):
        snippet = item['snippet'][:120]
        print(f"       {C.D}Сниппет:{C.END} {snippet}...")

# ===== Запуск =====
section("🔍 JARVIS — Тест Слоя 3: Hybrid Retrieval")

# Запрос пользователя
test_queries = [
    "ключевая ставка ЦБ",
    "Что произошло с экономикой",
    "прогноз по рублю",
    "Путин встретился",
]

print(f"\n{C.C}Введите запрос (или номер 1-4, или Enter для первого):{C.END}")
print(f"  1. ключевая ставка ЦБ")
print(f"  2. Что произошло с экономикой")
print(f"  3. прогноз по рублю")
print(f"  4. Путин встретился")

try:
    user_input = input(f"\n{C.C}> {C.END}").strip()
except (EOFError, KeyboardInterrupt):
    user_input = "1"

if user_input.isdigit() and 1 <= int(user_input) <= 4:
    query = test_queries[int(user_input) - 1]
elif user_input:
    query = user_input
else:
    query = test_queries[0]

print(f"\n{C.BOLD}Запрос:{C.END} {query}")

# ===== Шаг 1: Autocorrect =====
step(1, "Autocorrect")
from jarvis.retrieval.services.query_autocorrect import autocorrect_query
ac_result = autocorrect_query(query)
if ac_result.was_corrected:
    print(f"    {C.G}✅ Исправлено:{C.END} {ac_result.original} → {ac_result.corrected}")
    query = ac_result.corrected
else:
    print(f"    {C.D}Опечаток не обнаруено{C.END}")

# ===== Шаг 2: Preprocessing =====
step(2, "Query Preprocessing")
from jarvis.retrieval.services.query_preprocessing import preprocess_query
ctx = preprocess_query(query)
info("Лемма", ctx.lemma[:80])
info("Intent", f"{ctx.intent.intent} (confidence={ctx.intent.confidence})")
info("Dense dim", len(ctx.dense_vector))
info("Sparse dims", f"{len(ctx.sparse_indices)} non-zero")

# ===== Шаг 3: Retrieval =====
step(3, "Retrieval (Qdrant: dense + sparse → RRF)")
from jarvis.retrieval.services.qdrant_search import QdrantSearchService
qdrant = QdrantSearchService()
raw_results = qdrant.search(
    dense_vector=ctx.dense_vector,
    sparse_indices=ctx.sparse_indices,
    sparse_values=ctx.sparse_values,
    limit=10,
)
print(f"    {C.G}Найдено чанков:{C.END} {len(raw_results)}")
if raw_results:
    print(f"    {C.D}Лучший score (RRF):{C.END} {raw_results[0].score:.4f}")
    print(f"    {C.D}Худший score (RRF):{C.END} {raw_results[-1].score:.4f}")

# ===== Шаг 4: Reranking =====
step(4, "Reranking (bge-reranker-v2-m3)")
from jarvis.retrieval.services.reranking import RerankingService
reranker = RerankingService()
reranked = reranker.rerank(query, raw_results)
print(f"    {C.G}Переранжировано:{C.END} {len(reranked)}")
if reranked:
    print(f"    {C.D}Лучший rerank score:{C.END} {reranked[0].rerank_score:.4f}")
    print(f"    {C.D}Худший rerank score:{C.END} {reranked[-1].rerank_score:.4f}")

# ===== Шаг 5: Результаты =====
section("📊 Финальные результаты (top-5)")

for i, item in enumerate(reranked[:5], 1):
    r = item.result
    result_item(i, {
        "title": r.title[:80],
        "source_name": r.source_name,
        "score": item.rerank_score,
        "rerank_score": round(item.rerank_score, 4),
        "topics": r.topics[:3],
        "entities": r.entities[:3],
        "explanation": f"zone={r.zone}, grade={r.content_grade}",
        "snippet": (r.snippet_lead or r.text or "")[:120],
    })

# ===== Итого =====
section("📈 Итог")
info("Запрос", query)
info("Intent", ctx.intent.intent)
info("Всего найдено", len(raw_results))
info("После reranking", len(reranked))
info("Показано top", min(5, len(reranked)))
