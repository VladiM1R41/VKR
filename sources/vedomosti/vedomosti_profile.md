# Профиль источника: Ведомости

> Составлено на основе исследования: robots.txt, два живых RSS-фида, правила использования.
> Дата последней проверки: `2026-04-04`
> Исследовательский скрипт: [test_vedomosti.py](/c:/code/diplom/sources/vedomosti/test_vedomosti.py)

---

## 1. Зачем этот источник

Ведомости — ведущая российская деловая газета (основана 1999, совладельцы — FT и WSJ до 2022).
Покрывает: бизнес, финансы, экономику, политику. Высокий редакционный стандарт, глубокая аналитика.

Что даёт «Джарвису»:
- Деловая аналитика высшего уровня (Tier 2 вместе с Коммерсантом и РБК)
- **Иерархические категории** в RSS: "Политика / Власть", "Бизнес / ТЭК" — самая детальная классификация из всех источников
- Очень развитая система тематических RSS (60+ фидов по рубрикам) — можно подключить нужные вертикали
- Thumbnail у почти всех items (news: 92%, articles: 100%)
- ETag + Last-Modified — экономия трафика

---

## 2. ⚠️ Юридический статус

### Известно из robots.txt

**Ведомости явно разрешают AI-агентам полный доступ (`Allow: /`):**
```
User-agent: anthropic-ai    → Allow: /
User-agent: ClaudeBot       → Allow: /
User-agent: claude-web      → Allow: /
User-agent: GPTBot          → Allow: /
User-agent: OAI-SearchBot   → Allow: /
User-agent: PerplexityBot   → Allow: /
User-agent: Google-Extended → Allow: /
# + ещё ~10 AI-агентов
```
Это не просто отсутствие запрета — явное `Allow: /` для каждого AI-агента.
**Такого нет ни у одного другого источника в нашем списке.**
Ведомости сознательно открыли сайт для AI-систем как для полноправных читателей.

### Для ВКР

Та же логика что у ТАСС и РБК: научно-учебное использование по п.1 ст.1274 ГК РФ.
Плюс явное разрешение для AI-агентов в robots.txt — сильный аргумент в пользу допустимости.

✅ Допустимо:
- Читать RSS → извлекать текст → использовать как RAG-контекст (ВКР, не коммерция)
- Генерировать дайджест + ссылка на оригинал Ведомостей
- AI-доступ явно разрешён в robots.txt

❌ Недопустимо:
- Коммерческое использование
- Воспроизведение полных статей без ссылки
- Обход paywall через авторизацию

**`legal_status = "restricted"`** — paywall ограничивает контент, но AI-доступ явно разрешён.
Наиболее благоприятный юридический статус из всех ограниченных источников.

---

## 3. Тип источника и доступ

| Параметр | Значение |
|----------|----------|
| Тип | RSS (60+ фидов) |
| Протокол | HTTPS, pull-режим |
| Аутентификация | Не нужна для RSS |
| Полный текст в RSS | **НЕТ** для news / **ЕСТЬ description** для articles |
| Нужен Playwright | **Нет** — статический HTML, trafilatura работает |
| **Paywall** | **⚠️ Возможен** — в тесте 0/2, нужно наблюдать на большей выборке |

### RSS URL (основные фиды для MVP)

```
# Обязательные (для MVP)
https://www.vedomosti.ru/rss/news           # Все новости, 200 items, 140 KB
https://www.vedomosti.ru/rss/articles       # Все материалы, 200 items, 265 KB

# Тематические (опционально, пересекаются с основными)
https://www.vedomosti.ru/rss/rubric/economics   # Экономика
https://www.vedomosti.ru/rss/rubric/politics    # Политика
https://www.vedomosti.ru/rss/rubric/business    # Бизнес
https://www.vedomosti.ru/rss/rubric/technology  # Технологии
https://www.vedomosti.ru/rss/rubric/finance     # Финансы
https://www.vedomosti.ru/rss/rubric/opinion     # Мнения
```

