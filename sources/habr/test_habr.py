"""
Пошаговый тест сбора с Хабра.

Запуск: python sources/habr/test_habr.py

Этот скрипт НЕ использует базу данных и Celery.
Он показывает каждый шаг сбора «голым» кодом,
чтобы было понятно что происходит под капотом.

Зависимости: pip install httpx feedparser trafilatura
"""

import asyncio
import calendar
import hashlib
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import feedparser
import httpx
import trafilatura

# ─── Конфигурация ────────────────────────────────────────────────────────────

RSS_URL = "https://habr.com/ru/rss/articles/?fl=ru&limit=100&with_hubs=true"
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 10.0  # секунд между запросами (robots.txt Crawl-delay: 10)

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    """
    Привести URL к каноническому виду для дедупликации.

    Убираем: UTM-параметры, www, trailing slash, fragment.
    Схему приводим к https.

    Пример:
    "https://habr.com/ru/articles/1019062/?utm_source=habrahabr&utm_campaign=1019062"
    → "https://habr.com/ru/articles/1019062"
    """
    try:
        p = urlparse(url)
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        # Убрать UTM и трекинговые параметры
        params = {
            k: v for k, v in parse_qs(p.query).items()
            if not k.startswith(("utm_", "fbclid", "gclid", "yclid"))
        }
        query = urlencode(params, doseq=True)
        return urlunparse(("https", host, path, "", query, ""))
    except Exception:
        return url


def title_hash(title: str) -> str:
    """MD5 от нормализованного заголовка — для дедупликации по title."""
    normalized = " ".join(title.lower().split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def parse_date(entry) -> datetime | None:
    """
    Извлечь дату публикации из RSS-записи.

    ВАЖНО: calendar.timegm() интерпретирует struct_time как UTC.
    time.mktime() интерпретирует как локальное время — это баг.
    Хабр публикует pubDate в GMT (= UTC), поэтому calendar.timegm() корректен.
    """
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            ts = calendar.timegm(parsed)  # UTC, не mktime!
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


# ─── Шаги сбора ──────────────────────────────────────────────────────────────

async def step1_fetch_rss() -> tuple[bytes | None, dict]:
    """
    Шаг 1: Скачать RSS-фид.

    Используем условный запрос (If-None-Match / If-Modified-Since).
    Если сервер вернул 304 — фид не изменился, новых статей нет.
    Сохраняем ETag и Last-Modified для следующего запроса.
    """
    print("\n" + "="*60)
    print("ШАГ 1: Загрузка RSS-фида")
    print("="*60)
    print(f"URL: {RSS_URL}")

    headers = {"User-Agent": USER_AGENT}
    # Если бы у нас был ETag от предыдущего запроса — добавили бы:
    # headers["If-None-Match"] = "прошлый_etag"
    # headers["If-Modified-Since"] = "прошлый_modified"

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(RSS_URL, headers=headers)

    print(f"\nHTTP статус: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type', '—')}")
    print(f"ETag: {response.headers.get('etag', 'не поддерживается')}")
    print(f"Last-Modified: {response.headers.get('last-modified', 'не поддерживается')}")
    print(f"Размер ответа: {len(response.content):,} байт")

    if response.status_code == 304:
        print("\n→ 304 Not Modified: фид не изменился, нечего парсить")
        return None, {}

    response.raise_for_status()

    cache_info = {
        "etag": response.headers.get("etag"),
        "modified": response.headers.get("last-modified"),
    }
    print(f"\n→ Фид загружен, ETag для следующего запроса: {cache_info['etag']}")
    return response.content, cache_info


def step2_parse_rss(raw_content: bytes) -> list[dict]:
    """
    Шаг 2: Распарсить RSS через feedparser.

    Показываем структуру записи: какие поля есть и что в них.
    """
    print("\n" + "="*60)
    print("ШАГ 2: Парсинг RSS")
    print("="*60)

    feed = feedparser.parse(raw_content)

    print(f"Записей в фиде: {len(feed.entries)}")

    if not feed.entries:
        print("→ Фид пустой или не распарсился")
        return []

    # Покажем структуру первой записи подробно
    first = feed.entries[0]
    print("\n--- Структура первой записи ---")
    print(f"title:     {first.get('title', '—')}")
    print(f"link:      {first.get('link', '—')}")
    print(f"id (guid): {first.get('id', '—')}")
    print(f"published: {first.get('published', '—')}")
    print(f"author:    {first.get('author', '—')}")

    # Теги (category)
    tags = [t.get("term", "") for t in first.get("tags", [])]
    print(f"tags:      {tags[:5]} {'...' if len(tags) > 5 else ''}")

    # Контент
    summary = first.get("summary", "")
    content_encoded = first.get("content", [])
    print(f"\nsummary длина: {len(summary)} символов")
    print(f"content:encoded: {'есть, длина ' + str(len(content_encoded[0].get('value',''))) if content_encoded else 'НЕТ'}")
    print(f"\nПервые 200 символов summary:")
    print(repr(summary[:200]))

    # Спойлер: summary это только лид, полного текста нет
    if not content_encoded:
        print("\n⚠️  content:encoded отсутствует — нужно идти за полным текстом на сайт")

    # Собираем данные по всем записям
    articles = []
    for entry in feed.entries:
        # Берём URL из guid (он без UTM), не из link
        raw_url = entry.get("id") or entry.get("link", "")
        can_url = canonical_url(raw_url)
        pub_date = parse_date(entry)

        articles.append({
            "url": raw_url,
            "canonical_url": can_url,
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),
            "published_at": pub_date,
            "author": entry.get("author", ""),
            "tags": [t.get("term", "") for t in entry.get("tags", [])],
        })

    print(f"\n→ Извлечено записей: {len(articles)}")
    print("\nПервые 5 заголовков:")
    for a in articles[:5]:
        date_str = a["published_at"].strftime("%Y-%m-%d %H:%M UTC") if a["published_at"] else "нет даты"
        print(f"  [{date_str}] {a['title'][:60]}")

    return articles


