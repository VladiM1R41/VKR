"""
Пошаговый тест сбора с CNews.

Что проверяем:
- RSS доступен ли и поддерживает ли ETag / Last-Modified
- сколько записей в фиде
- совпадают ли guid и link
- полезен ли enclosure
- нужен ли запрос на HTML-страницу за полным текстом
- справляется ли trafilatura
- есть ли author / thumbnail на HTML-странице

Запуск:
    python sources/cnews/test_cnews.py

Зависимости:
    pip install httpx feedparser trafilatura beautifulsoup4
"""

import asyncio
import calendar
import hashlib
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

RSS_URL = "https://www.cnews.ru/inc/rss/news.xml"
BACKUP_RSS_URLS = [
    "https://windows8.cnews.ru/inc/rss/news.xml",
    "https://telecomb2b.cnews.ru/inc/rss/news.xml",
]
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 1.0
MIN_FULLTEXT_THRESHOLD = 200


def canonical_url(url: str) -> str:
    """Нормализовать URL статьи."""
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
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            ts = calendar.timegm(parsed)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def title_hash(title: str) -> str:
    normalized = " ".join(title.lower().split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def get_enclosure_url(enclosures: list[dict]) -> str | None:
    """Return a usable enclosure URL or None if enclosure is empty."""
    if not enclosures:
        return None
    first = enclosures[0]
    url = (first.get("href") or first.get("url") or "").strip()
    return url or None


def is_placeholder_image(url: str | None) -> bool:
    """Detect obvious placeholder images that are useless as article thumbnails."""
    if not url:
        return False
    lowered = url.lower()
    return "placeholder" in lowered or "noimage" in lowered


async def step1_fetch_rss() -> tuple[bytes, dict]:
    print("\n" + "=" * 60)
    print("ШАГ 1: Загрузка RSS-фида")
    print("=" * 60)
    print(f"URL: {RSS_URL}")
    print("Запасные RSS:")
    for backup_url in BACKUP_RSS_URLS:
        print(f"  - {backup_url}")

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
    enclosure = first.get("enclosures", [])

    print("\n--- Структура первой записи ---")
    print(f"title:         {first.get('title', '—')}")
    print(f"link:          {first.get('link', '—')}")
    print(f"guid/id:       {first.get('id', 'отсутствует')}")
    print(f"published:     {first.get('published', '—')}")
    print(f"description:   {first.get('summary', '')[:160]}")
    print(f"author:        {first.get('author', 'отсутствует')}")
    print(f"enclosures:    {len(enclosure)}")
    if enclosure:
        print(f"enclosure[0]:  {enclosure[0]}")

    articles = []
    with_guid = 0
    with_author = 0
    with_enclosure = 0
    with_nonempty_enclosure = 0
    guid_equals_link = 0

    for entry in feed.entries:
        guid = entry.get("id")
        enclosures = entry.get("enclosures", [])
        author = (entry.get("author") or "").strip() or None
        thumbnail = get_enclosure_url(enclosures)

        if guid:
            with_guid += 1
        if guid and guid == (entry.get("link") or "").strip():
            guid_equals_link += 1
        if author:
            with_author += 1
        if enclosures:
            with_enclosure += 1
        if thumbnail:
            with_nonempty_enclosure += 1

        articles.append({
            "url": (entry.get("link") or "").strip(),
            "canonical_url": canonical_url(entry.get("link", "")),
            "guid": guid,
            "title": (entry.get("title") or "").strip(),
            "snippet_lead": (entry.get("summary") or "").strip(),
            "published_at": parse_date(entry),
            "author": author,
            "thumbnail": thumbnail,
        })

    print(f"\nС guid:              {with_guid}/{len(articles)}")
    print(f"guid = link:         {guid_equals_link}/{len(articles)}")
    print(f"С author:            {with_author}/{len(articles)}")
    print(f"С enclosure:         {with_enclosure}/{len(articles)}")
    print(f"С непустым enclosure:{with_nonempty_enclosure}/{len(articles)}")

    print("\nПервые 5 заголовков:")
    for a in articles[:5]:
        t = a["published_at"].strftime("%H:%M UTC") if a["published_at"] else "—"
        print(f"  [{t}] {a['title'][:80]}")

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

    print(f"precision: {len(precision_text):,} символов")
    print(f"recall:    {len(recall_text):,} символов")

    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else "—"
    print(f"HTML <title>: {title[:120]}")

    og_image = None
    meta = soup.find("meta", attrs={"property": "og:image"})
    if meta:
        og_image = meta.get("content")
    print(f"og:image: {og_image or 'не найден'}")
    print(f"og:image placeholder: {'да' if is_placeholder_image(og_image) else 'нет'}")

    quality = "ok" if len(best_text) >= MIN_FULLTEXT_THRESHOLD else "low"

    if best_text:
        print("\nПревью текста:")
        print("-" * 40)
        print(best_text[:600])
        print("-" * 40)

    return {
        **article,
        "content": best_text,
        "quality": quality,
        "extraction_method": extraction_method,
        "raw_html": response.text,
        "og_image": og_image,
        "og_image_is_placeholder": is_placeholder_image(og_image),
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
    print(f"  guid:             {article.get('guid')}")
    print(f"  thumbnail_rss:    {article.get('thumbnail')}")
    print(f"  thumbnail_html:   {article.get('og_image')}")
    print(f"  thumbnail_fake:   {article.get('og_image_is_placeholder')}")
    print(f"  extraction_method:{article.get('extraction_method')}")

    print("\n--- Таблица news_raw ---")
    print(f"raw_content длина:{len(article.get('raw_html', '')):,} символов")
    print("raw_format:       html")
    print("parser_version:   cnews-v1")


async def main():
    print("ТЕСТ СБОРА: CNEWS")
    print("Особенности: лид в RSS, пустой enclosure, ожидаемый full text только с HTML-страницы")

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
    print(f"Thumbnail HTML:   {enriched.get('og_image') or '—'}")
    print(f"Thumbnail fake:   {'да' if enriched.get('og_image_is_placeholder') else 'нет'}")


if __name__ == "__main__":
    asyncio.run(main())
