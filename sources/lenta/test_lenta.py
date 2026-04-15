"""
Пошаговый тест сбора с Lenta.ru.

Запуск: python sources/lenta/test_lenta.py

Этот скрипт НЕ использует базу данных и Celery.
Он показывает каждый шаг сбора «голым» кодом.

Зависимости: pip install httpx feedparser trafilatura
"""

import asyncio
import calendar
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import feedparser
import httpx
import trafilatura

# ─── Конфигурация ────────────────────────────────────────────────────────────

RSS_URL = "https://lenta.ru/rss"
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 1.0  # секунд между запросами (нет Crawl-delay в robots.txt, вежливый дефолт)

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    """
    Привести URL к каноническому виду для дедупликации.

    У Lenta.ru URL уже чистый (нет UTM), нужна только базовая нормализация:
    убрать trailing slash, привести схему к https, убрать www.

    Пример:
    "https://lenta.ru/news/2026/04/03/some-title/" → "https://lenta.ru/news/2026/04/03/some-title"
    """
    try:
        p = urlparse(url)
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        return urlunparse(("https", host, path, "", "", ""))
    except Exception:
        return url


def title_hash(title: str) -> str:
    """MD5 от нормализованного заголовка — для дедупликации по title."""
    normalized = " ".join(title.lower().split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def parse_date(entry) -> datetime | None:
    """
    Извлечь дату публикации из RSS-записи.

    ВАЖНО для Lenta.ru: pubDate в МОСКОВСКОМ ВРЕМЕНИ (+0300), не UTC.
    Пример: "Fri, 03 Apr 2026 18:54:49 +0300" = 15:54:49 UTC

    feedparser конвертирует timezone автоматически: published_parsed всегда UTC.
    calendar.timegm() корректно интерпретирует как UTC.

    Сравнение с Хабром: у Хабра pubDate в GMT (= UTC), у Ленты +0300.
    Наш код одинаково корректен для обоих.
    """
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            ts = calendar.timegm(parsed)  # UTC struct_time → timestamp
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def get_thumbnail(entry) -> str | None:
    """
    Извлечь URL превью-картинки из <enclosure>.

    feedparser кладёт enclosures в entry.enclosures (список).
    Lenta.ru даёт одну картинку типа image/jpeg.

    Это полезно для UI — не нужно делать дополнительный HTTP-запрос
    чтобы показать thumbnail в карточке новости.
    """
    enclosures = entry.get("enclosures", [])
    for enc in enclosures:
        if enc.get("type", "").startswith("image/"):
            return enc.get("href") or enc.get("url")
    return None


# ─── Шаги сбора ──────────────────────────────────────────────────────────────

async def step1_fetch_rss() -> tuple[bytes | None, dict]:
    """
    Шаг 1: Скачать RSS-фид.

    Проверяем: поддерживает ли Lenta ETag/Last-Modified?
    У Хабра не поддерживалось — проверим у Ленты.
    """
    print("\n" + "="*60)
    print("ШАГ 1: Загрузка RSS-фида")
    print("="*60)
    print(f"URL: {RSS_URL}")

    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(RSS_URL, headers=headers)

    print(f"\nHTTP статус: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type', '—')}")
    print(f"ETag: {response.headers.get('etag', 'не поддерживается')}")
    print(f"Last-Modified: {response.headers.get('last-modified', 'не поддерживается')}")
    print(f"Размер ответа: {len(response.content):,} байт")

    if response.status_code == 304:
        print("\n→ 304 Not Modified")
        return None, {}

    response.raise_for_status()

    cache_info = {
        "etag": response.headers.get("etag"),
        "modified": response.headers.get("last-modified"),
    }

    if cache_info["etag"] or cache_info["modified"]:
        print(f"\n→ Lenta поддерживает кэширование: ETag={cache_info['etag']}, Modified={cache_info['modified']}")
    else:
        print("\n→ Lenta НЕ поддерживает ETag/Last-Modified (как Хабр)")
        print("  Каждый запрос скачивает полный фид, дедупликация по canonical_url")

    return response.content, cache_info


def step2_parse_rss(raw_content: bytes) -> list[dict]:
    """
    Шаг 2: Распарсить RSS.

    Главная особенность Lenta.ru: description ПУСТОЙ.
    Нет контента, нет лида, нет fallback — только заголовок и URL.
    """
    print("\n" + "="*60)
    print("ШАГ 2: Парсинг RSS")
    print("="*60)

    feed = feedparser.parse(raw_content)
    print(f"Записей в фиде: {len(feed.entries)}")

    if not feed.entries:
        print("→ Фид пустой или не распарсился")
        return []

    first = feed.entries[0]
    print("\n--- Структура первой записи ---")
    print(f"title:     {first.get('title', '—')}")
    print(f"link:      {first.get('link', '—')}")
    print(f"id (guid): {first.get('id', '—')}")
    print(f"author:    {first.get('author', '—')}")
    print(f"published: {first.get('published', '—')}")

    # Категория
    tags = [t.get("term", "") for t in first.get("tags", [])]
    print(f"category:  {tags}")

    # Thumbnail
    thumb = get_thumbnail(first)
    print(f"thumbnail: {thumb or '—'}")

    # Критическая проверка: description
    summary = first.get("summary", "")
    print(f"\nsummary: '{summary}' (длина: {len(summary)} символов)")

    if not summary or len(summary.strip()) == 0:
        print("\n⚠️  description ПУСТОЙ — нет fallback контента!")
        print("   Полный текст можно получить ТОЛЬКО со страницы статьи.")
        print("   Если страница недоступна — контента не будет вообще.")
    else:
        print(f"\nПервые 200 символов summary: {repr(summary[:200])}")

    # Проверка timezone в дате
    raw_date = first.get("published", "")
    parsed_dt = parse_date(first)
    print(f"\nДата из RSS:    {raw_date}")
    print(f"После парсинга: {parsed_dt} (UTC)")
    if "+0300" in raw_date or "MSK" in raw_date:
        print("→ feedparser корректно конвертировал московское время в UTC ✓")

    # Собираем все записи
    articles = []
    for entry in feed.entries:
        raw_url = entry.get("link") or entry.get("id", "")
        can_url = canonical_url(raw_url)
        pub_date = parse_date(entry)
        thumb = get_thumbnail(entry)

        articles.append({
            "url": raw_url,
            "canonical_url": can_url,
            "title": entry.get("title", ""),
            "summary": entry.get("summary", ""),  # пустой для Ленты
            "published_at": pub_date,
            "author": entry.get("author", ""),
            "category": [t.get("term", "") for t in entry.get("tags", [])],
            "thumbnail": thumb,
        })

    print(f"\n→ Извлечено записей: {len(articles)}")
    print("\nПервые 5 заголовков:")
    for a in articles[:5]:
        date_str = a["published_at"].strftime("%Y-%m-%d %H:%M UTC") if a["published_at"] else "нет даты"
        author = a["author"] or "—"
        print(f"  [{date_str}] {a['title'][:50]} ({author})")

    return articles


async def step3_get_full_text(article: dict) -> dict:
    """
    Шаг 3: Получить полный текст статьи.

    Для Ленты это ЕДИНСТВЕННЫЙ способ получить контент — description пустой.
    Ждём CRAWL_DELAY секунд (вежливый дефолт, robots.txt не указывает Crawl-delay).
    """
    print("\n" + "="*60)
    print("ШАГ 3: Получение полного текста")
    print("="*60)
    print(f"Статья: {article['title'][:60]}")
    print(f"Автор:  {article['author'] or '—'}")
    print(f"URL:    {article['canonical_url']}")
    print(f"Пауза {CRAWL_DELAY} сек (вежливый дефолт)...", end=" ", flush=True)

    await asyncio.sleep(CRAWL_DELAY)
    print("готово")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(
            article["canonical_url"],
            headers={"User-Agent": USER_AGENT},
        )

    print(f"HTTP статус: {response.status_code}")
    print(f"Размер HTML: {len(response.text):,} символов")

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
            # У Ленты нет fallback summary — это отличие от Хабра
            print("✗ trafilatura не справилась")
            print("⚠️  У Lenta.ru НЕТ fallback summary в RSS!")
            print("   Статья будет сохранена с пустым контентом (quality='low')")
            extraction_method = "none"
            content = ""
            trafilatura_author = None
            trafilatura_date = None

    if content:
        print(f"\nПревью текста:")
        print("-" * 40)
        print(content)
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
    if article.get("content"):
        print(f"snippet_lead:     {article.get('content', '')[:150]}...")
    else:
        print(f"snippet_lead:     [ПУСТО — не удалось извлечь текст]")
    print(f"published_at:     {article.get('published_at')} (UTC)")
    print(f"channel_type:     RSS")
    print(f"information_type: daily")
    print(f"content_type:     news")
    print(f"language:         ru")
    print(f"title_hash:       {th}")
    print(f"content_grade:    6 (по умолчанию)")
    print(f"processed:        False")
    print(f"extra JSONB:")
    print(f"  author:           {article.get('trafilatura_author') or article.get('author', '—')}")
    print(f"  category:         {article.get('category', [])}")
    print(f"  thumbnail:        {article.get('thumbnail', '—')}")
    print(f"  extraction_method:{article.get('extraction_method')}")

    print("\n--- Таблица news_raw ---")
    print(f"raw_content длина:{len(article.get('raw_html', '')) :,} символов (HTML)")
    print(f"raw_format:       html")
    print(f"parser_version:   lenta-v1")

    # Предупреждение если контента нет
    if not article.get("content"):
        print("\n⚠️  ВНИМАНИЕ: контент пустой!")
        print("   Статья попадёт в базу с empty content.")
        print("   Такие записи не будут полезны для RAG.")
        print("   Решение: пометить processed=False, content_grade=1, retry позже.")


# ─── Главная функция ──────────────────────────────────────────────────────────

async def main():
    print("ТЕСТ СБОРА: LENTA.RU")
    print("Пошаговая демонстрация без базы данных и Celery")
    print(f"\nКлючевые отличия от Хабра:")
    print(f"  - description ПУСТОЙ (у Хабра был лид)")
    print(f"  - pubDate в +0300 (у Хабра GMT)")
    print(f"  - guid = link, без UTM (у Хабра они разные)")
    print(f"  - crawl_delay = {CRAWL_DELAY} сек (у Хабра 10 сек)")

    raw_content, cache_info = await step1_fetch_rss()
    if raw_content is None:
        return

    articles = step2_parse_rss(raw_content)
    if not articles:
        return

    first_article = articles[0]
    print(f"\nБерём для демонстрации: {first_article['title'][:60]}")

    enriched = await step3_get_full_text(first_article)
    step4_show_what_goes_to_db(enriched)

    print("\n" + "="*60)
    print("ИТОГ")
    print("="*60)
    print(f"RSS записей в фиде:        {len(articles)}")
    print(f"Метод извлечения текста:   {enriched['extraction_method']}")
    print(f"Длина полного текста:      {len(enriched.get('content', '')):,} символов")
    print(f"ETag для следующего запроса: {cache_info.get('etag', '—')}")
    print(f"\nСледующий запрос через: 30 минут (crawl_interval)")
    print(f"Задержка между запросами: {CRAWL_DELAY} сек (вежливый дефолт)")


if __name__ == "__main__":
    asyncio.run(main())
