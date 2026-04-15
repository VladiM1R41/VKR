"""
Пошаговый тест сбора с ТАСС через Яндекс-фид.

Ключевое открытие: https://tass.ru/rss/yandex.xml содержит
<yandex:full-text> — полный HTML статьи прямо в RSS.
Не нужно ходить на страницы за текстом!

Запуск: python sources/tass/test_tass.py

Зависимости: pip install httpx feedparser trafilatura beautifulsoup4 lxml
"""

import asyncio
import calendar
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse
import xml.etree.ElementTree as ET

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

# ─── Конфигурация ────────────────────────────────────────────────────────────

RSS_URL = "https://tass.ru/rss/yandex.xml"
RSS_URL_FALLBACK = "https://tass.ru/rss/v2.xml"
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"

# Яндекс-фид даёт полный текст в RSS — НЕ нужно ходить на страницы статей.
# crawl_delay нужен только если понадобится скрапинг (fallback).
CRAWL_DELAY = 1.0

# Namespace для парсинга yandex:full-text вручную
YANDEX_NS = "http://news.yandex.ru"

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


def extract_yandex_fulltext_from_raw(raw_xml_bytes: bytes, item_link: str) -> str | None:
    """
    feedparser не знает про yandex: namespace и может не достать full-text.
    Парсим raw XML вручную через ElementTree.

    Яндекс-фид использует namespace: xmlns:yandex="http://news.yandex.ru"
    Тег: <yandex:full-text><![CDATA[<p>...</p>]]></yandex:full-text>
    """
    try:
        root = ET.fromstring(raw_xml_bytes)
        channel = root.find("channel")
        if channel is None:
            return None

        for item in channel.findall("item"):
            # Найти item с нашей ссылкой
            link_el = item.find("link")
            # В Яндекс-фиде <link> содержит CDATA, ET вернёт текст
            item_url = (link_el.text or "").strip() if link_el is not None else ""
            if canonical_url(item_url) != canonical_url(item_link):
                continue

            # Найти yandex:full-text с namespace
            ft_el = item.find(f"{{{YANDEX_NS}}}full-text")
            if ft_el is not None and ft_el.text:
                # ft_el.text — это HTML строка типа "<p>Текст</p><p>Продолжение</p>"
                html_fragment = ft_el.text.strip()
                # Извлечь чистый текст через BeautifulSoup
                soup = BeautifulSoup(html_fragment, "html.parser")
                clean = soup.get_text(separator="\n", strip=True)
                return clean if clean else None

        return None
    except Exception as e:
        print(f"  Ошибка парсинга yandex:full-text: {e}")
        return None


def extract_all_yandex_fulltexts(raw_xml_bytes: bytes) -> dict[str, str]:
    """
    Извлечь yandex:full-text для всех items сразу.
    Возвращает dict: canonical_url → clean_text
    """
    result = {}
    try:
        root = ET.fromstring(raw_xml_bytes)
        channel = root.find("channel")
        if channel is None:
            return result

        for item in channel.findall("item"):
            link_el = item.find("link")
            item_url = (link_el.text or "").strip() if link_el is not None else ""
            can = canonical_url(item_url)

            ft_el = item.find(f"{{{YANDEX_NS}}}full-text")
            if ft_el is not None and ft_el.text:
                html_fragment = ft_el.text.strip()
                soup = BeautifulSoup(html_fragment, "html.parser")
                clean = soup.get_text(separator="\n", strip=True)
                if clean:
                    result[can] = clean

    except Exception as e:
        print(f"  Ошибка при массовом парсинге full-text: {e}")

    return result


def get_thumbnail(entry) -> str | None:
    enclosures = entry.get("enclosures", [])
    for enc in enclosures:
        if enc.get("type", "").startswith("image/"):
            return enc.get("href") or enc.get("url")
    return None


# ─── Шаги сбора ──────────────────────────────────────────────────────────────

async def step1_fetch_rss() -> tuple[bytes | None, dict]:
    """
    Шаг 1: Скачать Яндекс-фид ТАСС.
    Сравниваем с v2.xml — разница в размере и структуре.
    """
    print("\n" + "="*60)
    print("ШАГ 1: Загрузка RSS-фида (Яндекс-формат)")
    print("="*60)
    print(f"Основной URL: {RSS_URL}")

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


