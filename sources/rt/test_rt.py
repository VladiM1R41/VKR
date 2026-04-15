"""
Пошаговый тест сбора с RT на русском.

Ключевые особенности:
- <link> и <guid> содержат UTM-параметры (?utm_source=rss...) — убирать ОБЯЗАТЕЛЬНО
  (robots.txt Disallow: *? — любой URL с query params запрещён)
- <description> — HTML-фрагмент с лидом + <a>Читать далее</a> — чистить
- <dc:creator> = "RT на русском" всегда — оставлять как author (не журналист, название канала)
- <category> отсутствует — секцию брать из URL (/world/, /ussr/, /sport/)
- Нет enclosure/thumbnail в RSS

Запуск: python sources/rt/test_rt.py

Зависимости: pip install httpx feedparser trafilatura beautifulsoup4
"""

import asyncio
import calendar
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import sys

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

# ─── Конфигурация ────────────────────────────────────────────────────────────

RSS_URL = "https://russian.rt.com/rss"
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 1.0
PAYWALL_THRESHOLD = 200

# UTM-параметры которые RT добавляет в RSS-ссылки
RT_UTM_PARAMS = {"utm_source", "utm_medium", "utm_campaign"}

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    """
    Убрать UTM и другие query params.
    robots.txt Disallow: *? — ЛЮБОЙ URL с ? запрещён.
    Поэтому убираем все query params, не только UTM.
    """
    try:
        p = urlparse(url.strip())
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        # Убираем все query params (robots.txt Disallow: *?)
        return urlunparse(("https", host, path, "", "", ""))
    except Exception:
        return url


def extract_section(url: str) -> str | None:
    """
    Извлечь секцию из URL (category в RSS отсутствует).
    "https://russian.rt.com/world/news/1615698-indiya..." → "world"
    "https://russian.rt.com/ussr/news/..."               → "ussr"
    """
    try:
        parts = urlparse(url).path.strip("/").split("/")
        return parts[0] if parts else None
    except Exception:
        return None


def clean_description(raw_html: str) -> str:
    """
    Очистить HTML из description:
    - Убрать <a href="...">Читать далее</a>
    - Убрать остальные HTML-теги
    - Нормализовать пробелы
    """
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    # Удалить ссылку "Читать далее" целиком
    for a in soup.find_all("a"):
        a.decompose()
    text = soup.get_text(separator=" ", strip=True)
    # Убрать возможный остаток "Читать далее" (на случай если тег уже был текстом)
    text = re.sub(r'\s*Читать далее\.?\s*$', '', text, flags=re.IGNORECASE).strip()
    return text


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

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(RSS_URL, headers={"User-Agent": USER_AGENT})

    etag = response.headers.get("etag")
    last_mod = response.headers.get("last-modified")
    print(f"\nHTTP статус:   {response.status_code}")
    print(f"Content-Type:  {response.headers.get('content-type', '—')}")
    print(f"ETag:          {etag or 'не поддерживается'}")
    print(f"Last-Modified: {last_mod or 'не поддерживается'}")
    print(f"Размер:        {len(response.content):,} байт")

    # Тест условного запроса если есть кэш-заголовки
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
            print(f"  ✓ 304 Not Modified — ETag работает, экономия {len(response.content):,} байт")
        else:
            print(f"  Статус: {r2.status_code} (фид обновился между запросами — норма)")

    response.raise_for_status()
    return response.content, {"etag": etag, "modified": last_mod}


