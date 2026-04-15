"""
Пошаговый тест сбора с Аргументов и фактов.

Что проверяем:
- доступен ли RSS и поддерживает ли ETag / Last-Modified
- сколько записей в фиде
- как feedparser отдает namespaced поля
- есть ли author / category / enclosure
- есть ли yandex:full-text и turbo:content
- достаточно ли RSS для full text без HTML-fetch

Запуск:
    python sources/aif/test_aif.py
"""

import asyncio
import hashlib
import sys
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from html import unescape
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

RSS_URL = "https://aif.ru/rss/news.php"
ARTICLES_RSS_URL = "https://aif.ru/rss/articles.php"
FEEDS = {
    "news": RSS_URL,
    "articles": ARTICLES_RSS_URL,
}
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 1.0
MIN_FULLTEXT_THRESHOLD = 200
TURBO_WIDGET_TAGS = {"extretellwidget", "ext24smiwidget", "extsvknativewidget"}

DROP_QUERY_PARAMS = {
    "email",
    "giclickid",
    "subscription_id",
    "source",
    "id",
    "cid",
    "etext",
    "utm_source",
    "utm_campaign",
    "utm_medium",
    "utm_referrer",
    "utm_content",
    "utm_term",
    "nw",
    "gl",
    "from",
    "key",
    "utm_site",
    "fbclid",
    "slug",
    "sign",
    "clid",
    "print",
    "region",
    "region_name",
}


def canonical_url(url: str) -> str:
    """Normalize AIF article URL."""
    try:
        p = urlparse(url.strip())
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        params = {
            k: v for k, v in parse_qs(p.query).items()
            if k.lower() not in DROP_QUERY_PARAMS
        }
        query = urlencode(params, doseq=True) if params else ""
        return urlunparse(("https", host, path, "", query, ""))
    except Exception:
        return url


