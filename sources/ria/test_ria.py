"""
Пошаговый тест сбора с РИА Новости.

Ключевая особенность: RSS отдаёт ТОЛЬКО заголовок + ссылку.
Всё остальное (текст, теги, рубрика) — только со страницы статьи.
Бонус: в HTML страниц есть window.dataLayer с реальной тематикой.

Запуск: python sources/ria/test_ria.py

Зависимости: pip install httpx feedparser trafilatura
"""

import asyncio
import calendar
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import feedparser
import httpx
import trafilatura

# ─── Конфигурация ────────────────────────────────────────────────────────────

RSS_URL = "https://ria.ru/export/rss2/archive/index.xml"
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 1.0

RIAN_NS = "http://rian.ru/ns"

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        # robots.txt: нельзя добавлять query params к статьям
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


def extract_rian_fields(raw_xml_bytes: bytes) -> dict[str, dict]:
    """
    feedparser не знает про rian: namespace.
    Извлекаем rian:priority и rian:type вручную через ElementTree.

    Возвращает dict: canonical_url → {"priority": int, "type": str}
    """
    result = {}
    try:
        root = ET.fromstring(raw_xml_bytes)
        channel = root.find("channel")
        if channel is None:
            return result

        for item in channel.findall("item"):
            link_el = item.find("link")
            url = (link_el.text or "").strip() if link_el is not None else ""
            can = canonical_url(url)

            priority_el = item.find(f"{{{RIAN_NS}}}priority")
            type_el = item.find(f"{{{RIAN_NS}}}type")

            result[can] = {
                "priority": int(priority_el.text) if priority_el is not None and priority_el.text else None,
                "type": type_el.text if type_el is not None else None,
            }
    except Exception as e:
        print(f"  Ошибка парсинга rian: namespace: {e}")
    return result


def extract_datalayer(html: str) -> dict:
    """
    В HTML страниц РИА есть window.dataLayer с полезными метаданными:
    - page_tags: реальные теги статьи (чего нет в RSS <category>!)
    - page_rubric: реальная рубрика («В мире», «Экономика» и т.д.)
    - article_length: длина текста в символах

    Это важная находка: RSS даёт только «Лента новостей»,
    а dataLayer даёт настоящую тематику.
    """
    tags_match = re.search(r"'page_tags'\s*:\s*'([^']*)'", html)
    rubric_match = re.search(r"'page_rubric'\s*:\s*'([^']*)'", html)
    length_match = re.search(r"'article_length'\s*:\s*'(\d+)'", html)

    tags_raw = tags_match.group(1) if tags_match else ""
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    return {
        "page_tags": tags,
        "page_rubric": rubric_match.group(1) if rubric_match else None,
        "article_length": int(length_match.group(1)) if length_match else None,
    }


# ─── Шаги сбора ──────────────────────────────────────────────────────────────

