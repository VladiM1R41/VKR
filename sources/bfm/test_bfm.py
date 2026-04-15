"""
Пошаговый тест сбора с BFM.ru.

Что проверяем:
- RSS доступен ли и поддерживает ли ETag / Last-Modified
- сколько записей в фиде
- есть ли guid
- есть ли enclosure / thumbnail
- как устроены category (рубрика vs автор)
- нужен ли запрос на HTML-страницу за полным текстом
- справляется ли trafilatura

Запуск:
    python sources/bfm/test_bfm.py

Зависимости:
    pip install httpx feedparser trafilatura beautifulsoup4
"""

import asyncio
import calendar
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

RSS_URL = "https://www.bfm.ru/news.rss?type=news"
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 1.0
MIN_FULLTEXT_THRESHOLD = 200

_NOISE_LINE_PATTERNS = [
    re.compile(r"^\s*лента новостей\s*$", re.IGNORECASE),
    re.compile(r"^\s*все новости\s*»?\s*$", re.IGNORECASE),
]


def canonical_url(url: str) -> str:
    """Нормализовать URL для дедупликации."""
    try:
        p = urlparse(url.strip())
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        params = {
            k: v for k, v in parse_qs(p.query).items()
            if k.lower() not in {"utm_source", "utm_medium", "utm_campaign", "fbclid", "gclid"}
        }
        query = urlencode(params, doseq=True) if params else ""
        return urlunparse(("https", host, path, "", query, ""))
    except Exception:
        return url