**Стратегия для MVP:** только `news` + `articles`. Тематические фиды полностью покрываются ими.
Тематические подключать только если нужна конкретная вертикаль в реальном времени.

---

## 4. Что реально отдаёт RSS (исследование живого фида)

**Проверено:** апрель 2026, оба фида.

### news — структура item:

```xml
<item>
  <title>При атаке на Энергодар повреждена вышка связи</title>

  <!-- link = guid = pdalink — все одинаковые -->
  <link>https://www.vedomosti.ru/society/news/2026/04/04/1187910-energodar-vishka</link>
  <guid>https://www.vedomosti.ru/society/news/2026/04/04/1187910-energodar-vishka</guid>
  <pdalink>https://www.vedomosti.ru/society/news/2026/04/04/1187910-energodar-vishka</pdalink>

  <author>Ведомости</author>          <!-- всегда "Ведомости", не журналист -->
  <category>Общество</category>       <!-- может быть иерархической: "Политика / Власть" -->
  <pubDate>Sat, 04 Apr 2026 01:00:44 +0300</pubDate>
  <!-- НЕТ enclosure у части items -->
  <!-- НЕТ description совсем -->
</item>
```

### articles — структура item (отличается!):

```xml
<item>
  <title>Чем известен ушедший в отставку главный архитектор Москвы Кузнецов</title>
  <link>https://www.vedomosti.ru/spravka/sergei-kuznetsov</link>
  <guid>https://www.vedomosti.ru/spravka/sergei-kuznetsov</guid>
  <pdalink>https://www.vedomosti.ru/spravka/sergei-kuznetsov</pdalink>

  <!-- author пустой в articles, "Ведомости" только в news -->
  <author/>

  <category>Общество</category>
  <pubDate>Sat, 04 Apr 2026 ...</pubDate>

  <!-- ЕСТЬ enclosure (thumbnail) — у всех 200/200! -->
  <enclosure url="https://cdn.vdmsti.ru/image/..." type="image/jpeg"/>

  <!-- ЕСТЬ description — только в articles фиде! -->
  <description>3 апреля мэр Москвы освободил от должности главного архитектора...</description>
</item>
```

### Ключевые наблюдения

**Два фида ведут себя по-разному:**

| Поле | `news` | `articles` |
|------|--------|-----------|
| `description` | **ПУСТО** | **ЕСТЬ** — лид статьи |
| `author` | "Ведомости" (бесполезно) | пустой |
| `enclosure` | у 184/200 (92%) | у 200/200 (100%) |
| Тип контента | короткие новости | лонгриды, справки, аналитика |

**`description` есть в articles, нет в news!**
Это важно для коллектора: при paywall в `articles` хотя бы есть лид.
При paywall в `news` нет вообще ничего.

**`<author>` не несёт информации:**
- news: всегда строка "Ведомости" (название редакции)
- articles: пустой
Для поля `author` в БД сохранять `null` в обоих случаях.

**`<category>` может быть иерархической.**
Форматы: `"Политика"`, `"Политика / Власть"`, `"Политика / Международные новости"`.
Разбивать при парсинге: `parent` + `sub`.
В тесте category_sub = None (плоские категории в попавшей выборке) — иерархические
встречаются реже, но при парсинге обрабатывать оба варианта.

**`<link>` = `<guid>` = `<pdalink>`** — все одинаковые.
Баг feedparser из РБК (related_links перебивает link) здесь не возникает.
Использовать `entry.link` — надёжно.

**URL структура разная для разных типов:**
- `/society/news/2026/04/04/1187910-slug` — новость (рубрика/тип/дата/id-slug)
- `/spravka/sergei-kuznetsov` — справочник (тип/slug без даты)
- `/politics/articles/2026/...` — аналитика