def step2_parse_rss(raw_content: bytes) -> list[dict]:
    """
    Шаг 2: Парсинг RSS.

    Главные задачи:
    1. Убрать UTM из link/guid → canonical_url
    2. Очистить HTML из description → snippet_lead
    3. Извлечь секцию из URL (category в RSS нет)
    4. dc:creator → author (сохраняем "RT на русском", не журналист — название канала)
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
    raw_desc = first.get("summary", "")
    clean_desc = clean_description(raw_desc)

    print(f"\n--- Структура первой записи ---")
    print(f"title:           {first.get('title', '—')[:70]}")
    print(f"link (сырой):    {raw_link}")
    print(f"link (canonical):{clean}  ← UTM убраны")
    print(f"guid:            {first.get('id', '—')[:80]}")
    print(f"dc:creator:      '{first.get('author', '—')}'  ← сохраняем как author")
    print(f"published:       {first.get('published', '—')}")
    print(f"\ndescription (сырой HTML):")
    print(f"  '{raw_desc[:120]}'")
    print(f"description (очищенный):")
    print(f"  '{clean_desc}'")
    print(f"\nsection из URL:  '{extract_section(clean)}'")

    # Сборка всех статей
    articles = []
    sections: dict[str, int] = {}

    for entry in feed.entries:
        raw_url = entry.get("link", "").strip()
        can_url = canonical_url(raw_url)
        section = extract_section(can_url)
        desc_html = entry.get("summary", "")
        snippet = clean_description(desc_html)

        sections[section or "?"] = sections.get(section or "?", 0) + 1

        articles.append({
            "url": raw_url,           # оригинальный (с UTM) — для raw хранения
            "canonical_url": can_url, # без UTM — для дедупликации и HTTP-запроса
            "title": entry.get("title", ""),
            "author": entry.get("author", "") or "RT на русском",  # dc:creator
            "snippet_lead": snippet,
            "published_at": parse_date(entry),
            "section": section,
        })

    print(f"\nВсего статей: {len(articles)}")
    print(f"\nРаспределение по секциям:")
    for sec, cnt in sorted(sections.items(), key=lambda x: -x[1]):
        print(f"  /{sec}/: {cnt}")

    print(f"\nПервые 5 заголовков:")
    for a in articles[:5]:
        t = a["published_at"].strftime("%H:%M UTC") if a["published_at"] else "—"
        print(f"  [{t}] [{a['section']}] {a['title'][:55]}", flush=True)
    sys.stdout.flush()

    return articles


async def step3_get_full_text(article: dict) -> dict:
    """
    Шаг 3: Полный текст со страницы.
    Используем canonical_url (без UTM!) — robots.txt Disallow: *?
    """
    print("\n" + "="*60)
    print("ШАГ 3: Получение полного текста")
    print("="*60)
    print(f"Статья:  {article['title'][:60]}")
    print(f"Секция:  /{article['section']}/")
    print(f"URL:     {article['canonical_url']}")
    print(f"(UTM убраны — robots.txt Disallow: *?)")
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

    doc = trafilatura.bare_extraction(
        response.text,
        url=article["canonical_url"],
        include_comments=False,
        favor_precision=True,
        deduplicate=True,
    )
    raw_text = (doc.text or "") if doc else ""

    if len(raw_text) < PAYWALL_THRESHOLD:
        doc2 = trafilatura.bare_extraction(
            response.text,
            url=article["canonical_url"],
            favor_recall=True,
        )
        raw_text2 = (doc2.text or "") if doc2 else ""
        if len(raw_text2) > len(raw_text):
            raw_text = raw_text2

    # RT прячет основной текст в article__text + article__summary
    # trafilatura часто берёт только summary — берём оба блока через BS4
    extraction_method = "trafilatura"
    soup = BeautifulSoup(response.text, "html.parser")
    parts = []
    for cls in ("article__summary", "article__text"):
        block = soup.find(class_=cls)
        if block:
            for tag in block.find_all(["script", "style", "figure"]):
                tag.decompose()
            text = block.get_text(separator="\n", strip=True)
            if text:
                parts.append(text)
    bs4_text = "\n\n".join(parts)

    # Также собираем теги статьи
    tags = []
    tags_block = soup.find(class_="article__tags-trends")
    if tags_block:
        tags = [a.get_text(strip=True) for a in tags_block.find_all("a")]

    print(f"\nBS4 extraction: {len(bs4_text):,} символов")
    print(f"Теги: {tags}")

    if len(bs4_text) > len(raw_text):
        raw_text = bs4_text
        extraction_method = "bs4_article_blocks"

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

    return {**article, "content": raw_text, "quality": quality, "tags": tags, "raw_html": response.text}


def step4_show_what_goes_to_db(article: dict) -> None:
    print("\n" + "="*60)
    print("ШАГ 4: Что пошло бы в базу данных")
    print("="*60)

    content = article.get("content", "")
    print("\n--- Таблица news ---")
    print(f"url:              {article['url'][:80]}...")
    print(f"canonical_url:    {article['canonical_url']}  ← без UTM")
    print(f"title:            {article['title'][:70]}")
    print(f"author:           '{article.get('author', 'RT на русском')}'")
    print(f"content длина:    {len(content):,} символов")
    print(f"snippet_lead:     '{article['snippet_lead'][:100]}'")
    print(f"published_at:     {article.get('published_at')} (UTC)")
    print(f"information_type: daily")
    print(f"quality:          {article.get('quality', 'ok')}")
    print(f"title_hash:       {title_hash(article['title'])}")
    print(f"extra JSONB:")
    print(f"  rt_section:   {article.get('section')}")
    print(f"  tags:         {article.get('tags', [])}")
    print(f"  thumbnail:    null  (нет в RSS)")

    print("\n--- Таблица news_raw ---")
    print(f"raw_content длина:{len(article.get('raw_html', '')):,} символов")
    print(f"raw_format:       html")
    print(f"parser_version:   rt-v1")


async def main():
    print("ТЕСТ СБОРА: RT НА РУССКОМ")
    print("Главные особенности: UTM в link/guid, HTML в description, нет category")

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
    print(f"ETag:             {cache_info.get('etag', '—')}")
    print(f"Last-Modified:    {cache_info.get('modified', '—')}")
    print(f"Качество текста:  {enriched.get('quality')}")
    print(f"snippet_lead:     {'есть' if enriched['snippet_lead'] else 'ПУСТО'}")
    print(f"\nrobots.txt Disallow: *? → все запросы к статьям БЕЗ query params!")


if __name__ == "__main__":
    asyncio.run(main())
