"""
Пошаговый тест сбора с Ведомостей.

Особенности:
- RSS минималистичный: только заголовок + ссылка, NO description!
- <author> всегда = "Ведомости" — бесполезно, не сохранять
- <category> иерархическая: "Политика / Власть" — самая детальная из всех источников
- <link> = <guid> = <pdalink> — все одинаковые, баг feedparser из РБК здесь не страшен
- Главный риск: paywall. При закрытой статье content будет пустым (нет fallback description!)
- AI-агенты явно разрешены в robots.txt (anthropic-ai, ClaudeBot и др.)

Запуск: python sources/vedomosti/test_vedomosti.py

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

FEEDS = [
    {
        "name": "news",
        "label": "Все новости",
        "url": "https://www.vedomosti.ru/rss/news",
        "default_info_type": "daily",
    },
    {
        "name": "articles",
        "label": "Все материалы",
        "url": "https://www.vedomosti.ru/rss/articles",
        "default_info_type": "analytical",
    },
]

USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 1.0
PAYWALL_THRESHOLD = 200

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        # robots.txt: *?* запрещено — убираем все query params
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


def get_thumbnail(entry) -> str | None:
    enclosures = entry.get("enclosures", [])
    for enc in enclosures:
        if enc.get("type", "").startswith("image/"):
            return enc.get("href") or enc.get("url")
    return None


def parse_category(category: str) -> tuple[str | None, str | None]:
    """
    "Политика / Власть"              → ("Политика", "Власть")
    "Политика / Международные новости" → ("Политика", "Международные новости")
    "Общество"                        → ("Общество", None)
    """
    if " / " in category:
        parts = category.split(" / ", 1)
        return parts[0].strip(), parts[1].strip()
    return category.strip() if category else None, None


def classify_content(text: str) -> tuple[str, str]:
    if len(text) > 500:
        return text, "ok"
    elif len(text) > 100:
        return text, "partial"
    else:
        return "", "paywall"


# ─── Шаги сбора ──────────────────────────────────────────────────────────────

async def step1_fetch_feeds() -> dict[str, tuple[bytes | None, dict]]:
    """
    Шаг 1: Скачать оба RSS-фида.
    Проверяем ETag/Last-Modified.
    """
    print("\n" + "="*60)
    print("ШАГ 1: Загрузка RSS-фидов")
    print("="*60)

    results = {}
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        for feed_cfg in FEEDS:
            print(f"\nФид: {feed_cfg['label']}")
            print(f"URL: {feed_cfg['url']}")

            response = await client.get(
                feed_cfg["url"],
                headers={"User-Agent": USER_AGENT},
            )

            etag = response.headers.get("etag")
            last_mod = response.headers.get("last-modified")
            print(f"HTTP статус: {response.status_code}")
            print(f"ETag: {etag or 'не поддерживается'}")
            print(f"Last-Modified: {last_mod or 'не поддерживается'}")
            print(f"Размер: {len(response.content):,} байт")

            response.raise_for_status()
            results[feed_cfg["name"]] = (
                response.content,
                {"etag": etag, "modified": last_mod},
            )
            await asyncio.sleep(0.5)

    return results


def step2_parse_feeds(raw_feeds: dict) -> tuple[list[dict], dict]:
    """
    Шаг 2: Парсить оба фида, собрать в общую очередь с дедупликацией.
    """
    print("\n" + "="*60)
    print("ШАГ 2: Парсинг фидов + дедупликация")
    print("="*60)

    all_articles = []
    seen_urls = set()
    stats = {}

    for feed_cfg in FEEDS:
        name = feed_cfg["name"]
        raw_content, _ = raw_feeds[name]

        feed = feedparser.parse(raw_content)
        total = len(feed.entries)
        print(f"\n{feed_cfg['label']}: {total} записей")

        if not feed.entries:
            stats[name] = {"total": 0, "unique": 0}
            continue

        # Структура первой записи
        first = feed.entries[0]
        cats = [t.get("term", "") for t in first.get("tags", [])]
        cat_parent, cat_sub = parse_category(cats[0] if cats else "")
        print(f"  Первая запись:")
        print(f"    title:    {first.get('title', '—')[:70]}")
        print(f"    link:     {first.get('link', '—')}")
        print(f"    guid:     {first.get('id', '—')}")
        print(f"    author:   '{first.get('author', '—')}'  ← всегда 'Ведомости'?")
        print(f"    category: {cats}  → parent='{cat_parent}', sub='{cat_sub}'")
        print(f"    description: '{first.get('summary', '')}'  ← пустой?")
        print(f"    thumbnail: {get_thumbnail(first) or '—'}")

        unique_count = 0
        with_thumb = 0

        for entry in feed.entries:
            raw_url = entry.get("link", "").strip()
            if not raw_url:
                continue
            can_url = canonical_url(raw_url)

            if can_url in seen_urls:
                continue
            seen_urls.add(can_url)
            unique_count += 1

            cats_entry = [t.get("term", "") for t in entry.get("tags", [])]
            cat_p, cat_s = parse_category(cats_entry[0] if cats_entry else "")

            thumb = get_thumbnail(entry)
            if thumb:
                with_thumb += 1

            author = entry.get("author", "").strip()

            all_articles.append({
                "url": raw_url,
                "canonical_url": can_url,
                "title": entry.get("title", ""),
                "published_at": parse_date(entry),
                "author_raw": author,       # "Ведомости" — не журналист
                "category_raw": cats_entry[0] if cats_entry else "",
                "category_parent": cat_p,
                "category_sub": cat_s,
                "thumbnail": thumb,
                "feed_source": name,
                "default_info_type": feed_cfg["default_info_type"],
            })

        stats[name] = {"total": total, "unique": unique_count, "with_thumb": with_thumb}
        print(f"  Уникальных: {unique_count}, с thumbnail: {with_thumb}")

    cross_dups = sum(s["total"] for s in stats.values()) - len(all_articles)
    print(f"\nВсего в очереди: {len(all_articles)}, пересечений: {cross_dups}")

    # Показать распределение категорий
    parents: dict[str, int] = {}
    for a in all_articles:
        p = a["category_parent"] or "?"
        parents[p] = parents.get(p, 0) + 1
    print(f"\nТоп категорий (parent):")
    for p, cnt in sorted(parents.items(), key=lambda x: -x[1])[:8]:
        print(f"  {p}: {cnt}")

    return all_articles, stats


async def step3_get_full_text(article: dict) -> dict:
    """
    Шаг 3: Получить полный текст.
    Главный вопрос: paywall или открытая статья?
    При paywall — content пустой, нет fallback description (RSS пустой)!
    """
    print("\n" + "="*60)
    print("ШАГ 3: Получение полного текста")
    print("="*60)
    print(f"Статья: {article['title'][:65]}")
    print(f"Фид:    {article['feed_source']} | Рубрика: {article['category_raw']}")
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

    doc = trafilatura.bare_extraction(
        response.text,
        url=article["canonical_url"],
        include_comments=False,
        favor_precision=True,
        deduplicate=True,
    )

    raw_text = (doc.text or "") if doc else ""

    if len(raw_text) < PAYWALL_THRESHOLD:
        # Пробуем favor_recall
        doc2 = trafilatura.bare_extraction(
            response.text,
            url=article["canonical_url"],
            favor_recall=True,
        )
        raw_text2 = (doc2.text or "") if doc2 else ""
        if len(raw_text2) > len(raw_text):
            raw_text = raw_text2

    content, quality = classify_content(raw_text)

    if quality == "paywall":
        print(f"\n🔒 PAYWALL: текст недоступен")
        print(f"   trafilatura: {len(raw_text)} символов < {PAYWALL_THRESHOLD}")
        print(f"   ⚠️ Нет fallback description (RSS пустой)! content = ''")
    elif quality == "partial":
        print(f"\n⚠️  PARTIAL: {len(content):,} символов (частичный доступ)")
    else:
        print(f"\n✓ Полный текст: {len(content):,} символов")
        print(f"\nПревью:")
        print("-" * 40)
        print(content[:400])
        print("-" * 40)

    return {
        **article,
        "content": content,
        "quality": quality,
        "raw_html": response.text,
    }


def step4_show_what_goes_to_db(article: dict) -> None:
    print("\n" + "="*60)
    print("ШАГ 4: Что пошло бы в базу данных")
    print("="*60)

    content = article.get("content", "")
    th = title_hash(article["title"])

    print("\n--- Таблица news ---")
    print(f"url:              {article['url']}")
    print(f"canonical_url:    {article['canonical_url']}")
    print(f"title:            {article['title'][:70]}")
    print(f"author:           null  (author_raw='{article['author_raw']}' — игнорируем)")
    print(f"content длина:    {len(content):,} символов")
    print(f"snippet_lead:     ''  (RSS не содержит description!)")
    print(f"published_at:     {article.get('published_at')} (UTC)")
    print(f"information_type: {article['default_info_type']}")
    print(f"quality:          {article.get('quality', 'ok')}")
    print(f"title_hash:       {th}")
    print(f"extra JSONB:")
    print(f"  category_parent: {article.get('category_parent')}")
    print(f"  category_sub:    {article.get('category_sub')}")
    print(f"  thumbnail:       {article.get('thumbnail') or null_str()}")
    print(f"  feed_source:     {article['feed_source']}")

    print("\n--- Таблица news_raw ---")
    print(f"raw_content длина:{len(article.get('raw_html', '')):,} символов (HTML)")
    print(f"raw_format:       html")
    print(f"parser_version:   vedomosti-v1")


def null_str():
    return "null"


async def main():
    print("ТЕСТ СБОРА: ВЕДОМОСТИ")
    print("RSS минималистичный: только заголовок + ссылка, без description")
    print("Главный вопрос: какой % статей за paywall?")

    raw_feeds = await step1_fetch_feeds()

    articles, stats = step2_parse_feeds(raw_feeds)
    if not articles:
        print("Статей не найдено!")
        return

    # Тестируем по одной статье из каждого фида
    print(f"\n{'='*60}")
    print("Тестируем по одной статье из каждого фида:")

    tested = []
    paywall_count = 0
    ok_count = 0

    for feed_name in ["news", "articles"]:
        candidate = next((a for a in articles if a["feed_source"] == feed_name), None)
        if candidate:
            result = await step3_get_full_text(candidate)
            tested.append(result)
            if result["quality"] == "paywall":
                paywall_count += 1
            else:
                ok_count += 1

    if tested:
        step4_show_what_goes_to_db(tested[0])

    print("\n" + "="*60)
    print("ИТОГ")
    print("="*60)
    for feed_cfg in FEEDS:
        s = stats.get(feed_cfg["name"], {})
        print(f"  {feed_cfg['name']:8}: {s.get('total', 0)} items, "
              f"{s.get('with_thumb', 0)} с thumbnail")
    print(f"\nТест полного текста ({len(tested)} статей):")
    for a in tested:
        icon = "✓" if a["quality"] == "ok" else ("⚠️" if a["quality"] == "partial" else "🔒")
        print(f"  {icon} {a['quality']:8} | {len(a.get('content', '')):,} симв | "
              f"[{a['feed_source']}] {a['title'][:45]}")
    print(f"\nPaywall в тесте: {paywall_count}/{len(tested)}")
    print(f"Нужно наблюдать на большей выборке для оценки % paywall")


if __name__ == "__main__":
    asyncio.run(main())