**Нет кастомных namespace** — чистый RSS 2.0, feedparser справляется полностью.
ElementTree не нужен (в отличие от РБК, ТАСС, РИА).

**`<ttl>` отсутствует** — нет официальной рекомендации по интервалу.

**Пересечений между news и articles: 0** — полностью независимые фиды.

**⚠️ www в canonical_url:**
feedparser возвращает `https://www.vedomosti.ru/...`.
После `canonical_url()` с `lstrip("www.")` получается `https://vedomosti.ru/...`.
Это корректно — сервер отдаёт 200 и без www. Но быть последовательным:
всегда нормализовать одинаково чтобы дедупликация работала верно.

---

## 5. robots.txt (исследование)

Источник: `https://www.vedomosti.ru/robots.txt`

### Общие правила (User-agent: *)

```
Disallow: /search
Disallow: /user/
Disallow: /advert/
Disallow: /preview/
Disallow: *?*          # ВСЕ URLs с любыми query-параметрами
# НЕТ Crawl-delay
# Статьи /society/news/..., /politics/articles/... — НЕ в Disallow
```

`Disallow: *?*` — очень широкий паттерн, запрещает любой URL с `?`.
Наши статьи чистые, без query params → ОК.

### ⭐ AI-агенты явно разрешены

```
User-agent: anthropic-ai    Allow: /
User-agent: ClaudeBot       Allow: /
User-agent: GPTBot          Allow: /
User-agent: PerplexityBot   Allow: /
User-agent: Google-Extended Allow: /
User-agent: BingBot         Allow: /
User-agent: FacebookBot     Allow: /
# + ещё ~10 AI и поисковых ботов
```

Заблокированы только коммерческие SEO-боты: SemrushBot, BLEXBot, AhrefsBot, MJ12bot.

### Что это значит для нас

| Директива | Значение | Наше действие |
|-----------|---------|---------------|
| **Нет Crawl-delay** | Нет ограничения | `crawl_delay = 1.0` |
| `Disallow: *?*` | Все query params запрещены | Статьи без params — ОК |
| Статьи `/*/news/...` | НЕ в Disallow | Ходить за полным текстом **можно** |
| `Allow: /` для AI | Явное разрешение | Никаких рисков для AI-коллектора |

---

## 6. ⚠️ Paywall — главный риск

В тесте paywall не встретился (0/2). Но выборка слишком мала для выводов.
Нужно наблюдать в процессе работы коллектора.

**При paywall у Ведомостей нет fallback — ситуация хуже чем у Коммерсанта:**

| Источник | При paywall |
|---------|------------|
| Коммерсантъ | есть description в RSS → snippet_lead |
| Ведомости news | нет description → content = "", snippet_lead = "" |
| Ведомости articles | есть description → snippet_lead = description |

**Стратегия:**
```python
PAYWALL_THRESHOLD = 200  # символов

def classify_content(text: str, description: str = "") -> tuple[str, str]:
    if len(text) > 500:
        return text, "ok"
    elif len(text) > 100:
        return text, "partial"
    else:
        # Paywall
        # Для articles: description из RSS есть → использовать как snippet_lead
        # Для news: description пустой → content = ""
        return description, "paywall"
```

Статьи с `quality="paywall"` сохраняем (title + category + url ценны для дайджеста),
в RAG не включаем или включаем с нулевым весом.

---

## 7. Путь одной статьи: от RSS до базы

