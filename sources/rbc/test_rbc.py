"""
Пошаговый тест сбора с РБК.

Ключевая особенность: <rbc_news:full-text> содержит полный текст прямо в RSS.
Как у ТАСС yandex.xml — не нужно ходить на страницы статей!

Важно: <guid isPermaLink="false"> — НЕ URL, нельзя использовать для дедупликации.
Используем <link> как canonical_url.

Запуск: python sources/rbc/test_rbc.py

Зависимости: pip install httpx feedparser beautifulsoup4 lxml
"""

import asyncio
import calendar
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse
import xml.etree.ElementTree as ET

import feedparser
import httpx
from bs4 import BeautifulSoup

# ─── Конфигурация ────────────────────────────────────────────────────────────

RSS_URL = "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
RBC_NS = "https://www.rbc.ru"

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        return urlunparse(("https", host, path, "", "", ""))
    except Exception:
        return url


def title_hash(title: str) -> str:
    normalized = " ".join(title.lower().split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def parse_date(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            ts = calendar.timegm(parsed)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def extract_rbc_fields(raw_xml_bytes: bytes) -> dict[str, dict]:
    """
    feedparser не знает про rbc_news: namespace.
    Извлекаем через ElementTree:
      - rbc_news:full-text  → полный текст (HTML-фрагмент)
      - rbc_news:tag        → список тегов (может быть несколько!)
      - rbc_news:newsline   → тематическая линия (society, politics...)
      - rbc_news:type       → тип материала (short_news, article...)
      - rbc_news:news_id    → ID материала

    Возвращает СПИСОК в том же порядке что items в XML.

    Важно: НЕ используем <link> как ключ!
    feedparser путается: <link url="..."> внутри <rbc_news:related_links>
    конкурирует с настоящим <link> статьи → feedparser берёт последний
    встреченный URL из related_links вместо URL статьи.
    Решение: возвращаем список по позиции, URL берём из <pdalink>
    (однозначный элемент, не встречается внутри related_links).
    """
    result = []
    try:
        root = ET.fromstring(raw_xml_bytes)
        channel = root.find("channel")
        if channel is None:
            return result

        for item in channel.findall("item"):
            # pdalink — надёжный URL, не путается с related_links
            pdalink_el = item.find("pdalink")
            link_el = item.find("link")
            url = ""
            if pdalink_el is not None and pdalink_el.text:
                url = pdalink_el.text.strip()
            elif link_el is not None and link_el.text:
                url = link_el.text.strip()

            # Полный текст
            ft_el = item.find(f"{{{RBC_NS}}}full-text")
            full_text_html = (ft_el.text or "").strip() if ft_el is not None else ""
            clean_text = ""
            if full_text_html:
                soup = BeautifulSoup(full_text_html, "html.parser")
                clean_text = soup.get_text(separator="\n", strip=True)

            # Теги (несколько элементов rbc_news:tag на item)
            tag_els = item.findall(f"{{{RBC_NS}}}tag")
            tags = [t.text.strip() for t in tag_els if t.text and t.text.strip()]

            def get_field(tag: str) -> str | None:
                el = item.find(f"{{{RBC_NS}}}{tag}")
                return el.text.strip() if el is not None and el.text else None

            result.append({
                "url": url,
                "canonical_url": canonical_url(url),
                "full_text": clean_text,
                "full_text_html": full_text_html,
                "tags": tags,
                "newsline": get_field("newsline"),
                "type": get_field("type"),
                "news_id": get_field("news_id"),
                "timestamp": get_field("newsDate_timestamp"),
            })

    except Exception as e:
        print(f"  Ошибка парсинга rbc_news: namespace: {e}")
    return result


# ─── Шаги сбора ──────────────────────────────────────────────────────────────

async def step1_fetch_rss() -> tuple[bytes | None, dict]:
    """
    Шаг 1: Скачать RSS.
    Проверяем ETag/Last-Modified и тест условного запроса.
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
    etag = response.headers.get("etag")
    last_mod = response.headers.get("last-modified")
    print(f"ETag: {etag or 'не поддерживается'}")
    print(f"Last-Modified: {last_mod or 'не поддерживается'}")
    print(f"Размер ответа: {len(response.content):,} байт")

    # Тест ETag если есть
    if etag or last_mod:
        print(f"\nТест условного запроса (If-None-Match / If-Modified-Since)...")
        cond_headers = {"User-Agent": USER_AGENT}
        if etag:
            cond_headers["If-None-Match"] = etag
        if last_mod:
            cond_headers["If-Modified-Since"] = last_mod

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            r2 = await client.get(RSS_URL, headers=cond_headers)

        if r2.status_code == 304:
            print(f"  ✓ 304 Not Modified — ETag работает, экономия {len(response.content):,} байт")
        else:
            print(f"  Статус: {r2.status_code} (фид обновился между запросами — норма)")

    response.raise_for_status()
    cache_info = {"etag": etag, "modified": last_mod}
    return response.content, cache_info


def step2_parse_rss(raw_content: bytes) -> list[dict]:
    """
    Шаг 2: Парсинг RSS + извлечение rbc_news: namespace.

    feedparser — для стандартных полей.
    ElementTree — для rbc_news:full-text, rbc_news:tag и других кастомных полей.
    """
    print("\n" + "="*60)
    print("ШАГ 2: Парсинг RSS + rbc_news: namespace")
    print("="*60)

    feed = feedparser.parse(raw_content)
    print(f"Записей в фиде: {len(feed.entries)}")

    if not feed.entries:
        return []

    print("\nИзвлекаем кастомные поля через ElementTree...")
    rbc_list = extract_rbc_fields(raw_content)
    print(f"rbc_news поля найдены: {len(rbc_list)} items")

    # Анализ первой записи
    # Берём URL из ElementTree (надёжный), а не из feedparser (может ошибаться)
    first = feed.entries[0]
    first_rbc = rbc_list[0] if rbc_list else {}

    print("\n--- Структура первой записи ---")
    print(f"title:         {first.get('title', '—')[:70]}")
    print(f"link (feedparser): {first.get('link', '—')}  ← может быть неверным!")
    print(f"link (ET/pdalink): {first_rbc.get('url', '—')}  ← правильный URL")
    print(f"guid:          {first.get('id', '—')}  ← НЕ URL!")
    print(f"author:        {first.get('author', '—')}")
    print(f"category:      {[t.get('term', '') for t in first.get('tags', [])]}")
    print(f"published:     {first.get('published', '—')}")
    print(f"description:   '{first.get('summary', '')[:80]}'")
    print(f"\nrbc_news:newsline: {first_rbc.get('newsline', '—')}")
    print(f"rbc_news:type:     {first_rbc.get('type', '—')}")
    print(f"rbc_news:tags:     {first_rbc.get('tags', [])}")
    ft = first_rbc.get('full_text', '')
    print(f"rbc_news:full-text: {len(ft):,} символов" if ft else "rbc_news:full-text: ПУСТО")

    if ft:
        print(f"\nПревью full-text:")
        print("-" * 40)
        print(ft[:300])
        print("-" * 40)

    # Собираем статьи: сопоставляем feedparser и ElementTree по позиции
    # (оба парсят один XML в одном порядке)
    articles = []
    for i, entry in enumerate(feed.entries):
        rbc = rbc_list[i] if i < len(rbc_list) else {}
        # URL из ElementTree — надёжный (pdalink, не путается с related_links)
        raw_url = rbc.get("url") or entry.get("link", "").strip()
        can_url = rbc.get("canonical_url") or canonical_url(raw_url)
        full_text = rbc.get("full_text", "")
        description = entry.get("summary", "").strip()

        articles.append({
            "url": raw_url,
            "canonical_url": can_url,
            "title": entry.get("title", ""),
            "description": description,
            "full_text": full_text,
            "has_fulltext": bool(full_text),
            "published_at": parse_date(entry),
            "author": entry.get("author", ""),
            "categories": [t.get("term", "") for t in entry.get("tags", [])],
            "rbc_newsline": rbc.get("newsline"),
            "rbc_type": rbc.get("type"),
            "rbc_tags": rbc.get("tags", []),
            "rbc_news_id": rbc.get("news_id"),
        })

    # Сводная статистика
    print(f"\n→ Итого записей: {len(articles)}")
    with_ft = sum(1 for a in articles if a["has_fulltext"])
    with_author = sum(1 for a in articles if a["author"])
    print(f"  full-text есть: {with_ft} ({with_ft*100//len(articles) if articles else 0}%)")
    print(f"  author есть:    {with_author} ({with_author*100//len(articles) if articles else 0}%)")

    # Распределение newsline
    newslines: dict[str, int] = {}
    for a in articles:
        nl = a["rbc_newsline"] or "?"
        newslines[nl] = newslines.get(nl, 0) + 1
    print(f"\nРаспределение rbc_news:newsline:")
    for nl, cnt in sorted(newslines.items(), key=lambda x: -x[1])[:10]:
        print(f"  {nl}: {cnt}")

    # Распределение type
    types: dict[str, int] = {}
    for a in articles:
        t = a["rbc_type"] or "?"
        types[t] = types.get(t, 0) + 1
    print(f"\nРаспределение rbc_news:type:")
    for t, cnt in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {cnt}")

    print("\nПервые 5 заголовков:")
    for a in articles[:5]:
        date_str = a["published_at"].strftime("%H:%M UTC") if a["published_at"] else "—"
        ft_mark = "📄" if a["has_fulltext"] else "✗"
        author_str = f" [{a['author']}]" if a["author"] else ""
        print(f"  {ft_mark} [{date_str}]{author_str} {a['title'][:55]}")

    return articles


def step3_show_content(article: dict) -> dict:
    """
    Шаг 3: Показать извлечённый контент.

    В отличие от Ленты и Коммерсанта — HTTP-запрос на страницу НЕ нужен.
    Полный текст уже в rbc_news:full-text.
    """
    print("\n" + "="*60)
    print("ШАГ 3: Контент (из RSS, без HTTP-запроса на страницу)")
    print("="*60)
    print(f"Статья: {article['title']}")
    print(f"Автор:  {article['author'] or '—'}")
    print(f"Линия:  {article['rbc_newsline'] or '—'} | Тип: {article['rbc_type'] or '—'}")

    if article["has_fulltext"]:
        content = article["full_text"]
        extraction_method = "rbc_full_text"
        print(f"\n✓ rbc_news:full-text: {len(content):,} символов")
        print(f"  (HTTP-запрос на страницу НЕ нужен!)")
        print(f"\nПолный текст:")
        print("-" * 40)
        print(content)
        print("-" * 40)
    else:
        content = article["description"]
        extraction_method = "rss_description_fallback"
        print(f"\n⚠️  full-text отсутствует → используем description: {len(content)} симв")

    return {**article, "content": content, "extraction_method": extraction_method}


def step4_show_what_goes_to_db(article: dict) -> None:
    print("\n" + "="*60)
    print("ШАГ 4: Что пошло бы в базу данных")
    print("="*60)

    th = title_hash(article["title"])
    content = article.get("content", "")

    print("\n--- Таблица news ---")
    print(f"url:              {article['url']}")
    print(f"canonical_url:    {article['canonical_url']}")
    print(f"title:            {article['title'][:70]}")
    print(f"author:           {article['author'] or '—'}")
    print(f"content длина:    {len(content):,} символов")
    if content:
        print(f"snippet_lead:     {article['description'][:120]}...")
    print(f"published_at:     {article.get('published_at')} (UTC)")
    print(f"channel_type:     RSS")
    print(f"information_type: daily")
    print(f"content_type:     {article.get('rbc_type', 'news')}")
    print(f"title_hash:       {th}")
    print(f"extra JSONB:")
    print(f"  rbc_newsline:      {article.get('rbc_newsline')}")
    print(f"  rbc_type:          {article.get('rbc_type')}")
    print(f"  rbc_tags:          {article.get('rbc_tags', [])}")
    print(f"  rbc_news_id:       {article.get('rbc_news_id')}")
    print(f"  extraction_method: {article.get('extraction_method')}")

    print("\n--- Таблица news_raw ---")
    print(f"raw_content длина: {len(article.get('full_text', '')):,} символов (HTML-фрагмент из RSS)")
    print(f"raw_format:        html_fragment")
    print(f"parser_version:    rbc-v1")
    print(f"\n→ Страница статьи НЕ скачивалась (экономия HTTP-запроса!)")


async def main():
    print("ТЕСТ СБОРА: РБК")
    print("rbc_news:full-text → полный текст прямо в RSS, как у ТАСС!")
    print("Важно: <guid> — НЕ URL, используем <link>")

    raw_content, cache_info = await step1_fetch_rss()
    if raw_content is None:
        return

    articles = step2_parse_rss(raw_content)
    if not articles:
        return

    # Берём первую статью с full-text
    demo = next((a for a in articles if a["has_fulltext"]), articles[0])
    print(f"\nДемонстрация: {demo['title'][:60]}")

    enriched = step3_show_content(demo)
    step4_show_what_goes_to_db(enriched)

    print("\n" + "="*60)
    print("ИТОГ")
    print("="*60)
    print(f"RSS записей:         {len(articles)}")
    with_ft = sum(1 for a in articles if a["has_fulltext"])
    print(f"С full-text:         {with_ft} ({with_ft*100//len(articles)}%)")
    print(f"ETag: {cache_info.get('etag', '—')}")
    print(f"\nHTTP-запросов за цикл сбора: 1 (только RSS!)")


if __name__ == "__main__":
    asyncio.run(main())
