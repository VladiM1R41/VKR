"""
Пошаговый тест сбора с iXBT.com.

Ключевые особенности:
- <description> — полный HTML-текст статьи (не нужно скрапить страницы!)
- <author> = "mpak@ixbt.com (MPAK)" — email+псевдоним → вытащить псевдоним
- <category/> — всегда пустой, нет тегов
- Нет <enclosure> — thumbnail из первого <img> в description
- URL: ixbt.com/news/YYYY/MM/DD/{slug}.html

Запуск: python sources/ixbt/test_ixbt.py

Зависимости: pip install httpx feedparser beautifulsoup4
"""

import asyncio
import calendar
import hashlib
import html
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import feedparser
import httpx
from bs4 import BeautifulSoup

# ─── Конфигурация ────────────────────────────────────────────────────────────

RSS_URL = "https://www.ixbt.com/export/news.rss"
USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 1.0

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    """Нормализовать URL: https, без www., без trailing slash, без query params."""
    try:
        p = urlparse(url.strip())
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        return urlunparse(("https", host, path, "", "", ""))
    except Exception:
        return url


def extract_author(raw: str) -> str | None:
    """
    Извлечь псевдоним из формата "mpak@ixbt.com (MPAK)".
    → "MPAK", "Jin" и т.д.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    m = re.search(r'\(([^)]+)\)', raw)
    if m:
        return m.group(1)
    # Fallback: взять часть до @
    return raw.split("@")[0] if "@" in raw else raw


def parse_ixbt_content(raw_html: str) -> tuple[str, str | None]:
    """
    Извлечь (text, thumbnail) из description iXBT.

    Что делаем:
    1. Находим первый <img> → thumbnail URL
    2. Удаляем все <figure> и обёртки <a> вокруг них (иллюстрации)
    3. Фильтруем строки-подписи "Фото ...", "Создано ..." — остатки после figure
    4. get_text() → plain text

    Важно: iXBT запрещает использование иллюстраций → thumbnail только для UI,
    не публикуем изображение как своё.
    """
    if not raw_html:
        return "", None

    soup = BeautifulSoup(raw_html, "html.parser")

    # Thumbnail — первый <img> (обычно обёрнут в <a><figure>)
    img = soup.find("img")
    thumbnail = img.get("src") if img else None

    # Удалить виджет "Смотрите также" — ссылки с utm_campaign=seealso
    # Структура: <a href="...?utm_campaign=seealso"><figure>...</figure></a>
    #            <a href="...?utm_campaign=seealso">Заголовок похожей статьи</a>
    for a in soup.find_all("a", href=True):
        if "seealso" in a.get("href", ""):
            a.decompose()

    # Удалить все оставшиеся <figure> (фото статьи — и обёртку <a> если есть)
    for fig in soup.find_all("figure"):
        parent = fig.parent
        if parent and parent.name == "a":
            parent.decompose()
        else:
            fig.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Убрать текстовые подписи к фото ("Фото ASRock через Guru3D", "Создано Grok" и т.п.)
    photo_prefixes = ("фото", "создано", "photo", "изображение:", "источник:")
    lines = [
        line for line in text.split("\n")
        if line.strip() and not line.strip().lower().startswith(photo_prefixes)
    ]
    return "\n".join(lines), thumbnail


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


# ─── Шаги сбора ──────────────────────────────────────────────────────────────

async def step1_fetch_rss() -> tuple[bytes | None, dict]:
    """Шаг 1: Скачать RSS. Проверяем ETag/Last-Modified."""
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
            print(f"  Статус: {r2.status_code}")

    response.raise_for_status()
    return response.content, {"etag": etag, "modified": last_mod}


def step2_parse_rss(raw_content: bytes) -> list[dict]:
    """
    Шаг 2: Парсинг RSS + извлечение полного текста из description.
    HTTP-запросы к статьям НЕ нужны!
    """
    print("\n" + "="*60)
    print("ШАГ 2: Парсинг RSS (полный текст в description!)")
    print("="*60)

    feed = feedparser.parse(raw_content)
    print(f"Записей в фиде: {len(feed.entries)}")

    if not feed.entries:
        return []

    # Детальный анализ первой записи
    first = feed.entries[0]
    raw_link = first.get("link", "")
    raw_desc = first.get("summary", "") or ""
    raw_author = first.get("author", "") or ""
    author = extract_author(raw_author)
    text, thumbnail = parse_ixbt_content(raw_desc)

    print(f"\n--- Структура первой записи ---")
    print(f"title:           {first.get('title', '—')[:70]}")
    print(f"link:            {raw_link}")
    print(f"guid = link?     {first.get('id', '').rstrip('/') == raw_link.rstrip('/')}")
    print(f"published:       {first.get('published', '—')}")
    print(f"\nauthor (сырой): '{raw_author}'")
    print(f"author (parsed): '{author}'")
    print(f"\ncategory:        '{first.get('tags', 'пустой (всегда пустой)')}' ← не используем")
    print(f"\ndescription HTML длина: {len(raw_desc):,} символов")
    print(f"text длина:             {len(text):,} символов")
    print(f"thumbnail:              {thumbnail}")
    print(f"\nПревью текста:")
    print("-" * 40)
    print(text)
    print("-" * 40)

    # Сборка всех статей
    articles = []
    has_content = 0
    has_thumbnail = 0

    for entry in feed.entries:
        raw_url = entry.get("link", "").strip()
        can_url = canonical_url(raw_url)
        raw_desc_e = entry.get("summary", "") or ""
        content, thumb = parse_ixbt_content(raw_desc_e)
        auth = extract_author(entry.get("author", "") or "")
        pub = parse_date(entry)

        if content:
            has_content += 1
        if thumb:
            has_thumbnail += 1

        # snippet_lead — первый непустой абзац
        snippet = next((line for line in content.split("\n") if len(line) > 30), content[:150])

        articles.append({
            "url": raw_url,
            "canonical_url": can_url,
            "title": (entry.get("title", "") or "").strip(),
            "author": auth,
            "snippet_lead": snippet,
            "content": content,
            "content_html": raw_desc_e,
            "published_at": pub,
            "thumbnail": thumb,
        })

    print(f"\nВсего статей:      {len(articles)}")
    print(f"С полным текстом:  {has_content}/{len(articles)}")
    print(f"С thumbnail:       {has_thumbnail}/{len(articles)}")

    # Длина текстов
    lengths = [len(a["content"]) for a in articles if a["content"]]
    if lengths:
        print(f"\nДлина текстов:")
        print(f"  мин:    {min(lengths):,} символов")
        print(f"  макс:   {max(lengths):,} символов")
        print(f"  средняя:{sum(lengths)//len(lengths):,} символов")

    print(f"\nПервые 5 заголовков:")
    for a in articles[:5]:
        t = a["published_at"].strftime("%H:%M UTC") if a["published_at"] else "—"
        auth_s = a["author"] or "—"
        chars = len(a["content"])
        print(f"  [{t}] [{auth_s}] {a['title'][:45]}  ({chars} симв.)", flush=True)
    sys.stdout.flush()

    return articles


def step3_show_what_goes_to_db(article: dict) -> None:
    out = []
    out.append("\n" + "="*60)
    out.append("ШАГ 3: Что пошло бы в базу данных")
    out.append("(HTTP-запрос к статье НЕ нужен — текст уже в RSS!)")
    out.append("="*60)

    content = article.get("content", "")
    out.append("\n--- Таблица news ---")
    out.append(f"url:              {article['url']}")
    out.append(f"canonical_url:    {article['canonical_url']}")
    out.append(f"title:            {article['title'][:70]}")
    out.append(f"author:           '{article.get('author')}'  ← псевдоним из email")
    out.append(f"content длина:    {len(content):,} символов")
    out.append(f"snippet_lead:     '{article['snippet_lead'][:100]}'")
    out.append(f"published_at:     {article.get('published_at')} (UTC)")
    out.append(f"information_type: daily")
    out.append(f"quality:          ok  (текст из RSS)")
    out.append(f"title_hash:       {title_hash(article['title'])}")
    out.append(f"extra JSONB:")
    out.append(f"  thumbnail: {article.get('thumbnail')}")
    out.append("\n--- Таблица news_raw ---")
    out.append(f"raw_content длина:{len(article.get('content_html', '')):,} символов (HTML из RSS)")
    out.append(f"raw_format:       rss_description")
    out.append(f"parser_version:   ixbt-v1")

    print("\n".join(out), flush=True)


async def main():
    print("ТЕСТ СБОРА: IXBT.COM")
    print("Особенности: полный текст в description, автор=псевдоним, thumbnail из img")

    raw_content, cache_info = await step1_fetch_rss()
    if not raw_content:
        return

    articles = step2_parse_rss(raw_content)
    if not articles:
        return

    demo = articles[0]
    step3_show_what_goes_to_db(demo)

    print("\n" + "="*60)
    print("ИТОГ")
    print("="*60)
    print(f"Записей в фиде:  {len(articles)}")
    print(f"ETag:            {cache_info.get('etag') or '—'}")
    print(f"Last-Modified:   {cache_info.get('modified') or '—'}")
    print(f"Автор:           {demo.get('author')}")
    print(f"Thumbnail:       {demo.get('thumbnail') or '—'}")
    print(f"\nHTTP-запросов к статьям: 0  ← всё из RSS!")


if __name__ == "__main__":
    asyncio.run(main())
