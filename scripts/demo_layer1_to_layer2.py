#!/usr/bin/env python
r"""
Наглядная демонстрация полного пути статьи: Layer 1 -> Layer 2

Запуск:
    cd c:\code\diplom
    .venv\Scripts\python scripts\demo_layer1_to_layer2.py

Что показывает:
    1. Layer 1: сбор новостей из RSS -> запись в БД (processed=false)
    2. Layer 2: обработка -> NER, topics, keywords, chunks, embeddings -> Qdrant
    3. Результаты: сущности, темы, кластеры, граф знаний
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

# ===== Настройка путей =====
sys.path.insert(0, "src")

from sqlalchemy import func, select
from jarvis.db.models import (
    Chunk, Entity, News, NewsEntity, NewsTopic, Source, Topic,
    EntityCooccurrence, TermVocabulary, Collocation,
)
from jarvis.db.session import SyncSessionLocal
from jarvis.core.logging import configure_logging
from jarvis.core.settings import get_settings
from jarvis.processing.services.process_batch import process_pending_news_batch
from jarvis.processing.services.select_batch import load_unprocessed_batch

configure_logging()
settings = get_settings()

# ===== Цвета для консоли =====
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

def print_section(title: str):
    """Печатает заголовок секции."""
    width = 70
    print(f"\n{'=' * width}")
    print(f"  {Colors.BOLD}{Colors.CYAN}{title}{Colors.RESET}")
    print(f"{'=' * width}")

def print_step(num: int, title: str):
    """Печатает номер шага."""
    print(f"\n{Colors.YELLOW}┌─ Шаг {num}: {title}{Colors.RESET}")

def print_result(label: str, value, indent: int = 4):
    """Печатает результат."""
    prefix = " " * indent
    print(f"{prefix}{Colors.DIM}{label}:{Colors.RESET} {value}")

def print_success(msg: str):
    print(f"  {Colors.GREEN}✅ {msg}{Colors.RESET}")

def print_info(msg: str):
    print(f"  {Colors.BLUE}ℹ️  {msg}{Colors.RESET}")

def print_warning(msg: str):
    print(f"  {Colors.YELLOW}⚠️  {msg}{Colors.RESET}")


def get_db_stats() -> dict:
    """Получить статистику БД."""
    with SyncSessionLocal() as session:
        total_news = session.scalar(select(func.count()).select_from(News))
        processed_news = session.scalar(
            select(func.count()).select_from(News).where(News.processed.is_(True))
        )
        unprocessed_news = session.scalar(
            select(func.count()).select_from(News).where(News.processed.is_(False))
        )
        total_entities = session.scalar(select(func.count()).select_from(Entity))
        total_chunks = session.scalar(select(func.count()).select_from(Chunk))
        total_topics = session.scalar(select(func.count()).select_from(NewsTopic))
        total_coocc = session.scalar(select(func.count()).select_from(EntityCooccurrence))
        total_vocabulary = session.scalar(select(func.count()).select_from(TermVocabulary))
        total_collocations = session.scalar(select(func.count()).select_from(Collocation))

        # Источники
        active_sources = session.scalar(
            select(func.count()).select_from(Source).where(Source.is_active.is_(True))
        )

        return {
            "total_news": total_news or 0,
            "processed_news": processed_news or 0,
            "unprocessed_news": unprocessed_news or 0,
            "total_entities": total_entities or 0,
            "total_chunks": total_chunks or 0,
            "total_topics": total_topics or 0,
            "total_coocc": total_coocc or 0,
            "total_vocabulary": total_vocabulary or 0,
            "total_collocations": total_collocations or 0,
            "active_sources": active_sources or 0,
        }


def show_article_details(news_id: int):
    """Показать детальную информацию об одной статье после обработки."""
    with SyncSessionLocal() as session:
        news = session.get(News, news_id)
        if not news:
            print_warning(f"Статья #{news_id} не найдена")
            return

        print(f"\n  {Colors.BOLD}📰 Статья #{news_id}{Colors.RESET}")
        print(f"    {Colors.DIM}Заголовок:{Colors.RESET} {news.title[:80]}...")
        print(f"    {Colors.DIM}Источник:{Colors.RESET} {news.source_id}")
        print(f"    {Colors.DIM}Дата публикации:{Colors.RESET} {news.published_at}")
        print(f"    {Colors.DIM}Content grade:{Colors.RESET} {news.content_grade}")
        print(f"    {Colors.DIM}Uncertain:{Colors.RESET} {news.is_uncertain}")
        print(f"    {Colors.DIM}Cluster ID:{Colors.RESET} {news.event_cluster_id}")

        processing_info = (news.extra or {}).get("processing", {})
        if processing_info:
            print(f"    {Colors.DIM}Processing:{Colors.RESET}")
            for key, val in processing_info.items():
                print(f"      {Colors.DIM}{key}:{Colors.RESET} {val}")

        # Topics
        topic_results = session.execute(
            select(Topic.name, NewsTopic.confidence)
            .join(NewsTopic, Topic.id == NewsTopic.topic_id)
            .where(NewsTopic.news_id == news_id)
        ).all()
        if topic_results:
            print(f"    {Colors.DIM}Темы ({len(topic_results)}):{Colors.RESET}")
            for topic_name, conf in topic_results:
                print(f"      📌 {topic_name} (confidence={conf:.2f})")

        # Simpler: just show news_topics count
        topic_count = session.scalar(
            select(func.count()).select_from(NewsTopic).where(NewsTopic.news_id == news_id)
        )

        # Entities
        entities = session.execute(
            select(Entity.name, Entity.type, NewsEntity.mention_count)
            .join(NewsEntity, Entity.id == NewsEntity.entity_id)
            .where(NewsEntity.news_id == news_id)
        ).all()
        if entities:
            print(f"    {Colors.DIM}Сущности ({len(entities)}):{Colors.RESET}")
            for name, etype, mcount in entities[:10]:
                type_icon = {"person": "👤", "organization": "🏢", "location": "📍"}.get(etype, "❓")
                print(f"      {type_icon} {name} ({etype}, {mcount}x)")

        # Chunks
        chunks = session.scalars(
            select(Chunk).where(Chunk.news_id == news_id).order_by(Chunk.chunk_index)
        ).all()
        if chunks:
            print(f"    {Colors.DIM}Чанки ({len(chunks)}):{Colors.RESET}")
            for ch in chunks:
                preview = ch.lemma_text[:60] if ch.lemma_text else ch.text[:60] if ch.text else ""
                print(f"      [{ch.zone}] #{ch.chunk_index}: {preview}...")


def run_demo():
    """Запустить полную демонстрацию."""
    print(f"""
{Colors.BOLD}{Colors.CYAN}
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║     🤖  JARVIS — Демонстрация Layer 1 → Layer 2         ║
║                                                          ║
║     Полный путь статьи от сбора до индексирования         ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
{Colors.RESET}
    """)

    # === СТАРТ: Статистика до запуска ===
    print_section("📊 Начальное состояние базы данных")
    stats_before = get_db_stats()
    print_result("Активных источников", stats_before["active_sources"])
    print_result("Всего статей", stats_before["total_news"])
    print_result("  ├─ Обработанных (processed=true)", stats_before["processed_news"])
    print_result("  └─ Необработанных (processed=false)", stats_before["unprocessed_news"])
    print_result("Сущностей (NER)", stats_before["total_entities"])
    print_result("Чанков в Qdrant", stats_before["total_chunks"])
    print_result("Рёбер графа знаний", stats_before["total_coocc"])
    print_result("Словарь терминов", stats_before["total_vocabulary"])
    print_result("Коллокации", stats_before["total_collocations"])

    # === ШАГ 1: Сбор данных (Layer 1) ===
    print_section("📥 Шаг 1: Layer 1 — Сбор данных из RSS")

    print_step(1, "Сбор новостей из RSS-источников")
    print_info("Запускаем сбор из 1-2 источников для демонстрации")

    # Проверяем доступные источники
    with SyncSessionLocal() as session:
        sources = session.scalars(
            select(Source).where(Source.is_active.is_(True)).limit(18)
        ).all()

    if not sources:
        print_warning("Нет активных источников! Нужно запустить seed.")
        print_info("Запусти: cd c:\\code\\diplom && alembic upgrade head")
        return

    for src in sources:
        print_result(f"Источник '{src.name}'", f"type={src.type}, priority={src.priority}")

    print_info(f"\nВсего доступно источников: {len(sources)}")
    print_info("Запуск Celery worker для сбора...")
    print_warning("Для запуска сбора данных открой ДРУГОЙ терминал и выполни:")
    print(f"  {Colors.BOLD}celery -A jarvis.ingestion.tasks.celery_app worker --loglevel=info -Q collector_queue{Colors.RESET}")
    print(f"  {Colors.BOLD}celery -A jarvis.ingestion.tasks.celery_app beat --loglevel=info{Colors.RESET}")

    print_info("\nИли запусти CLI вручную:")
    print(f"  {Colors.BOLD}cd c:\\code\\diplom && .venv\\Scripts\\python -m jarvis.ingestion.cli.run_source --source ТАСС{Colors.RESET}")

    print_info("\n⏳ После сбора данных нажми Enter для продолжения...")

    # Ждём ввод пользователя
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass

    # === ШАГ 2: Проверка данных после Layer 1 ===
    print_section("📋 Шаг 2: Проверка данных после Layer 1")

    stats_after_layer1 = get_db_stats()
    new_articles = stats_after_layer1["total_news"] - stats_before["total_news"]

    print_result("Статей после сбора", stats_after_layer1["total_news"])
    print_result("Новых статей", f"+{new_articles}" if new_articles > 0 else "0 (сбор ещё не запущен)")
    print_result("Необработанных (Layer 2 ещё не работал)", stats_after_layer1["unprocessed_news"])

    if stats_after_layer1["unprocessed_news"] == 0:
        print_warning("Нет необработанных статей!")
        print_info("Возможно все статьи уже обработаны или сбор ещё не запускался.")
        print_info("Покажу последние 3 статьи в БД:")

        with SyncSessionLocal() as session:
            last_news = session.scalars(
                select(News).order_by(News.ingested_at.desc()).limit(3)
            ).all()
            for news in last_news:
                status_icon = "✅" if news.processed else "⏳"
                print(f"  {status_icon} #{news.id}: {news.title[:60]}... ({'processed' if news.processed else 'pending'})")
    else:
        # Показать последние необработанные статьи
        print_info("\nПоследние 5 необработанных статей:")
        with SyncSessionLocal() as session:
            pending = session.scalars(
                select(News).where(News.processed.is_(False))
                .order_by(News.ingested_at.desc()).limit(5)
            ).all()
            for news in pending:
                print(f"  ⏳ #{news.id}: {news.title[:60]}...")

    # === ШАГ 3: Обработка (Layer 2) ===
    print_section("⚙️  Шаг 3: Layer 2 — Обработка и индексирование")

    if stats_after_layer1["unprocessed_news"] > 0:
        print_step(3, f"Обработка батча ({min(stats_after_layer1['unprocessed_news'], 16)} статей)")

        t0 = time.time()
        result = process_pending_news_batch(limit=min(stats_after_layer1["unprocessed_news"], 16))
        elapsed = time.time() - t0

        print_success(f"Батч обработан за {elapsed:.1f} сек")
        print_result("Выбрано статей", result.selected_count)
        print_result("Обработано", result.processed_count)
        print_result("Пропущено", result.skipped_count)
        print_result("Ошибки", result.failed_count)

        if result.processed_news_ids:
            print_info("\nОбработанные статьи:")
            for nid in result.processed_news_ids[:5]:
                show_article_details(nid)
    else:
        print_info("Нет статей для обработки.")
        print_info("Если хочешь обработать конкретную статью:")
        print(f"  {Colors.BOLD}python -c \"from jarvis.processing.services.process_article import process_one_news_article; process_one_news_article(42)\"{Colors.RESET}")

    # === ШАГ 4: Финальная статистика ===
    print_section("📊 Финальное состояние")

    stats_after = get_db_stats()
    print_result("Всего статей", stats_after["total_news"])
    print_result("Обработанных", stats_after["processed_news"])
    print_result("Необработанных", stats_after["unprocessed_news"])
    print_result("Сущностей (NER)", stats_after["total_entities"])
    print_result("Чанков в Qdrant", stats_after["total_chunks"])
    print_result("Назначений тем", stats_after["total_topics"])
    print_result("Рёбер графа знаний", stats_after["total_coocc"])
    print_result("Словарь терминов", stats_after["total_vocabulary"])
    print_result("Коллокации", stats_after["total_collocations"])

    # === ШАГ 5: Топ сущностей ===
    print_section("🏆 Топ-10 сущностей по упоминаниям")

    with SyncSessionLocal() as session:
        top_entities = session.execute(
            select(Entity.name, Entity.type, Entity.mention_count)
            .order_by(Entity.mention_count.desc())
            .limit(10)
        ).all()

    if top_entities:
        for name, etype, count in top_entities:
            icon = {"person": "👤", "organization": "🏢", "location": "📍"}.get(etype, "❓")
            bar = "█" * min(count, 40)
            print(f"  {icon} {name:30s} {bar} ({count})")
    else:
        print_info("Сущностей пока нет — нужно больше статей.")

    # === ШАГ 6: Топ тем ===
    print_section("📂 Топ тем")

    with SyncSessionLocal() as session:
        from jarvis.db.models import Topic
        topic_counts = session.execute(
            select(Topic.name, func.count(NewsTopic.news_id).label('cnt'))
            .join(NewsTopic, Topic.id == NewsTopic.topic_id)
            .group_by(Topic.name)
            .order_by(func.count(NewsTopic.news_id).desc())
            .limit(10)
        ).all()

    if topic_counts:
        for name, count in topic_counts:
            bar = "█" * min(count * 2, 40)
            print(f"  📌 {name:30s} {bar} ({count})")
    else:
        print_info("Тем пока нет.")

    # === ШАГ 7: Граф знаний ===
    print_section("🕸️  Граф знаний (co-occurrences)")

    with SyncSessionLocal() as session:
        top_coocc = session.execute(
            select(EntityCooccurrence.entity_a_id, EntityCooccurrence.entity_b_id,
                   EntityCooccurrence.co_mention_count)
            .order_by(EntityCooccurrence.co_mention_count.desc())
            .limit(10)
        ).all()

    if top_coocc:
        for a_id, b_id, count in top_coocc:
            entity_a = session.get(Entity, a_id)
            entity_b = session.get(Entity, b_id)
            if entity_a and entity_b:
                print(f"  {entity_a.name:25s} ──[{count}x]──  {entity_b.name}")
    else:
        print_info("Рёбер графа пока нет — нужно больше статей с несколькими сущностями.")

    # === ШАГ 8: Qdrant ===
    print_section("🔍 Qdrant — векторный индекс")

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=settings.qdrant_url)
        collections = client.get_collections()

        if collections.collections:
            for col in collections.collections:
                info = client.get_collection(col.name)
                print_result(f"Коллекция '{col.name}'", f"{info.points_count} точек")
        else:
            print_info("Коллекций в Qdrant пока нет.")
    except Exception as exc:
        print_warning(f"Не удалось подключиться к Qdrant: {exc}")
        print_info("Убедись что Qdrant запущен: docker ps | grep qdrant")

    # === ФИНАЛ ===
    print_section("🎉 Демонстрация завершена!")

    print("""
{GREEN}Что дальше:{RESET}

  1. {BOLD}Запустить полный сбор данных:{RESET}
     celery -A jarvis.ingestion.tasks.celery_app worker -Q collector_queue &
     celery -A jarvis.ingestion.tasks.celery_app beat &

  2. {BOLD}Запустить обработку (Layer 2):{RESET}
     celery -A jarvis.ingestion.tasks.celery_app worker -Q processing_queue &

  3. {BOLD}Проверить Qdrant:{RESET}
     Открой http://localhost:6333/dashboard в браузере

  4. {BOLD}Перейти к Слою 3 (Hybrid Retrieval):{RESET}
     Когда накопишь достаточно данных в Qdrant

{DIM}Слой 2 полностью реализован! ✅{RESET}
    """.format(GREEN=Colors.GREEN, BOLD=Colors.BOLD, RESET=Colors.RESET,
               DIM=Colors.DIM))


if __name__ == "__main__":
    try:
        run_demo()
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}⏹️  Демонстрация прервана пользователем{Colors.RESET}")
    except Exception as exc:
        print(f"\n\n{Colors.RED}❌ Ошибка: {exc}{Colors.RESET}")
        import traceback
        traceback.print_exc()