async def step1_fetch_rss() -> tuple[bytes | None, dict]:
    """
    Шаг 1: Скачать RSS.
    Ожидаем: ETag — неизвестно, проверим. Фид небольшой (только заголовки).
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

    response.raise_for_status()
    cache_info = {
        "etag": response.headers.get("etag"),
        "modified": response.headers.get("last-modified"),
    }
    return response.content, cache_info


def step2_parse_rss(raw_content: bytes) -> list[dict]:
    """
    Шаг 2: Парсинг RSS.

    Главная особенность: RSS = только заголовок + ссылка.
    Дополнительно извлекаем rian:priority и rian:type через ElementTree.
    """
    print("\n" + "="*60)
    print("ШАГ 2: Парсинг RSS + rian: namespace")
    print("="*60)

    feed = feedparser.parse(raw_content)
    print(f"Записей в фиде: {len(feed.entries)}")

    if not feed.entries:
        return []

    # Кастомные поля через ElementTree
    print("\nИзвлекаем rian:priority и rian:type...")
    rian_fields = extract_rian_fields(raw_content)
    print(f"rian-поля найдены: {len(rian_fields)} items")

    # Анализ первой записи
    first = feed.entries[0]
    first_can = canonical_url(first.get("link", ""))
    first_rian = rian_fields.get(first_can, {})

    print("\n--- Структура первой записи ---")
    print(f"title:         {first.get('title', '—')[:70]}")
    print(f"link:          {first.get('link', '—')[:70]}")
    print(f"guid:          {first.get('id', '—')[:70]}")
    print(f"published:     {first.get('published', '—')}")
    tags = [t.get("term", "") for t in first.get("tags", [])]
    print(f"category RSS:  {tags}  ← всегда 'Лента новостей', бесполезно")
    print(f"description:   '{first.get('summary', '')}'  ← пустой!")
    print(f"\nrian:priority: {first_rian.get('priority', '—')}")
    print(f"rian:type:     {first_rian.get('type', '—')}")

    # Дата
    raw_date = first.get("published", "")
    parsed_dt = parse_date(first)
    print(f"\nДата из RSS:    {raw_date}")
    print(f"После парсинга: {parsed_dt} (UTC)")

    # Собираем все
    articles = []
    for entry in feed.entries:
        raw_url = entry.get("link", "").strip()
        can_url = canonical_url(raw_url)
        rian = rian_fields.get(can_url, {})

        articles.append({
            "url": raw_url,
            "canonical_url": can_url,
            "title": entry.get("title", ""),
            "published_at": parse_date(entry),
            "rian_priority": rian.get("priority"),
            "rian_type": rian.get("type"),
        })

    print(f"\n→ Извлечено: {len(articles)} записей")

    # Распределение приоритетов
    priorities = {}
    for a in articles:
        p = a["rian_priority"]
        priorities[p] = priorities.get(p, 0) + 1
    print(f"\nРаспределение rian:priority:")
    for p, cnt in sorted(priorities.items(), key=lambda x: (x[0] is None, x[0])):
        label = ""
        if p == 1: label = "← breaking?"
        elif p == 2: label = "← важная?"
        elif p == 3: label = "← обычная"
        print(f"  priority {p}: {cnt} статей {label}")

    print("\nПервые 5 заголовков:")
    for a in articles[:5]:
        date_str = a["published_at"].strftime("%H:%M UTC") if a["published_at"] else "—"
        print(f"  [p={a['rian_priority']}] [{date_str}] {a['title'][:60]}")

    return articles


async def step3_get_full_text(article: dict) -> dict:
    """
    Шаг 3: Получить полный текст + метаданные со страницы.

    РИА — единственный путь к тексту. В RSS нет ничего.
    Бонус: извлекаем page_tags и page_rubric из window.dataLayer.
    """
    print("\n" + "="*60)
    print("ШАГ 3: Получение полного текста и метаданных")
    print("="*60)
    print(f"Статья: {article['title'][:60]}")
    print(f"URL:    {article['canonical_url']}")
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

    # Извлечь метаданные из dataLayer
    dl = extract_datalayer(response.text)
    print(f"\nИз window.dataLayer:")
    print(f"  page_rubric: {dl['page_rubric'] or '—'}  ← реальная рубрика (нет в RSS!)")
    print(f"  page_tags:   {dl['page_tags']}  ← реальные теги")
    print(f"  article_length: {dl['article_length']} символов")

    # Извлечь текст
    doc = trafilatura.bare_extraction(
        response.text,
        url=article["canonical_url"],
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        deduplicate=True,
    )

    if doc and doc.text and len(doc.text) > 100:
        print(f"\n✓ trafilatura (favor_precision): {len(doc.text):,} символов")
        content = doc.text
        extraction_method = "trafilatura_precision"
    else:
        print("  favor_precision мало → пробуем favor_recall...")
        doc2 = trafilatura.bare_extraction(
            response.text,
            url=article["canonical_url"],
            favor_recall=True,
        )
        if doc2 and doc2.text and len(doc2.text) > 100:
            print(f"✓ trafilatura (favor_recall): {len(doc2.text):,} символов")
            content = doc2.text
            extraction_method = "trafilatura_recall"
        else:
            print("✗ trafilatura не справилась — статья без контента")
            content = ""
            extraction_method = "none"

    if content:
        print(f"\nПревью текста:")
        print("-" * 40)
        print(content[:400])
        print("-" * 40)

    return {
        **article,
        "content": content,
        "extraction_method": extraction_method,
        "raw_html": response.text,
        "page_rubric": dl["page_rubric"],
        "page_tags": dl["page_tags"],
        "article_length_expected": dl["article_length"],
    }


def step4_show_what_goes_to_db(article: dict) -> None:
    print("\n" + "="*60)
    print("ШАГ 4: Что пошло бы в базу данных")
    print("="*60)

    th = title_hash(article["title"])
    content = article.get("content", "")

    # Определить information_type по rian:priority
    priority = article.get("rian_priority")
    if priority and priority <= 2:
        info_type = "breaking"
    else:
        info_type = "daily"

    print("\n--- Таблица news ---")
    print(f"url:              {article['url'][:70]}")
    print(f"canonical_url:    {article['canonical_url'][:70]}")
    print(f"title:            {article['title'][:70]}")
    print(f"content длина:    {len(content):,} символов")
    if content:
        print(f"snippet_lead:     {content[:150]}...")
    print(f"published_at:     {article.get('published_at')} (UTC)")
    print(f"channel_type:     RSS")
    print(f"information_type: {info_type}  (из rian:priority={priority})")
    print(f"content_type:     {article.get('rian_type', 'news')}")
    print(f"title_hash:       {th}")
    print(f"extra JSONB:")
    print(f"  rian_priority:    {priority}")
    print(f"  rian_type:        {article.get('rian_type')}")
    print(f"  page_rubric:      {article.get('page_rubric', '—')}")
    print(f"  page_tags:        {article.get('page_tags', [])}")
    print(f"  extraction_method:{article.get('extraction_method')}")

    # Сравнение с article_length из dataLayer
    expected = article.get("article_length_expected")
    if expected and content:
        ratio = len(content) / expected
        print(f"\nПроверка: trafilatura={len(content)} симв, dataLayer={expected} симв")
        print(f"  Отношение: {ratio:.2f}x {'✓' if 0.5 <= ratio <= 2.0 else '⚠️'}")

    print("\n--- Таблица news_raw ---")
    print(f"raw_content длина:{len(article.get('raw_html', '')):,} символов (HTML)")
    print(f"raw_format:       html")
    print(f"parser_version:   ria-v1")


async def main():
    print("ТЕСТ СБОРА: РИА НОВОСТИ")
    print("Самый бедный RSS — только заголовок+ссылка, зато dataLayer в HTML!")

    raw_content, cache_info = await step1_fetch_rss()
    if raw_content is None:
        return

    articles = step2_parse_rss(raw_content)
    if not articles:
        return

    demo = articles[0]
    print(f"\nДемонстрация: {demo['title'][:60]}")

    enriched = await step3_get_full_text(demo)
    step4_show_what_goes_to_db(enriched)

    print("\n" + "="*60)
    print("ИТОГ")
    print("="*60)
    print(f"RSS записей:         {len(articles)}")
    print(f"ETag: {cache_info.get('etag', '—')}")
    print(f"Метод извлечения:    {enriched['extraction_method']}")
    print(f"Длина текста:        {len(enriched.get('content', '')):,} символов")
    print(f"\nHTTP-запросов за цикл: 1 (RSS) + N (страницы статей)")
    print(f"crawl_delay между запросами: {CRAWL_DELAY} сек")
    print(f"Следующий опрос через: 20 минут")


if __name__ == "__main__":
    asyncio.run(main())