def parse_date(entry) -> datetime | None:
    """Преобразовать published_parsed в UTC."""
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            ts = calendar.timegm(parsed)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def title_hash(title: str) -> str:
    normalized = " ".join(title.lower().split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def clean_extracted_text(text: str) -> str:
    """
    Удалить типичные шумовые строки из извлечённого текста.

    Для BFM тест показал артефакт из правой колонки: «Лента новостей».
    """
    if not text:
        return text

    cleaned_lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()

        if not line:
            cleaned_lines.append("")
            continue

        if any(pattern.search(line) for pattern in _NOISE_LINE_PATTERNS):
            continue

        cleaned_lines.append(line)

    result: list[str] = []
    prev_blank = False
    for line in cleaned_lines:
        blank = line == ""
        if blank and prev_blank:
            continue
        result.append(line)
        prev_blank = blank

    return "\n".join(result).strip()


def split_categories(entry) -> tuple[list[str], list[str]]:
    """
    Разделить категории на рубрики и author-category.

    Логика предварительная:
    - если domain содержит /rubric/ -> это рубрика
    - если domain содержит author= -> это author-category
    """
    rubric_categories: list[str] = []
    author_categories: list[str] = []

    for tag in entry.get("tags", []):
        term = (tag.get("term") or "").strip()
        domain = (tag.get("scheme") or tag.get("domain") or "").strip()

        if not term:
            continue

        if "/rubric/" in domain:
            rubric_categories.append(term)
        elif "author=" in domain:
            author_categories.append(term)
        else:
            rubric_categories.append(term)

    return rubric_categories, author_categories


async def step1_fetch_rss() -> tuple[bytes, dict]:
    print("\n" + "=" * 60)
    print("ШАГ 1: Загрузка RSS-фида")
    print("=" * 60)
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

    response.raise_for_status()

    if etag or last_mod:
        print("\nТест условного запроса...")
        cond = {"User-Agent": USER_AGENT}
        if etag:
            cond["If-None-Match"] = etag
        if last_mod:
            cond["If-Modified-Since"] = last_mod

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            r2 = await client.get(RSS_URL, headers=cond)
        print(f"Условный запрос: HTTP {r2.status_code}")

    return response.content, {"etag": etag, "modified": last_mod}


def step2_parse_rss(raw_content: bytes) -> list[dict]:
    print("\n" + "=" * 60)
    print("ШАГ 2: Парсинг RSS")
    print("=" * 60)

    feed = feedparser.parse(raw_content)
    print(f"Записей в фиде: {len(feed.entries)}")

    if not feed.entries:
        return []

    first = feed.entries[0]
    rubrics, author_categories = split_categories(first)

    print("\n--- Структура первой записи ---")
    print(f"title:         {first.get('title', '—')}")
    print(f"link:          {first.get('link', '—')}")
    print(f"guid/id:       {first.get('id', 'отсутствует')}")
    print(f"published:     {first.get('published', '—')}")
    print(f"author:        {first.get('author', '—')}")
    print(f"description:   {first.get('summary', '')[:160]}")
    print(f"rubrics:       {rubrics}")
    print(f"author-cats:   {author_categories}")
    print(f"enclosures:    {len(first.get('enclosures', []))}")

    articles = []
    with_author = 0
    with_guid = 0
    with_enclosure = 0

    for entry in feed.entries:
        rubrics, author_categories = split_categories(entry)
        guid = entry.get("id")
        enclosures = entry.get("enclosures", [])

        if entry.get("author"):
            with_author += 1
        if guid:
            with_guid += 1
        if enclosures:
            with_enclosure += 1

        articles.append({
            "url": (entry.get("link") or "").strip(),
            "canonical_url": canonical_url(entry.get("link", "")),
            "title": (entry.get("title") or "").strip(),
            "snippet_lead": (entry.get("summary") or "").strip(),
            "published_at": parse_date(entry),
            "author": (entry.get("author") or "").strip() or None,
            "guid": guid,
            "rubrics": rubrics,
            "author_categories": author_categories,
            "thumbnail": enclosures[0].get("href") if enclosures else None,
        })

    print(f"\nС author:      {with_author}/{len(articles)}")
    print(f"С guid:        {with_guid}/{len(articles)}")
    print(f"С enclosure:   {with_enclosure}/{len(articles)}")

    print("\nПервые 5 заголовков:")
    for a in articles[:5]:
        t = a["published_at"].strftime("%H:%M UTC") if a["published_at"] else "—"
        print(f"  [{t}] {a['title'][:70]}")

    return articles


async def step3_get_full_text(article: dict) -> dict:
    print("\n" + "=" * 60)
    print("ШАГ 3: Получение полного текста")
    print("=" * 60)
    print(f"Статья: {article['title'][:80]}")
    print(f"URL:    {article['canonical_url']}")
    print(f"Пауза {CRAWL_DELAY} сек...", end=" ", flush=True)
    await asyncio.sleep(CRAWL_DELAY)
    print("готово")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(article["canonical_url"], headers={"User-Agent": USER_AGENT})

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
    precision_text = (doc.text or "") if doc else ""

    doc2 = trafilatura.bare_extraction(
        response.text,
        url=article["canonical_url"],
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )
    recall_text = (doc2.text or "") if doc2 else ""

    best_text = precision_text if len(precision_text) >= len(recall_text) else recall_text
    extraction_method = "trafilatura_precision" if best_text == precision_text else "trafilatura_recall"
    cleaned_text = clean_extracted_text(best_text)

    print(f"precision: {len(precision_text):,} символов")
    print(f"recall:    {len(recall_text):,} символов")
    print(f"cleaned:   {len(cleaned_text):,} символов")

    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else "—"
    print(f"HTML <title>: {title[:120]}")

    quality = "ok" if len(cleaned_text) >= MIN_FULLTEXT_THRESHOLD else "low"

    if cleaned_text:
        print("\nПревью текста:")
        print("-" * 40)
        print(cleaned_text)
        print("-" * 40)

    return {
        **article,
        "content": cleaned_text,
        "quality": quality,
        "extraction_method": extraction_method,
        "raw_html": response.text,
    }


def step4_show_what_goes_to_db(article: dict) -> None:
    print("\n" + "=" * 60)
    print("ШАГ 4: Что пошло бы в базу данных")
    print("=" * 60)

    print("\n--- Таблица news ---")
    print(f"url:              {article['url']}")
    print(f"canonical_url:    {article['canonical_url']}")
    print(f"title:            {article['title']}")
    print(f"author:           {article.get('author')}")
    print(f"content длина:    {len(article.get('content', '')):,} символов")
    print(f"snippet_lead:     {article.get('snippet_lead', '')[:140]}")
    print(f"published_at:     {article.get('published_at')} (UTC)")
    print(f"title_hash:       {title_hash(article['title'])}")
    print(f"quality:          {article.get('quality')}")
    print("extra JSONB:")
    print(f"  rubrics:          {article.get('rubrics', [])}")
    print(f"  author_categories:{article.get('author_categories', [])}")
    print(f"  thumbnail:        {article.get('thumbnail')}")
    print(f"  extraction_method:{article.get('extraction_method')}")

    print("\n--- Таблица news_raw ---")
    print(f"raw_content длина:{len(article.get('raw_html', '')):,} символов")
    print("raw_format:       html")
    print("parser_version:   bfm-v1")


async def main():
    print("ТЕСТ СБОРА: BFM.RU")
    print("Особенности: author в RSS, mixed category, полный текст ожидается только на HTML-странице")

    raw_content, cache_info = await step1_fetch_rss()
    articles = step2_parse_rss(raw_content)
    if not articles:
        return

    demo = articles[0]
    enriched = await step3_get_full_text(demo)
    step4_show_what_goes_to_db(enriched)

    print("\n" + "=" * 60)
    print("ИТОГ")
    print("=" * 60)
    print(f"Записей в фиде:   {len(articles)}")
    print(f"ETag:             {cache_info.get('etag') or '—'}")
    print(f"Last-Modified:    {cache_info.get('modified') or '—'}")
    print(f"Метод extraction: {enriched.get('extraction_method')}")
    print(f"Качество текста:  {enriched.get('quality')}")
    print(f"Author:           {enriched.get('author') or '—'}")
    print(f"Rubrics:          {enriched.get('rubrics')}")


if __name__ == "__main__":
    asyncio.run(main())