```
[RSS-фиды Ведомостей]
  │
  ├── GET https://www.vedomosti.ru/rss/news      (каждые 30 мин)
  │   If-None-Match: W/"..." + If-Modified-Since → 304 если не изменился
  ├── GET https://www.vedomosti.ru/rss/articles  (каждые 60 мин)
  │   If-None-Match: W/"..." + If-Modified-Since → 304 если не изменился
  │
  ├── feedparser (namespace не нужен — чистый RSS 2.0):
  │   title, link, guid, pubDate, category, enclosure, description (только articles)
  │
  └── Для каждого <item>:

      ├── canonical_url ← entry.link → нормализация (убрать www, query params)
      ├── Дедупликация по canonical_url → СТОП при известном
      │
      ├── category → parse_category("Политика / Власть") → ("Политика", "Власть")
      ├── description → snippet_lead (только для articles; пусто для news)
      ├── author → null (игнорировать "Ведомости")
      │
      ├── GET на canonical_url (обязателен — full-text в RSS нет)
      │   crawl_delay = 1.0 сек
      │   HTML статический, Playwright не нужен
      │
      ├── trafilatura.bare_extraction(html, favor_precision=True)
      │   Если < 200 символов → paywall
      │   При paywall news: content="" snippet_lead=""
      │   При paywall articles: content="" snippet_lead=description из RSS
      │
      └── Сохранить
          news: (canonical_url, title, content, snippet_lead,
                 published_at, source_id, quality, ...)
          news_raw: (raw_content=html, raw_format='html')
          extra JSONB: {
            "category_parent": "Политика",
            "category_sub": "Власть",      # null если категория плоская
            "thumbnail": "https://...",
            "feed_source": "news" / "articles",
            "quality": "ok" / "partial" / "paywall",
          }
```

---

## 8. Обработка категорий

```python
def parse_category(category: str) -> tuple[str | None, str | None]:
    """
    "Политика / Власть"              → ("Политика", "Власть")
    "Политика / Международные новости" → ("Политика", "Международные новости")
    "Общество"                        → ("Общество", None)
    ""                                → (None, None)
    """
    if not category:
        return None, None
    if " / " in category:
        parts = category.split(" / ", 1)
        return parts[0].strip(), parts[1].strip()
    return category.strip(), None
```

**Наблюдаемые топ-категории** (из 400 items, апрель 2026):
- Политика: 142 | Общество: 85 | Бизнес: 33 | Инвестиции: 30
- Технологии: 28 | Экономика: 20 | Мнения: 19 | Финансы: 18

Категория "Инвестиции" появилась неожиданно — нет в списке RSS-рубрик на сайте.
Вероятно, автоматически проставляется на некоторые типы новостей.

---

## 9. Расписание опроса

| Параметр | news | articles | Обоснование |
|----------|------|---------|-------------|
| `crawl_interval` | 30 мин | 60 мин | news: оперативные; articles: аналитика обновляется реже |
| `crawl_delay` | 1.0 сек | 1.0 сек | AI явно разрешён robots.txt; нет Crawl-delay |
| `priority` | `high` | `medium` | |

**Нагрузка:** 200 items в каждом фиде. ETag экономит трафик при неизменном фиде.
При 48 опросах news/сутки: 140 KB × 48 = ~6.5 MB/сутки (без ETag).
С ETag при редких изменениях: большинство запросов → 0 байт.

---

## 10. Итоговый конфиг для таблицы sources

```python
# 1. Ведомости — новости
{
    "name": "Ведомости (новости)",
    "type": "rss",
    "url": "https://www.vedomosti.ru/rss/news",
    "config": {
        "feed_url": "https://www.vedomosti.ru/rss/news",
        "feed_source": "news",
        "fetch_full_text": True,
        "stop_early_on_known": True,
        "paywall_threshold": 200,
        "has_rss_description": False,   # news не содержит description
        "ignore_author": True,          # "Ведомости" — не журналист
    },
    "crawl_interval": 30,
    "crawl_delay": 1.0,
    "trust_score": 0.90,
    "reliability": "A",
    "priority": "periodic",
    "default_info_type": "daily",
    "default_content_type": "news",
    "legal_status": "restricted",
    "is_active": True,
}

# 2. Ведомости — статьи
{
    "name": "Ведомости (статьи)",
    "type": "rss",
    "url": "https://www.vedomosti.ru/rss/articles",
    "config": {
        "feed_url": "https://www.vedomosti.ru/rss/articles",
        "feed_source": "articles",
        "fetch_full_text": True,
        "stop_early_on_known": True,
        "paywall_threshold": 200,
        "has_rss_description": True,    # articles содержит description — fallback при paywall
        "ignore_author": True,
    },
    "crawl_interval": 60,
    "crawl_delay": 1.0,
    "trust_score": 0.92,
    "reliability": "A",
    "priority": "periodic",
    "default_info_type": "analytics",
    "default_content_type": "analysis",
    "legal_status": "restricted",
    "is_active": True,
}
```

