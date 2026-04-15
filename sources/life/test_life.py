"""
Пошаговый тест сбора с Life.ru.

Ключевые особенности:
- <link> и <guid> уже чистые (нет UTM) — нормализация минимальная
- <description> — ЧИСТЫЙ ТЕКСТ (не HTML!) — очистка не нужна
- <category> — несколько на статью → список тегов
- <enclosure url="..."> — thumbnail (length=0 — баг Life.ru, URL рабочий)
- Нет <author> → author = null
- robots.txt Disallow: *?* — статьи /p/{id} без query params → разрешены

Запуск: python sources/life/test_life.py

Зависимости: pip install httpx feedparser trafilatura beautifulsoup4
"""

import asyncio
import calendar
import hashlib
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

# ─── Конфигурация ────────────────────────────────────────────────────────────

RSS_URL = "https://life.ru/rss"
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 1.0
PAYWALL_THRESHOLD = 200

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    """
    Нормализовать URL: https, без www., без trailing slash, без query params.
    robots.txt Disallow: *?* — любой URL с ? запрещён.
    У Life.ru ссылки уже чистые, но нормализуем для единообразия.
    """
    try:
        p = urlparse(url.strip())
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        return urlunparse(("https", host, path, "", "", ""))
    except Exception:
        return url


def parse_date(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            ts = calendar.timegm(parsed)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def title_hash(title: str) -> str:
    normalized = " ".join(title.lower().split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def get_categories(entry) -> list[str]:
    """Собрать все <category> — feedparser кладёт их в entry.tags."""
    return [tag["term"] for tag in entry.get("tags", []) if tag.get("term")]


def get_thumbnail(entry) -> str | None:
    """Thumbnail из <enclosure>. length=0 — баг Life.ru, URL рабочий."""
    if entry.enclosures:
        return entry.enclosures[0].get("href")
    return None


# ─── Шаги сбора ──────────────────────────────────────────────────────────────

async def step1_fetch_rss() -> tuple[bytes | None, dict]:
    """
    Шаг 1: Скачать RSS.
    Проверяем ETag/Last-Modified.
    """
    print("\n" + "="*60)
    print("ШАГ 1: Загрузка RSS-фида")
    print("="*60)
    print(f"URL: {RSS_URL}")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(RSS_URL, headers={"User-Agent": USER_AGENT})

    etag = response.headers.get("etag")
    last_mod = response.headers.get("last-modified")
    print(f"\nHTTP статус:   {response.status_code}")
    print(f"Content-Type:  {response.headers.get('content-type', '—')}")
    print(f"ETag:          {etag or 'не поддерживается'}")
    print(f"Last-Modified: {last_mod or 'не поддерживается'}")
    print(f"Размер:        {len(response.content):,} байт")

    if etag or last_mod:
        print("\nТест If-None-Match / If-Modified-Since...")
        cond = {"User-Agent": USER_AGENT}
        if etag:
            cond["If-None-Match"] = etag
        if last_mod:
            cond["If-Modified-Since"] = last_mod

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            r2 = await client.get(RSS_URL, headers=cond)
        if r2.status_code == 304:
            print(f"  ✓ 304 Not Modified — кэширование работает")
        else:
            print(f"  Статус: {r2.status_code} (фид обновился между запросами — норма)")

    response.raise_for_status()
    return response.content, {"etag": etag, "modified": last_mod}


def step2_parse_rss(raw_content: bytes) -> list[dict]:
    """
    Шаг 2: Парсинг RSS.

    Главные задачи:
    1. canonical_url (URL уже чистый, только нормализация)
    2. description — чистый текст, не трогаем
    3. Собрать все category → список тегов
    4. Thumbnail из enclosure
    """
    print("\n" + "="*60)
    print("ШАГ 2: Парсинг RSS")
    print("="*60)

    feed = feedparser.parse(raw_content)
    print(f"Записей в фиде: {len(feed.entries)}")

    if not feed.entries:
        return []

    # Детальный анализ первой записи
    first = feed.entries[0]
    raw_link = first.get("link", "")
    clean = canonical_url(raw_link)
    categories = get_categories(first)
    thumbnail = get_thumbnail(first)
    snippet = first.get("summary", "")  # уже чистый текст

    print(f"\n--- Структура первой записи ---")
    print(f"title:           {first.get('title', '—')[:70]}")
    print(f"link:            {raw_link}")
    print(f"link (canonical):{clean}  ← нормализован")
    print(f"guid:            {first.get('id', '—')}")
    print(f"published:       {first.get('published', '—')}")
    print(f"\ndescription (ЧИСТЫЙ ТЕКСТ — не HTML!):")
    print(f"  '{snippet[:120]}'")
    print(f"\ncategories ({len(categories)}): {categories}")
    print(f"thumbnail: {thumbnail}")
    print(f"author:    {first.get('author', 'отсутствует')} ← null в БД")

    # Сборка всех статей
    articles = []
    has_thumbnail = 0

    for entry in feed.entries:
        raw_url = entry.get("link", "").strip()
        can_url = canonical_url(raw_url)
        cats = get_categories(entry)
        thumb = get_thumbnail(entry)
        snippet_lead = entry.get("summary", "")

        if thumb:
            has_thumbnail += 1

        articles.append({
            "url": raw_url,
            "canonical_url": can_url,
            "title": entry.get("title", "").strip(),
            "author": None,            # Life.ru не указывает автора
            "snippet_lead": snippet_lead,
            "published_at": parse_date(entry),
            "categories": cats,
            "thumbnail": thumb,
        })

    print(f"\nВсего статей: {len(articles)}")
    print(f"С thumbnail:  {has_thumbnail}/{len(articles)}")

    # Распределение по категориям (топ)
    cat_counter: dict[str, int] = {}
    for a in articles:
        for c in a["categories"]:
            cat_counter[c] = cat_counter.get(c, 0) + 1
    top_cats = sorted(cat_counter.items(), key=lambda x: -x[1])[:10]
    print(f"\nТоп категорий:")
    for cat, cnt in top_cats:
        print(f"  '{cat}': {cnt}")

    print(f"\nПервые 5 заголовков:")
    for a in articles[:5]:
        t = a["published_at"].strftime("%H:%M UTC") if a["published_at"] else "—"
        print(f"  [{t}] {a['title'][:60]}", flush=True)
    sys.stdout.flush()

    return articles


async def step3_get_full_text(article: dict) -> dict:
    """
    Шаг 3: Полный текст со страницы.
    URL уже без query params — robots.txt Disallow: *?* соблюдён.
    """
    print("\n" + "="*60)
    print("ШАГ 3: Получение полного текста")
    print("="*60)
    print(f"Статья:  {article['title'][:60]}")
    print(f"URL:     {article['canonical_url']}")
    print(f"Пауза {CRAWL_DELAY} сек...", end=" ", flush=True)
    await asyncio.sleep(CRAWL_DELAY)
    print("готово")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(
            article["canonical_url"],
            headers={"User-Agent": USER_AGENT},
        )

    print(f"HTTP статус: {response.status_code}")
    print(f"Размер HTML: {len(response.text):,} символов")

    # Попытка 1: trafilatura favor_precision
    doc = trafilatura.bare_extraction(
        response.text,
        url=article["canonical_url"],
        include_comments=False,
        favor_precision=True,
        deduplicate=True,
    )
    raw_text = (doc.text or "") if doc else ""

    # Попытка 2: trafilatura favor_recall
    if len(raw_text) < PAYWALL_THRESHOLD:
        doc2 = trafilatura.bare_extraction(
            response.text,
            url=article["canonical_url"],
            favor_recall=True,
        )
        raw_text2 = (doc2.text or "") if doc2 else ""
        if len(raw_text2) > len(raw_text):
            raw_text = raw_text2

    extraction_method = "trafilatura"
    print(f"\ntrafilatura: {len(raw_text):,} символов")

    # Попытка 3: BS4 — ищем типичные CSS-классы статейных блоков
    soup = BeautifulSoup(response.text, "html.parser")
    bs4_candidates = {}

    # Перебираем вероятные CSS-классы Life.ru
    for cls in (
        "article__body",
        "article__text",
        "article-body",
        "article__content",
        "story__body",
        "story-body",
        "js-mediator-article",
        "publication__body",
    ):
        block = soup.find(class_=cls)
        if block:
            for tag in block.find_all(["script", "style", "figure", "aside"]):
                tag.decompose()
            text = block.get_text(separator="\n", strip=True)
            if text:
                bs4_candidates[cls] = text

    if bs4_candidates:
        best_cls = max(bs4_candidates, key=lambda k: len(bs4_candidates[k]))
        best_bs4 = bs4_candidates[best_cls]
        print(f"BS4 найдено классов: {list(bs4_candidates.keys())}")
        print(f"BS4 лучший '{best_cls}': {len(best_bs4):,} символов")
        if len(best_bs4) > len(raw_text):
            raw_text = best_bs4
            extraction_method = f"bs4_{best_cls}"
    else:
        print("BS4: подходящих CSS-классов не найдено — используем trafilatura")

    if len(raw_text) < PAYWALL_THRESHOLD:
        quality = "paywall_or_js"
        print(f"\n⚠️  Мало текста: {len(raw_text)} символов — paywall или JS-рендеринг?")
    else:
        quality = "ok"
        print(f"\n✓ Полный текст: {len(raw_text):,} символов (метод: {extraction_method})")
        print(f"\nПревью:")
        print("-" * 40)
        print(raw_text[:400])
        print("-" * 40)

    return {**article, "content": raw_text, "quality": quality,
            "extraction_method": extraction_method, "raw_html": response.text}


def step4_show_what_goes_to_db(article: dict) -> None:
    print("\n" + "="*60)
    print("ШАГ 4: Что пошло бы в базу данных")
    print("="*60)

    content = article.get("content", "")
    print("\n--- Таблица news ---")
    print(f"url:              {article['url']}")
    print(f"canonical_url:    {article['canonical_url']}")
    print(f"title:            {article['title'][:70]}")
    print(f"author:           null  (Life.ru не указывает авторов)")
    print(f"content длина:    {len(content):,} символов")
    print(f"snippet_lead:     '{article['snippet_lead'][:100]}'")
    print(f"published_at:     {article.get('published_at')} (UTC)")
    print(f"information_type: daily")
    print(f"quality:          {article.get('quality', 'ok')}")
    print(f"title_hash:       {title_hash(article['title'])}")
    print(f"extra JSONB:")
    print(f"  categories:       {article.get('categories', [])}")
    print(f"  thumbnail:        {article.get('thumbnail')}")
    print(f"  extraction_method:{article.get('extraction_method')}")

    print("\n--- Таблица news_raw ---")
    print(f"raw_content длина:{len(article.get('raw_html', '')):,} символов")
    print(f"raw_format:       html")
    print(f"parser_version:   life-v1")


async def main():
    print("ТЕСТ СБОРА: LIFE.RU")
    print("Особенности: чистый текст в description, несколько category, thumbnail в enclosure")

    raw_content, cache_info = await step1_fetch_rss()
    if not raw_content:
        return

    articles = step2_parse_rss(raw_content)
    if not articles:
        return

    demo = articles[0]
    enriched = await step3_get_full_text(demo)
    step4_show_what_goes_to_db(enriched)

    print("\n" + "="*60)
    print("ИТОГ")
    print("="*60)
    print(f"Записей в фиде:   {len(articles)}")
    print(f"ETag:             {cache_info.get('etag') or '—'}")
    print(f"Last-Modified:    {cache_info.get('modified') or '—'}")
    print(f"Качество текста:  {enriched.get('quality')}")
    print(f"Метод:            {enriched.get('extraction_method')}")
    print(f"snippet_lead:     {'есть' if enriched['snippet_lead'] else 'ПУСТО'}")
    print(f"Thumbnail:        {enriched.get('thumbnail') or '—'}")
    print(f"\nrobots.txt Disallow: *?* → статьи /p/{{id}} без ? — разрешены")


if __name__ == "__main__":
    asyncio.run(main())