def step2_parse_rss(raw_content: bytes) -> tuple[list[dict], dict[str, str]]:
    """
    Шаг 2: Распарсить RSS + извлечь все yandex:full-text.

    feedparser обрабатывает стандартные поля.
    yandex:full-text достаём вручную через ElementTree.
    """
    print("\n" + "="*60)
    print("ШАГ 2: Парсинг RSS + извлечение yandex:full-text")
    print("="*60)

    # feedparser для стандартных полей
    feed = feedparser.parse(raw_content)
    print(f"Записей в фиде: {len(feed.entries)}")

    if not feed.entries:
        print("→ Фид пустой")
        return [], {}

    # ElementTree для yandex:full-text
    print("\nИзвлекаем yandex:full-text через ElementTree...")
    fulltexts = extract_all_yandex_fulltexts(raw_content)
    print(f"full-text найдено: {len(fulltexts)} из {len(feed.entries)} items")

    # Анализ первой записи
    first = feed.entries[0]
    first_can = canonical_url(first.get("link", ""))
    first_fulltext = fulltexts.get(first_can, "")

    print("\n--- Структура первой записи ---")
    print(f"title:       {first.get('title', '—')}")
    print(f"link:        {first.get('link', '—')}")
    print(f"guid:        {first.get('id', '—')}")
    print(f"published:   {first.get('published', '—')}")
    tags = [t.get("term", "") for t in first.get("tags", [])]
    print(f"categories:  {tags}")
    print(f"thumbnail:   {get_thumbnail(first) or '—'}")

    summary = first.get("summary", "").strip()
    print(f"\ndescription: '{summary}' (длина: {len(summary)})")
    print(f"full-text:   {len(first_fulltext):,} символов" if first_fulltext else "full-text:   НЕ НАЙДЕН")

    if first_fulltext:
        print(f"\nПревью full-text (первые 300 символов):")
        print("-" * 40)
        print(first_fulltext)
        print("-" * 40)

    # Дата
    raw_date = first.get("published", "")
    parsed_dt = parse_date(first)
    print(f"\nДата из RSS:    {raw_date}")
    print(f"После парсинга: {parsed_dt} (UTC)")

    # Собираем все записи
    articles = []
    for entry in feed.entries:
        raw_url = entry.get("link", "").strip()
        can_url = canonical_url(raw_url)
        full_text = fulltexts.get(can_url, "")
        summary = entry.get("summary", "").strip()

        articles.append({
            "url": raw_url,
            "canonical_url": can_url,
            "title": entry.get("title", ""),
            "summary": summary,
            "full_text": full_text,          # из yandex:full-text
            "has_fulltext": bool(full_text),
            "has_summary": bool(summary),
            "published_at": parse_date(entry),
            "categories": [t.get("term", "") for t in entry.get("tags", [])],
            "thumbnail": get_thumbnail(entry),
        })

    print(f"\n→ Итого записей: {len(articles)}")
    with_ft = sum(1 for a in articles if a["has_fulltext"])
    with_s = sum(1 for a in articles if a["has_summary"])
    print(f"  full-text есть: {with_ft} ({with_ft*100//len(articles)}%)")
    print(f"  description есть: {with_s} ({with_s*100//len(articles)}%)")

    print("\nПервые 5 заголовков:")
    for a in articles[:5]:
        date_str = a["published_at"].strftime("%H:%M UTC") if a["published_at"] else "—"
        ft_mark = "📄" if a["has_fulltext"] else "✗"
        print(f"  {ft_mark} [{date_str}] {a['title']}")

    return articles, fulltexts


def step3_show_content(article: dict) -> dict:
    """
    Шаг 3: Показать извлечённый контент.

    В отличие от Хабра и Ленты — НЕ делаем HTTP-запрос на страницу.
    Весь текст уже в RSS через yandex:full-text.
    """
    print("\n" + "="*60)
    print("ШАГ 3: Контент (из RSS, без HTTP-запроса на страницу)")
    print("="*60)
    print(f"Статья: {article['title']}")

    if article["has_fulltext"]:
        content = article["full_text"]
        extraction_method = "yandex_full_text"
        print(f"\n✓ yandex:full-text: {len(content):,} символов")
        print(f"  (HTTP-запрос на страницу НЕ нужен!)")
        print(f"\nПолный текст:")
        print("-" * 40)
        print(content)
        print("-" * 40)
    elif article["has_summary"]:
        content = article["summary"]
        extraction_method = "rss_summary_fallback"
        print(f"\n⚠️  yandex:full-text отсутствует → используем description")
        print(f"   Контент: {len(content)} символов")
    else:
        content = ""
        extraction_method = "none"
        print(f"\n✗ Ни full-text, ни description — пустая статья")

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
    print(f"title:            {article['title']}")
    print(f"content длина:    {len(content):,} символов")
    if content:
        print(f"snippet_lead:     {content}...")
    print(f"published_at:     {article.get('published_at')} (UTC)")
    print(f"channel_type:     RSS")
    print(f"information_type: daily")
    print(f"content_type:     news")
    print(f"title_hash:       {th}")
    print(f"extra JSONB:")
    print(f"  categories:         {article.get('categories', [])}")
    print(f"  thumbnail:          {article.get('thumbnail', '—')}")
    print(f"  extraction_method:  {article.get('extraction_method')}")
    print(f"  has_rss_description:{article.get('has_summary', False)}")

    print("\n--- Таблица news_raw ---")
    # При использовании yandex-фида HTML страницы не скачиваем.
    # В raw сохраняем исходный HTML из yandex:full-text (для переобработки).
    raw_content = article.get("full_text", article.get("summary", ""))
    print(f"raw_content длина:{len(raw_content):,} символов (HTML из yandex:full-text)")
    print(f"raw_format:       html_fragment")
    print(f"parser_version:   tass-yandex-v1")
    print(f"\n→ Страница статьи НЕ скачивалась (экономия HTTP-запроса!)")


async def main():
    print("ТЕСТ СБОРА: ТАСС (Яндекс-фид)")
    print("Используем rss/yandex.xml — полный текст прямо в RSS!")
    print(f"\nГлавное отличие от Хабра и Ленты:")
    print(f"  - yandex:full-text → полный текст БЕЗ HTTP-запроса на страницу")
    print(f"  - description всегда есть")
    print(f"  - нет <author> (агентство, не конкретный журналист)")

    raw_content, cache_info = await step1_fetch_rss()
    if raw_content is None:
        return

    articles, _ = step2_parse_rss(raw_content)
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
    print(f"(Хабр и Лента делали 1 + N запросов на страницы)")


if __name__ == "__main__":
    asyncio.run(main())
