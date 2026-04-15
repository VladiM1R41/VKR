"""Быстрый сбор новостей от всех 18 источников + NLP-обработка.

Запуск (из c:/code/diplom):
    .venv/Scripts/python scripts/collect_all_sources.py

Не требует Celery-воркера — вызывает collect_source напрямую.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.core.settings import get_settings
get_settings.cache_clear()

from jarvis.ingestion.services.collect_source import run_collect_source

# Источники в порядке приоритета (самые быстрые и богатые — первыми)
SOURCES = [
    "ТАСС",
    "РИА Новости",
    "РБК",
    "Lenta.ru",
    "BFM.ru",
    "RT на русском",
    "МК",
    "Коммерсантъ news",
    "Ведомости news",
    "CNews",
    "Life.ru",
    "АиФ news",
    "iXBT.com",
    "Хабр",
    "Коммерсантъ corp",
    "Ведомости articles",
    "Коммерсантъ main",
    "АиФ articles",
]

def main() -> None:
    total_new = 0
    total_sources = 0
    failed = []

    print(f"Сбор новостей от {len(SOURCES)} источников...")
    print("=" * 55)

    for i, source_name in enumerate(SOURCES, 1):
        print(f"\n[{i}/{len(SOURCES)}] {source_name}...", flush=True)
        t0 = time.perf_counter()
        try:
            result = run_collect_source(source_name)
            elapsed = round(time.perf_counter() - t0, 1)
            new_count = result.get("items_new", 0)
            total_new += new_count
            total_sources += 1
            status = result.get("status", "?")
            print(f"  OK  {new_count} новых | {elapsed}s | {status}", flush=True)
        except Exception as exc:
            elapsed = round(time.perf_counter() - t0, 1)
            print(f"  ERR {exc} | {elapsed}s", flush=True)
            failed.append(source_name)

    print("\n" + "=" * 55)
    print(f"Собрано: {total_new} новых статей из {total_sources} источников")
    if failed:
        print(f"Ошибки ({len(failed)}): {', '.join(failed)}")

    # --- NLP-обработка (Layer 2) ---
    print("\nЗапуск NLP-пайплайна (чанки + embeddings + Qdrant)...")
    print("Это может занять 5-10 минут...", flush=True)

    try:
        from jarvis.processing.services.process_batch import process_pending_news_batch

        batch_size = 200
        processed_total = 0
        rounds = 0

        while rounds < 10:
            result = process_pending_news_batch(limit=batch_size)
            n = getattr(result, "processed_count", 0) or (result if isinstance(result, int) else 0)
            if n == 0:
                break
            processed_total += n
            rounds += 1
            print(f"  Раунд {rounds}: обработано {n} статей (всего {processed_total})", flush=True)

        print(f"\nNLP завершён: {processed_total} статей обработано")
    except Exception as exc:
        print(f"NLP ошибка: {exc}")
        print("Запусти вручную:")
        print("  python -c \"import sys; sys.path.insert(0,'src'); from jarvis.processing.services.process_batch import process_pending_news_batch; r=process_pending_news_batch(limit=200); print(r)\"")

    print("\nГотово! Теперь очисти кэш Redis и перезапусти ablation:")
    print("  docker exec jarvis-redis redis-cli FLUSHDB")
    print("  python scripts/run_ablation.py")

if __name__ == "__main__":
    main()
