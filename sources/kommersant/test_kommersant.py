"""
Пошаговый тест сбора с Коммерсанта.

Особенности:
- Три RSS-фида: news.xml (лента), corp.xml (сайт), main.xml (газета Главное)
- description-лид есть во всех фидах — есть что показать даже без полного текста
- Часть статей за paywall — trafilatura вернёт < 200 символов
- Все три фида дедуплицируются вместе по canonical_url

Запуск: python sources/kommersant/test_kommersant.py

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
        "label": "Лента новостей",
        "url": "https://www.kommersant.ru/rss/news.xml",
        "default_info_type": "daily",
    },
    {
        "name": "corp",
        "label": "Материалы сайта",
        "url": "https://www.kommersant.ru/rss/corp.xml",
        "default_info_type": "daily",
    },
    {
        "name": "main",
        "label": "Газета. Главное",
        "url": "https://www.kommersant.ru/rss/main.xml",
        "default_info_type": "analytical",
    },
]

USER_AGENT = "JarvisNewsBot/1.0 (academic-research)"
CRAWL_DELAY = 1.0
PAYWALL_THRESHOLD = 200  # символов — если меньше, вероятно paywall

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    try:
        p = urlparse(url.strip())
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        # robots.txt: /doc*= запрещено — убираем query params
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


def split_title(title: str) -> tuple[str, str | None]:
    """
    Коммерсантъ использует двойные заголовки через '//':
    'Москва осталась без главного по фасадам // Архитектор отправился в отставку'
    Возвращает (основной_заголовок, подзаголовок или None).
    """
    if " // " in title:
        parts = title.split(" // ", 1)
        return parts[0].strip(), parts[1].strip()
    return title, None


def classify_content(text: str, description: str) -> tuple[str, str]:
    """
    Определить качество извлечённого текста.
    Если текст слишком короткий — вероятно paywall.
    """
    if len(text) > 500:
        return text, "ok"
    elif len(text) > 50:
        return text, "partial"
    else:
        # Возвращаем description как минимальный контент
        return description, "paywall"


# ─── Шаги сбора ──────────────────────────────────────────────────────────────

async def step1_fetch_all_feeds() -> dict[str, tuple[bytes | None, dict]]:
    """
    Шаг 1: Скачать все три RSS-фида.
    Делаем запросы последовательно (вежливо, с задержкой).
    """
    print("\n" + "="*60)
    print("ШАГ 1: Загрузка трёх RSS-фидов")
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

            print(f"HTTP статус: {response.status_code}")
            print(f"ETag: {response.headers.get('etag', 'не поддерживается')}")
            print(f"Last-Modified: {response.headers.get('last-modified', 'не поддерживается')}")
            print(f"Размер: {len(response.content):,} байт")

            response.raise_for_status()

            cache_info = {
                "etag": response.headers.get("etag"),
                "modified": response.headers.get("last-modified"),
            }
            results[feed_cfg["name"]] = (response.content, cache_info)

            # Небольшая пауза между запросами к одному серверу
            await asyncio.sleep(0.5)

    return results


def step2_parse_all_feeds(
    raw_feeds: dict[str, tuple[bytes, dict]]
) -> tuple[list[dict], dict]:
    """
    Шаг 2: Парсить все три фида, собрать в одну очередь с дедупликацией.
    """
    print("\n" + "="*60)
    print("ШАГ 2: Парсинг фидов + дедупликация")
    print("="*60)

    all_articles = []
    seen_urls = set()  # для дедупликации между фидами
    stats = {}

    for feed_cfg in FEEDS:
        name = feed_cfg["name"]
        raw_content, _ = raw_feeds[name]

        feed = feedparser.parse(raw_content)
        total = len(feed.entries)
        print(f"\n{feed_cfg['label']}: {total} записей в фиде")

        if not feed.entries:
            stats[name] = {"total": 0, "unique": 0, "with_thumbnail": 0}
            continue

        # Показать структуру первой записи
        first = feed.entries[0]
        print(f"  Первая запись:")
        print(f"    title:    {first.get('title', '—')[:70]}")
        print(f"    link:     {first.get('link', '—')}")
        print(f"    guid:     {first.get('id', '—')}")
        print(f"    category: {[t.get('term', '') for t in first.get('tags', [])]}")
        print(f"    description ({len(first.get('summary', ''))} симв): "
              f"'{first.get('summary', '')[:80]}...'")
        print(f"    thumbnail: {get_thumbnail(first) or '—'}")
        print(f"    pubDate:   {first.get('published', '—')}")

        unique_count = 0
        with_thumbnail = 0

        for entry in feed.entries:
            raw_url = entry.get("link", "").strip()
            if not raw_url:
                continue
            can_url = canonical_url(raw_url)

            # Дедупликация между тремя фидами
            if can_url in seen_urls:
                continue
            seen_urls.add(can_url)
            unique_count += 1

            thumb = get_thumbnail(entry)
            if thumb:
                with_thumbnail += 1

            main_title, subtitle = split_title(entry.get("title", ""))
            description = entry.get("summary", "").strip()

            all_articles.append({
                "url": raw_url,
                "canonical_url": can_url,
                "title": main_title,
                "subtitle": subtitle,
                "description": description,        # лид из RSS — всегда есть
                "published_at": parse_date(entry),
                "category": [t.get("term", "") for t in entry.get("tags", [])],
                "thumbnail": thumb,
                "feed_source": name,
                "default_info_type": feed_cfg["default_info_type"],
            })

        stats[name] = {
            "total": total,
            "unique": unique_count,
            "with_thumbnail": with_thumbnail,
        }
        print(f"  Уникальных (после дедупликации): {unique_count}")
        print(f"  С thumbnail: {with_thumbnail}")

    print(f"\n--- Итого ---")
    print(f"Статей в очереди: {len(all_articles)}")
    cross_dups = sum(s["total"] for s in stats.values()) - len(all_articles)
    print(f"Пересечений между фидами: {cross_dups}")

    print("\nСводка по фидам:")
    for feed_cfg in FEEDS:
        s = stats[feed_cfg["name"]]
        print(f"  {feed_cfg['label']}: {s['total']} → {s['unique']} уникальных")

    return all_articles, stats


async def step3_get_full_text(article: dict) -> dict:
    """
    Шаг 3: Получить полный текст со страницы статьи.

    Ключевой вопрос: paywall или открытая статья?
    Если text < PAYWALL_THRESHOLD → paywall, используем description как snippet_lead.
    """
    print("\n" + "="*60)
    print("ШАГ 3: Получение полного текста")
    print("="*60)
    print(f"Статья:    {article['title']}")
    print(f"Фид:       {article['feed_source']}")
    print(f"URL:       {article['canonical_url']}")
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

    # Извлечь текст
    doc = trafilatura.bare_extraction(
        response.text,
        url=article["canonical_url"],
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        deduplicate=True,
    )

    raw_text = (doc.text or "") if doc else ""

    if len(raw_text) < PAYWALL_THRESHOLD:
        print(f"\n⚠️  trafilatura: {len(raw_text):,} символов < {PAYWALL_THRESHOLD} — возможно paywall")
        print(f"   Пробуем favor_recall...")
        doc2 = trafilatura.bare_extraction(
            response.text,
            url=article["canonical_url"],
            favor_recall=True,
        )
        raw_text2 = (doc2.text or "") if doc2 else ""
        if len(raw_text2) > len(raw_text):
            raw_text = raw_text2
            print(f"   favor_recall: {len(raw_text):,} символов")

    content, quality = classify_content(raw_text, article["description"])

    if quality == "paywall":
        print(f"\n🔒 PAYWALL: полный текст недоступен")
        print(f"   Используем description ({len(article['description'])} симв) как snippet_lead")
    elif quality == "partial":
        print(f"\n⚠️  PARTIAL: получено {len(raw_text):,} символов (частичный доступ)")
    else:
        print(f"\n✓ Полный текст: {len(content):,} символов")
        print(f"\nПревью текста:")
        print("-" * 40)
        print(content)
        print("-" * 40)

    return {
        **article,
        "content": content,
        "quality": quality,
        "extraction_method": "trafilatura_precision" if quality != "paywall" else "rss_description_fallback",
        "raw_html": response.text,
    }


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
    if article.get("subtitle"):
        print(f"subtitle:         {article['subtitle']}")
    print(f"content длина:    {len(content):,} символов")
    print(f"snippet_lead:     {article['description'][:120]}...")
    print(f"published_at:     {article.get('published_at')} (UTC)")
    print(f"channel_type:     RSS")
    print(f"information_type: {article['default_info_type']}")
    print(f"content_type:     {'news' if article['feed_source'] == 'news' else 'article'}")
    print(f"title_hash:       {th}")
    print(f"quality:          {article.get('quality', 'ok')}")
    print(f"extra JSONB:")
    print(f"  category:         {article.get('category', [])}")
    print(f"  thumbnail:        {article.get('thumbnail') or '—'}")
    print(f"  feed_source:      {article['feed_source']}")
    print(f"  extraction_method:{article.get('extraction_method')}")

    print("\n--- Таблица news_raw ---")
    print(f"raw_content длина:{len(article.get('raw_html', '')):,} символов (HTML)")
    print(f"raw_format:       html")
    print(f"parser_version:   kommersant-v1")


async def step0_test_etag() -> None:
    """
    Шаг 0 (опциональный): проверить работу условных HTTP-запросов.

    ETag/Last-Modified позволяют не скачивать фид повторно если он не изменился.
    Алгоритм:
      1. Первый запрос → получаем ETag и Last-Modified
      2. Второй запрос с If-None-Match + If-Modified-Since → ожидаем 304 Not Modified
      3. При 304 тело ответа пустое → не тратим трафик (570 KB → 0)
    """
    print("\n" + "="*60)
    print("ШАГ 0: Тест ETag / If-None-Match")
    print("="*60)

    url = "https://www.kommersant.ru/rss/news.xml"

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        # Первый запрос — получаем кэш-заголовки
        print(f"Запрос 1 (без кэш-заголовков)...")
        r1 = await client.get(url, headers={"User-Agent": USER_AGENT})
        etag = r1.headers.get("etag")
        last_modified = r1.headers.get("last-modified")
        print(f"  Статус:        {r1.status_code}")
        print(f"  ETag:          {etag}")
        print(f"  Last-Modified: {last_modified}")
        print(f"  Размер:        {len(r1.content):,} байт")

        if not etag and not last_modified:
            print("\n✗ Сервер не вернул ETag/Last-Modified — условные запросы не работают")
            return

        # Второй запрос — с кэш-заголовками
        print(f"\nЗапрос 2 (с If-None-Match / If-Modified-Since)...")
        cond_headers = {"User-Agent": USER_AGENT}
        if etag:
            cond_headers["If-None-Match"] = etag
        if last_modified:
            cond_headers["If-Modified-Since"] = last_modified

        r2 = await client.get(url, headers=cond_headers)
        print(f"  Статус:  {r2.status_code}")
        print(f"  Размер:  {len(r2.content):,} байт")

        if r2.status_code == 304:
            print(f"\n✓ 304 Not Modified — сервер подтвердил: фид не изменился")
            print(f"  Скачано: 0 байт (вместо {len(r1.content):,} байт)")
            print(f"  Экономия: 100% трафика при неизменном фиде")
        else:
            print(f"\n⚠️  Ожидали 304, получили {r2.status_code}")
            print(f"   Возможно, фид успел обновиться между двумя запросами")


async def main():
    print("ТЕСТ СБОРА: КОММЕРСАНТЪ")
    print("Три RSS-фида: news.xml + corp.xml + main.xml")
    print("Ключевой вопрос: paywall или открытая статья?")

    # Шаг 0: проверить ETag
    await step0_test_etag()

    # Шаг 1: скачать все три фида
    raw_feeds = await step1_fetch_all_feeds()

    # Шаг 2: парсить и дедуплицировать
    articles, stats = step2_parse_all_feeds(raw_feeds)
    if not articles:
        print("Статей не найдено!")
        return

    # Шаг 3: получить полный текст для одной статьи из каждого фида
    print(f"\n{'='*60}")
    print("Тестируем по одной статье из каждого фида:")

    tested = {}
    for feed_name in ["news", "corp", "main"]:
        candidate = next(
            (a for a in articles if a["feed_source"] == feed_name),
            None
        )
        if candidate:
            tested[feed_name] = await step3_get_full_text(candidate)

    # Шаг 4: показать DB для первой протестированной
    if tested:
        demo = tested.get("news") or tested.get("corp") or tested.get("main")
        step4_show_what_goes_to_db(demo)

    # Итоговая таблица
    print("\n" + "="*60)
    print("ИТОГ")
    print("="*60)
    for feed_name, article in tested.items():
        quality = article.get("quality", "?")
        quality_icon = "✓" if quality == "ok" else ("⚠️" if quality == "partial" else "🔒")
        print(f"  {feed_name:5}: {quality_icon} {quality:8} | {len(article.get('content', '')):,} симв | {article['title'][:50]}")

    print(f"\nВсего статей в очереди: {len(articles)}")
    print(f"HTTP-запросов за цикл: 3 (RSS) + N (страницы статей)")
    print(f"crawl_delay: {CRAWL_DELAY} сек")


if __name__ == "__main__":
    asyncio.run(main())