def parse_rss_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def title_hash(title: str) -> str:
    normalized = " ".join(title.lower().split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    cleaned = soup.get_text(" ", strip=True)
    return unescape(" ".join(cleaned.split()))


def normalize_turbo_tag_name(tag) -> str:
    return (getattr(tag, "name", "") or "").lower()


def is_turbo_widget(tag) -> bool:
    return normalize_turbo_tag_name(tag) in TURBO_WIDGET_TAGS


def is_related_feed_block(tag) -> bool:
    return normalize_turbo_tag_name(tag) == "div" and tag.get("data-block") == "feed"


def is_turbo_ad_placeholder(tag) -> bool:
    return normalize_turbo_tag_name(tag) == "figure" and bool(tag.get("data-turbo-ad-id"))


def paragraph_like_text(tag) -> str:
    if not tag:
        return ""
    html = "".join(str(x) for x in tag.contents)
    soup = BeautifulSoup(html, "html.parser")
    for nested in soup.find_all("div"):
        if nested.get("data-block") == "slider":
            nested.decompose()
    for nested in soup.find_all("figure"):
        nested.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    cleaned = soup.get_text(" ", strip=True)
    cleaned = cleaned.replace("\n ", "\n").replace(" \n", "\n")
    return unescape(" ".join(cleaned.split()))


def clean_turbo_content_to_text(value: str | None) -> str:
    """Clean noisy turbo content and return body-oriented plain text."""
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")

    # Remove wrappers and widgets that do not belong to the article body.
    for tag in list(soup.find_all()):
        if normalize_turbo_tag_name(tag) == "header" or is_turbo_widget(tag):
            tag.decompose()

    # Remove ad placeholders and injected related-content blocks.
    for tag in list(soup.find_all()):
        if is_turbo_ad_placeholder(tag) or is_related_feed_block(tag):
            tag.decompose()

    # Figures often duplicate captions/media already represented by thumbnail metadata.
    for tag in soup.find_all("figure"):
        tag.decompose()

    cleaned = soup.get_text(" ", strip=True)
    return unescape(" ".join(cleaned.split()))


def parse_turbo_content_blocks(value: str | None, thumbnail_url: str | None = None) -> dict:
    """Parse turbo:content into ordered content blocks.

    We keep only article-semantic blocks:
    - h2/h3/h4 as section headings
    - p as text paragraphs
    - figure/img as inline article images, excluding the header thumbnail

    We drop:
    - header block (title + hero image already come from other RSS fields)
    - widgets
    - ad placeholders
    - injected related-article feed blocks
    """
    result = {
        "blocks": [],
        "text": "",
        "inline_images": [],
        "headings": [],
    }
    if not value:
        return result

    soup = BeautifulSoup(value, "html.parser")

    root_children = [child for child in soup.contents if getattr(child, "name", None)]
    thumb_norm = (thumbnail_url or "").strip()

    blocks: list[dict] = []
    text_parts: list[str] = []
    inline_images: list[dict] = []
    headings: list[str] = []
    seen_images: set[str] = set()

    def clean_text_from_tag(tag) -> str:
        if normalize_turbo_tag_name(tag) == "p":
            return paragraph_like_text(tag)
        text = tag.get_text(" ", strip=True)
        return unescape(" ".join(text.split()))

    for child in root_children:
        name = normalize_turbo_tag_name(child)
        if not name:
            continue

        # Skip non-article wrappers and widgets.
        if name == "header":
            continue
        if is_turbo_widget(child):
            continue
        if is_related_feed_block(child):
            continue
        if is_turbo_ad_placeholder(child):
            continue

        if name in {"h2", "h3", "h4"}:
            heading = clean_text_from_tag(child)
            if heading:
                blocks.append({"type": "heading", "level": int(name[1]), "text": heading})
                headings.append(heading)
                text_parts.append(heading)
            continue

        if name == "p":
            paragraph = clean_text_from_tag(child)
            if paragraph:
                blocks.append({"type": "paragraph", "text": paragraph})
                text_parts.append(paragraph)
            continue

        if name == "figure":
            img = child.find("img")
            if not img:
                continue
            src = (img.get("src") or "").strip()
            if not src or src == thumb_norm or src in seen_images:
                continue
            seen_images.add(src)
            caption_tag = child.find("figcaption")
            caption = clean_text_from_tag(caption_tag) if caption_tag else None
            image_block = {"type": "image", "src": src, "caption": caption}
            blocks.append(image_block)
            inline_images.append(image_block)
            continue

    result["blocks"] = blocks
    result["text"] = "\n\n".join(text_parts).strip()
    result["inline_images"] = inline_images
    result["headings"] = headings
    return result


def get_enclosure_url(enclosures: list[dict]) -> str | None:
    if not enclosures:
        return None
    for enclosure in enclosures:
        url = (enclosure.get("href") or enclosure.get("url") or "").strip()
        if url:
            return url
    return None


def choose_demo_article(articles: list[dict]) -> dict:
    """Pick the richest entry to validate structured turbo parsing."""
    def score(article: dict) -> tuple:
        return (
            len(article.get("inline_images") or []),
            len(article.get("turbo_headings") or []),
            1 if article.get("theme_tags") else 0,
            len(article.get("related_links") or []),
            len(article.get("content_turbo_structured") or ""),
        )

    return max(articles, key=score)


def resolve_feed_from_argv() -> tuple[str, str]:
    if len(sys.argv) < 2:
        return "news", FEEDS["news"]

    requested = sys.argv[1].strip().lower()
    if requested not in FEEDS:
        allowed = ", ".join(FEEDS.keys())
        raise SystemExit(f"Unknown feed '{requested}'. Use one of: {allowed}")

    return requested, FEEDS[requested]


async def step1_fetch_rss(feed_name: str, feed_url: str) -> tuple[bytes, dict]:
    print("\n" + "=" * 60)
    print("ШАГ 1: Загрузка RSS-фида")
    print("=" * 60)
    print(f"News RSS:     {RSS_URL}")
    print(f"Articles RSS: {ARTICLES_RSS_URL}")
    print(f"Selected RSS: {feed_name} -> {feed_url}")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(feed_url, headers={"User-Agent": USER_AGENT})

    etag = response.headers.get("etag")
    last_mod = response.headers.get("last-modified")

    print(f"\nHTTP статус:   {response.status_code}")
    print(f"Content-Type:  {response.headers.get('content-type', '—')}")
    print(f"ETag:          {etag or 'не поддерживается'}")
    print(f"Last-Modified: {last_mod or 'не поддерживается'}")
    print(f"Размер:        {len(response.content):,} байт")

    response.raise_for_status()
    return response.content, {"etag": etag, "modified": last_mod}


def get_direct_text(tag, name: str) -> str:
    child = tag.find(name, recursive=False)
    if not child:
        return ""
    return child.get_text(strip=True)


def get_direct_tag_html(tag, name: str) -> str:
    child = tag.find(name, recursive=False)
    if not child:
        return ""
    return "".join(str(x) for x in child.contents).strip()


def get_related_links(item) -> list[dict]:
    related = item.find("yandex:related", recursive=False)
    if not related:
        return []
    links = []
    for link in related.find_all("link", recursive=False):
        url = (link.get("url") or "").strip()
        title = link.get_text(" ", strip=True)
        img = (link.get("img") or "").strip() or None
        if url:
            links.append({"url": url, "title": title, "img": img})
    return links


def step2_parse_rss(raw_content: bytes) -> list[dict]:
    print("\n" + "=" * 60)
    print("ШАГ 2: Парсинг RSS")
    print("=" * 60)

    soup = BeautifulSoup(raw_content, "xml")
    channel = soup.find("channel")
    items = channel.find_all("item", recursive=False) if channel else []
    print(f"Записей в фиде: {len(items)}")
    print(f"lastBuildDate:   {get_direct_text(channel, 'lastBuildDate') or 'отсутствует'}")
    print(f"ttl:             {get_direct_text(channel, 'ttl') or 'отсутствует'}")

    if not items:
        return []

    first = items[0]
    first_enclosures = first.find_all("enclosure", recursive=False)
    first_fulltext = get_direct_tag_html(first, "yandex:full-text")
    first_turbo = get_direct_tag_html(first, "turbo:content")
    first_categories = [tag.get_text(strip=True) for tag in first.find_all("category", recursive=False)]
    first_related = get_related_links(first)
    first_thumbnail = get_enclosure_url([
        {
            "href": (tag.get("url") or "").strip(),
            "url": (tag.get("url") or "").strip(),
            "type": (tag.get("type") or "").strip(),
            "length": (tag.get("length") or "").strip(),
        }
        for tag in first_enclosures
    ])
    first_turbo_structured = parse_turbo_content_blocks(first_turbo, first_thumbnail)
    first_inline_images = first_turbo_structured["inline_images"]

    print("\n--- Структура первой записи ---")
    print(f"title:         {get_direct_text(first, 'title') or '—'}")
    print(f"link:          {get_direct_text(first, 'link') or '—'}")
    print(f"guid/id:       {get_direct_text(first, 'guid') or 'отсутствует'}")
    print(f"published:     {get_direct_text(first, 'pubDate') or '—'}")
    print(f"description:   {html_to_text(get_direct_tag_html(first, 'description'))[:160]}")
    print(f"author:        {get_direct_text(first, 'author') or 'отсутствует'}")
    print(f"categories:    {first_categories}")
    print(f"enclosures:    {len(first_enclosures)}")
    print(f"yandex_full_text: {'да' if first_fulltext else 'нет'}")
    print(f"turbo_content:    {'да' if first_turbo else 'нет'}")
    print(f"related_links:    {len(first_related)}")
    print(f"theme_tags:       {get_direct_text(first, 'yandex:theme_tags') or 'отсутствует'}")
    print(f"inline_images:    {len(first_inline_images)}")
    if first_inline_images:
        print(f"inline_img[0]:    {first_inline_images[0]}")
    if first_enclosures:
        print(f"enclosure[0]:  {{'url': '{first_enclosures[0].get('url') or ''}', 'type': '{first_enclosures[0].get('type') or ''}', 'length': '{first_enclosures[0].get('length') or ''}'}}")

    articles = []
    with_author = 0
    with_category = 0
    with_enclosure = 0
    with_fulltext = 0
    with_turbo = 0
    with_related = 0
    with_theme_tags = 0
    with_inline_images = 0

    for entry in items:
        author = get_direct_text(entry, "author") or None
        categories = [tag.get_text(strip=True) for tag in entry.find_all("category", recursive=False)]
        enclosures = [
            {
                "href": (tag.get("url") or "").strip(),
                "url": (tag.get("url") or "").strip(),
                "type": (tag.get("type") or "").strip(),
                "length": (tag.get("length") or "").strip(),
            }
            for tag in entry.find_all("enclosure", recursive=False)
        ]
        thumbnail = get_enclosure_url(enclosures)
        fulltext_raw = get_direct_tag_html(entry, "yandex:full-text")
        turbo_raw = get_direct_tag_html(entry, "turbo:content")
        related_links = get_related_links(entry)
        theme_tags = get_direct_text(entry, "yandex:theme_tags") or None
        url = get_direct_text(entry, "link")
        turbo_structured = parse_turbo_content_blocks(turbo_raw, thumbnail)
        inline_images = turbo_structured["inline_images"]

        if author:
            with_author += 1
        if categories:
            with_category += 1
        if thumbnail:
            with_enclosure += 1
        if fulltext_raw:
            with_fulltext += 1
        if turbo_raw:
            with_turbo += 1
        if related_links:
            with_related += 1
        if theme_tags:
            with_theme_tags += 1
        if inline_images:
            with_inline_images += 1

        articles.append({
            "url": url,
            "canonical_url": canonical_url(url),
            "guid": get_direct_text(entry, "guid") or None,
            "pdalink": get_direct_text(entry, "pdalink") or None,
            "title": get_direct_text(entry, "title"),
            "snippet_lead": html_to_text(get_direct_tag_html(entry, "description")),
            "published_at": parse_rss_date(get_direct_text(entry, "pubDate")),
            "author": author,
            "categories": categories,
            "thumbnail": thumbnail,
            "content_rss": html_to_text(fulltext_raw),
            "content_turbo": clean_turbo_content_to_text(turbo_raw),
            "content_turbo_structured": turbo_structured["text"],
            "source_fulltext_raw": fulltext_raw,
            "source_turbo_raw": turbo_raw,
            "related_links": related_links,
            "theme_tags": theme_tags,
            "inline_images": inline_images,
            "turbo_blocks": turbo_structured["blocks"],
            "turbo_headings": turbo_structured["headings"],
        })

    print(f"\nС author:             {with_author}/{len(articles)}")
    print(f"С category:           {with_category}/{len(articles)}")
    print(f"С thumbnail/enclosure:{with_enclosure}/{len(articles)}")
    print(f"С yandex_full_text:   {with_fulltext}/{len(articles)}")
    print(f"С turbo_content:      {with_turbo}/{len(articles)}")
    print(f"С related_links:      {with_related}/{len(articles)}")
    print(f"С theme_tags:         {with_theme_tags}/{len(articles)}")
    print(f"С inline_images:      {with_inline_images}/{len(articles)}")

    print("\nПервые 5 заголовков:")
    for article in articles[:5]:
        t = article["published_at"].strftime("%H:%M UTC") if article["published_at"] else "—"
        print(f"  [{t}] {article['title'][:80]}")

    return articles


async def step3_compare_fulltext(article: dict) -> dict:
    print("\n" + "=" * 60)
    print("ШАГ 3: Оценка полного текста из RSS")
    print("=" * 60)
    print(f"Статья: {article['title'][:80]}")
    print(f"URL:    {article['canonical_url']}")
    print(f"Пауза {CRAWL_DELAY} сек...", end=" ", flush=True)
    await asyncio.sleep(CRAWL_DELAY)
    print("готово")

    content_rss = article.get("content_rss", "")
    content_turbo = article.get("content_turbo", "")
    content_turbo_structured = article.get("content_turbo_structured", "")

    # Prefer structured turbo when it is good enough:
    # it preserves headings and inline images while removing obvious noise.
    if len(content_turbo_structured) >= MIN_FULLTEXT_THRESHOLD:
        best_text = content_turbo_structured
        extraction_method = "rss_turbo_structured"
    elif len(content_rss) >= MIN_FULLTEXT_THRESHOLD:
        best_text = content_rss
        extraction_method = "rss_yandex_full_text_fallback"
    elif len(content_turbo) >= MIN_FULLTEXT_THRESHOLD:
        best_text = content_turbo
        extraction_method = "rss_turbo_content_fallback"
    else:
        candidates = [
            ("rss_turbo_structured", content_turbo_structured),
            ("rss_yandex_full_text_fallback", content_rss),
            ("rss_turbo_content_fallback", content_turbo),
        ]
        extraction_method, best_text = max(candidates, key=lambda x: len(x[1]))

    quality = "ok" if len(best_text) >= MIN_FULLTEXT_THRESHOLD else "low"

    print(f"Длина yandex_full_text: {len(content_rss):,} символов")
    print(f"Длина turbo_content:    {len(content_turbo):,} символов")
    print(f"Длина turbo_structured: {len(content_turbo_structured):,} символов")
    print(f"Inline images:          {len(article.get('inline_images') or [])}")
    print(f"Structured blocks:      {len(article.get('turbo_blocks') or [])}")
    print(f"Headings:               {len(article.get('turbo_headings') or [])}")
    if article.get("turbo_headings"):
        print(f"Heading list:           {article.get('turbo_headings')}")
    print("Предпочтение источника: turbo_structured > yandex_full_text > cleaned turbo_content")
    print(f"Выбранный метод:        {extraction_method}")

    if best_text:
        print("\nПревью текста:")
        print("-" * 40)
        print(best_text)
        print("-" * 40)

    return {
        **article,
        "content": best_text,
        "quality": quality,
        "extraction_method": extraction_method,
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
    print(f"  source_guid:      {article.get('guid')}")
    print(f"  pdalink:          {article.get('pdalink')}")
    print(f"  categories:       {article.get('categories')}")
    print(f"  thumbnail_rss:    {article.get('thumbnail')}")
    print(f"  yandex_fulltext:  {bool(article.get('source_fulltext_raw'))}")
    print(f"  turbo_content:    {bool(article.get('source_turbo_raw'))}")
    print(f"  related_count:    {len(article.get('related_links') or [])}")
    print(f"  theme_tags:       {article.get('theme_tags')}")
    print(f"  inline_images:    {len(article.get('inline_images') or [])}")
    if article.get("inline_images"):
        for idx, image in enumerate(article.get("inline_images", [])[:3], start=1):
            print(f"  inline_image_{idx}:  {image}")
    print(f"  turbo_headings:   {article.get('turbo_headings')}")
    print(f"  extraction_method:{article.get('extraction_method')}")


async def main():
    feed_name, feed_url = resolve_feed_from_argv()
    print("ТЕСТ СБОРА: АИФ")
    print("Особенности: author/category/full-text уже есть в RSS, turbo_content доступен, HTML может не понадобиться")

    print(f"Feed mode: {feed_name}")
    raw_content, cache_info = await step1_fetch_rss(feed_name, feed_url)
    articles = step2_parse_rss(raw_content)
    if not articles:
        return

    demo = choose_demo_article(articles)
    print("\nДля демонстрации выбрана наиболее структурно богатая запись из фида.")
    enriched = await step3_compare_fulltext(demo)
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
    print(f"Thumbnail RSS:    {enriched.get('thumbnail') or '—'}")


if __name__ == "__main__":
    asyncio.run(main())