async def step3_get_full_text(article: dict) -> dict:
    """
    Шаг 3: Получить полный текст статьи.

    Ждём CRAWL_DELAY секунд (robots.txt Crawl-delay: 10).
    Используем ЧИСТЫЙ URL (canonical_url, без UTM) — UTM-URL в Disallow у Хабра.
    """
    print("\n" + "="*60)
    print("ШАГ 3: Получение полного текста")
    print("="*60)
    print(f"Статья: {article['title'][:60]}")
    print(f"URL для запроса: {article['canonical_url']}")
    print(f"Пауза {CRAWL_DELAY} сек (robots.txt Crawl-delay: 10)...", end=" ", flush=True)

    await asyncio.sleep(CRAWL_DELAY)
    print("готово")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(
            article["canonical_url"],
            headers={"User-Agent": USER_AGENT},
        )

    print(f"HTTP статус: {response.status_code}")
    print(f"Размер HTML: {len(response.text):,} символов")

    # Извлекаем текст через trafilatura
    doc = trafilatura.bare_extraction(
        response.text,
        url=article["canonical_url"],
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        deduplicate=True,
    )

    if doc and doc.text and len(doc.text) > 200:
        print(f"\n✓ trafilatura (favor_precision): извлечено {len(doc.text):,} символов")
        extraction_method = "trafilatura_precision"
        content = doc.text
        trafilatura_author = doc.author
        trafilatura_date = doc.date
    else:
        # Fallback: агрессивный режим
        print("  favor_precision вернул мало → пробуем favor_recall...")
        doc2 = trafilatura.bare_extraction(
            response.text,
            url=article["canonical_url"],
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        if doc2 and doc2.text and len(doc2.text) > 200:
            print(f"✓ trafilatura (favor_recall): извлечено {len(doc2.text):,} символов")
            extraction_method = "trafilatura_recall"
            content = doc2.text
            trafilatura_author = doc2.author
            trafilatura_date = doc2.date
        else:
            print("✗ trafilatura не справилась → используем summary из RSS")
            extraction_method = "rss_summary"
            content = article["summary"]
            trafilatura_author = None
            trafilatura_date = None

    # Превью: первые 300 символов
    print(f"\nПревью текста:")
    print("-" * 40)
    print(content[:1000])
    print("-" * 40)

    return {
        **article,
        "content": content,
        "extraction_method": extraction_method,
        "raw_html": response.text,
        "trafilatura_author": trafilatura_author,
        "trafilatura_date": trafilatura_date,
    }


def step4_show_what_goes_to_db(article: dict) -> None:
    """
    Шаг 4: Показать что именно попало бы в базу данных.

    В реальной системе здесь был бы INSERT INTO news + INSERT INTO news_raw.
    Сейчас просто печатаем.
    """
    print("\n" + "="*60)
    print("ШАГ 4: Что пошло бы в базу данных")
    print("="*60)

    th = title_hash(article["title"])

    print("\n--- Таблица news ---")
    print(f"url:              {article['url'][:70]}")
    print(f"canonical_url:    {article['canonical_url'][:70]}")
    print(f"title:            {article['title'][:70]}")
    print(f"content длина:    {len(article.get('content', '')) :,} символов")
    print(f"snippet_lead:     {article.get('content', '')[:150]}...")
    print(f"published_at:     {article.get('published_at')} (UTC)")
    print(f"channel_type:     RSS")
    print(f"information_type: analytics")
    print(f"content_type:     analysis")
    print(f"language:         ru")
    print(f"title_hash:       {th}")
    print(f"content_grade:    6 (по умолчанию, пока Слой 3 не уточнит)")
    print(f"processed:        False (Слой 2 ещё не обработал)")
    print(f"extra JSONB:")
    print(f"  author:           {article.get('trafilatura_author') or article.get('author', '—')}")
    print(f"  tags:             {article.get('tags', [])[:5]}")
    print(f"  extraction_method:{article.get('extraction_method')}")

    print("\n--- Таблица news_raw ---")
    print(f"raw_content длина:{len(article.get('raw_html', '')) :,} символов (HTML)")
    print(f"raw_format:       html")
    print(f"parser_version:   habr-v1")


# ─── Главная функция ──────────────────────────────────────────────────────────

async def main():
    print("ТЕСТ СБОРА: ХАБР")
    print("Пошаговая демонстрация без базы данных и Celery")

    # Шаг 1: Загрузить RSS
    raw_content, cache_info = await step1_fetch_rss()
    if raw_content is None:
        return

    # Шаг 2: Распарсить
    articles = step2_parse_rss(raw_content)
    if not articles:
        return

    # Шаг 3: Взять первую статью и получить полный текст
    # (в реальной системе — все новые статьи, с проверкой дубликатов)
    first_article = articles[0]
    print(f"\nБерём для демонстрации: {first_article['title'][:60]}")

    enriched = await step3_get_full_text(first_article)

    # Шаг 4: Показать что пойдёт в базу
    step4_show_what_goes_to_db(enriched)

    print("\n" + "="*60)
    print("ИТОГ")
    print("="*60)
    print(f"RSS записей в фиде:        {len(articles)}")
    print(f"Метод извлечения текста:   {enriched['extraction_method']}")
    print(f"Длина полного текста:      {len(enriched.get('content', '')):,} символов")
    print(f"ETag для следующего запроса: {cache_info.get('etag', '—')}")
    print(f"\nСледующий запрос через: 120 минут (crawl_interval)")
    print(f"Задержка между запросами: {CRAWL_DELAY} сек (robots.txt Crawl-delay: 10)")


if __name__ == "__main__":
    asyncio.run(main())