---

## 11. Открытые вопросы

- [x] Поддерживает ли ETag/Last-Modified?
      **Ответ:** ДА, оба. news: W/"69d03c75-224e8", articles: W/"69d00b00-40b49" (слабые ETag).
      Last-Modified тоже есть. Условные запросы работают → 304 при неизменном фиде.
- [x] Сколько items в фидах?
      **Ответ:** news: 200, articles: 200. Размеры: 140 KB и 265 KB.
- [x] Пересечения между фидами?
      **Ответ:** 0. Полностью независимые фиды.
- [x] Статический HTML или JS?
      **Ответ:** Статический. Playwright не нужен. trafilatura работает отлично.
- [x] Thumbnail?
      **Ответ:** news: 184/200 (92%), articles: 200/200 (100%). Почти всегда есть.
- [x] description в RSS?
      **Ответ:** news — НЕТ. articles — ЕСТЬ (лид статьи). Важное различие фидов.
- [ ] Какой % статей за paywall?
      В тесте 0/2. Нужно наблюдать на большой выборке, особенно для articles.
      Ожидаем: news — меньше paywall, articles — больше.

## 12. Результаты тестирования (апрель 2026)

Запущен `test_vedomosti.py`:

**Фиды:**
- news: HTTP 200, ETag `W/"69d03c75-224e8"`, Last-Modified ✓, 140 KB, **200 items**
- articles: HTTP 200, ETag `W/"69d00b00-40b49"`, Last-Modified ✓, 265 KB, **200 items**
- Пересечений: 0 ✓

**Thumbnail:** news 184/200 (92%), articles 200/200 (100%) ✓

**Топ категорий (400 items):**
Политика (142), Общество (85), Бизнес (33), Инвестиции (30), Технологии (28)

**Полный текст (trafilatura):**
- news/Общество: 861 символ ✓ (quality=ok)
- articles/Общество: 4,449 символов ✓ (quality=ok)
- HTML статический, 127-153 KB на страницу. Playwright не нужен ✓

**Paywall:** 0/2 в тесте. Нужно наблюдение на большей выборке.

**description различается по фидам:**
- news: пусто (`''`) — нет fallback при paywall
- articles: полный лид (~300+ символов) — есть fallback при paywall ✓

---

## 13. Итоговые правила для коллектора

```text
1. Подключать как минимум два основных фида: news и articles
2. Для URL статьи использовать link/guid/pdalink — у Ведомостей они совпадают
3. Для news full-text fetch обязателен, потому что description пустой
4. Для articles description сохранять как сильный fallback при paywall
5. Для extraction использовать trafilatura; Playwright не нужен
6. Иерархические categories сохранять как есть, не упрощая на этапе ingestion
7. В metadata сохранять feed_kind, thumbnail, quality и наличие fallback_description
8. Источник считать высококачественным деловым, но с постоянным вниманием к paywall
```

---

## 14. Краткая оценка пригодности для MVP

| Критерий | Оценка |
|----------|--------|
| Техническая простота | `средняя` |
| Юридический риск | `средний` |
| Качество данных | `высокое` |
| Нагрузка на сайт | `средняя` |
| Польза для MVP | `взять` |

Итоговый вывод:
- `Берём в MVP`, но наблюдаем долю paywall-материалов и отдельно учитываем различия между `news` и `articles`
