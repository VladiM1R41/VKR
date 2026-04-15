# Профиль источника: Коммерсантъ

> Составлено на основе исследования: robots.txt, три живых RSS-фида, правила использования.
> Дата последней проверки: `2026-04-04`
> Исследовательский скрипт: [test_kommersant.py](/c:/code/diplom/sources/kommersant/test_kommersant.py)

---

## 1. Зачем этот источник

Коммерсантъ — ведущее деловое издание России (основан 1989). Покрывает:
бизнес, финансы, экономику, политику, право, культуру. Высокий редакционный стандарт.

Что даёт «Джарвису»:
- Деловая повестка — которой нет у РИА/ТАСС/Ленты
- Три типа контента в трёх разных фидах (новости / сайт / газета)
- description-лид всегда присутствует в RSS — можно показывать в дайджесте даже без полного текста
- Наиболее либеральные правила цитирования из всех источников (30%)

---

## 2. Юридический статус

### Правила использования

**Цитирование разрешено:** до 30% объёма материала с обязательной гиперссылкой на оригинал.
Это самые либеральные условия среди всех рассматриваемых источников.

### Для ВКР

✅ Допустимо:
- Читать RSS → извлекать текст → использовать как RAG-контекст
- Генерировать дайджест + ссылка на оригинал Коммерсанта
- Цитировать до 30% с гиперссылкой

❌ Недопустимо:
- Коммерческое использование без договора
- Воспроизведение более 30% без разрешения

**Нормализованное значение для БД: `legal_status = "public_rss"`**.

---

## 3. Три RSS-фида — зачем все три

На главной ленте Коммерсанта материалы из трёх разных потоков идут вперемешку.
Каждый фид — отдельная редакционная линейка:

| Параметр | `news.xml` | `corp.xml` | `main.xml` |
|----------|-----------|-----------|-----------|
| **Название** | Лента новостей | Материалы с сайта | Газета. Главное |
| **Тип контента** | Оперативные новости | Сайтовые материалы | Статьи газеты |
| **Кол-во items** | **666** (~1 день) | **132** | **14** |
| **Размер фида** | 570 KB | 173 KB | 21 KB |
| **Обновление** | Часто (24/7) | Среднее | Медленно |
| **Thumbnail** | ❌ 18% items | ✅ 42% items | ✅ 64% items |
| **description** | Короткий лид | Средний лид (~538 симв) | Развёрнутый (~588 симв) |
| **`information_type`** | `"daily"` | `"daily"` / `"analytics"` | `"analytics"` |
| **`priority`** | `periodic` | `periodic` | `control` |

**Пересечения: 0** — фиды не пересекаются совсем. Дедупликация нужна только как страховка.
Обходим все три, собираем в общую очередь.

### RSS URL

```
https://www.kommersant.ru/rss/news.xml    # лента новостей, ~100 items
https://www.kommersant.ru/rss/corp.xml    # материалы сайта, ~15-30 items
https://www.kommersant.ru/rss/main.xml    # газета Главное, ~15 items
```

---

## 4. Что реально отдаёт RSS (структура фидов)

### news.xml — оперативные новости:

```xml
<item>
  <guid>https://www.kommersant.ru/doc/8568881</guid>
  <category>Мир</category>
  <title>NBC News: Иран ударил по двум вертолетам США из поисковой миссии F-15</title>
  <link>https://www.kommersant.ru/doc/8568881</link>
  <pubDate>Fri, 03 Apr 2026 22:59:21 +0300</pubDate>
  <description>Иранские военнослужащие ударили по двум американским вертолетам,
    которые участвовали в поиске сбитого истребителя F-15. Об этом сообщил NBC News
    со ссылкой на американского чиновника.</description>
  <!-- НЕТ: enclosure, author, content:encoded -->
</item>
```

### corp.xml — материалы сайта (thumbnail у части items):

```xml
<item>
  <guid>https://www.kommersant.ru/doc/8568872</guid>
  <category>Общество</category>
  <title>Колледжи встраивают в региональную экономику // Минпросвещения...</title>
  <link>https://www.kommersant.ru/doc/8568872</link>
  <enclosure url="https://im2.kommersant.ru/..." type="image/jpeg" length="31717"/>
  <pubDate>Fri, 03 Apr 2026 22:47:48 +0300</pubDate>
  <description>Выпускникам колледжей к 2032 году предстоит закрыть две трети
    кадровой потребности экономики страны...</description>
</item>
```

### main.xml — статьи газеты (thumbnail всегда):

```xml
<item>
  <guid>https://www.kommersant.ru/doc/8568856</guid>
  <category>Общество</category>
  <title>Москва осталась без главного по фасадам // Архитектор Кузнецов...</title>
  <link>https://www.kommersant.ru/doc/8568856</link>
  <enclosure url="https://im2.kommersant.ru/Issues.photo2/DAILY/..." type="image/jpeg" length="12242"/>
  <pubDate>Fri, 03 Apr 2026 21:34:05 +0300</pubDate>
  <description>Главный архитектор Москвы Сергей Кузнецов написал прошение об
    отставке... [развёрнутый лид]</description>
</item>
```

### Ключевые наблюдения

**description присутствует во всех трёх фидах** — важнейшее отличие от Lenta.ru!
Даже при paywall у нас есть snippet_lead для отображения в дайджесте.

**category — конкретная рубрика** (Мир, Бизнес, Общество, Фотогалерея и т.д.)
Сразу известна тематика без парсинга страницы.

**guid = link** — без UTM. URL формата `/doc/8568881` (числовой ID).
Canonical URL = нормализация (https, без trailing slash).

**pubDate в +0300** — feedparser конвертирует в UTC. Норма.

**Нет `<author>`** — не указывается в RSS Коммерсанта.

**Заголовки в corp.xml и main.xml** — двойные через `//`:
`«Москва осталась без главного по фасадам // Архитектор отправился в отставку»`.
Часть после `//` — подзаголовок. При сохранении можно разбить или оставить как есть.

---

## 5. ⚠️ Paywall

Часть материалов Коммерсанта — за подпиской. Характерный признак: paywall-статьи
обычно из `main.xml` (газетные материалы) и части `corp.xml`.
`news.xml` — как правило, открыт.

**Стратегия обхода:**
```python
def classify_content(text: str, description: str) -> tuple[str, str]:
    """Определить: полный текст получен или paywall."""
    if len(text) > 500:
        return text, "ok"
    elif len(text) > 50:
        return text, "partial"   # частично доступно
    else:
        # Paywall: возвращаем description как минимальный контент
        return description, "paywall"
```

Статьи с `quality = "paywall"` — включаем в RAG с низким весом.

---

## 6. robots.txt (исследование)

Источник: `https://www.kommersant.ru/robots.txt`

Ключевые правила для `User-agent: *`:

```
Disallow: /doc*=          # /doc/ID?param=value — с query params
Disallow: /*utm_          # UTM-ссылки
Disallow: /*from=         # реферальные параметры
Disallow: /doc-y/         # Яндекс-турбо страницы
Disallow: /articles/      # старый архивный раздел
Disallow: /Daily/         # архивы приложений газеты
Disallow: /Vlast/
Disallow: /Money/         # (и другие спец-издания — нас не касаются)
Disallow: *doc.html*      # старый формат URL
Disallow: /?*feed=*       # фиды с параметрами
# НЕТ Crawl-delay
```

### Что это значит для нас

| Директива | Значение | Наше действие |
|-----------|---------|---------------|
| **Нет Crawl-delay** | Явного ограничения нет | Используем `crawl_delay = 1.0` (стандартный вежливый дефолт) |
| `Disallow: /doc*=` | `/doc/ID?query=` запрещены | Наши URLs чистые (`/doc/8568881`) — ОК |
| `Disallow: /*utm_` | UTM запрещены | В RSS guid=link без UTM — ОК |
| `/doc/` страницы | НЕ в Disallow | Ходить за полным текстом **можно** |
| `Disallow: /doc-y/` | Яндекс-турбо | Нас не касается |

**Clean-param для Яндекса** — зарегистрированы чистые параметры через Вебмастер.
Для нас не важно — мы используем чистые URLs.

---

## 7. Путь одной статьи: от RSS до базы

```
[Три RSS-фида Коммерсанта]
  │
  ├── GET https://www.kommersant.ru/rss/news.xml   (каждые 30 мин)
  ├── GET https://www.kommersant.ru/rss/corp.xml   (каждые 60 мин)
  ├── GET https://www.kommersant.ru/rss/main.xml   (каждые 60 мин)
  │
  ├── Парсинг feedparser:
  │   title, link/guid, pubDate, description, category, enclosure (если есть)
  │
  └── Для каждого <item> из каждого фида:

      ├── canonical_url ← entry.link (нормализация, без query params)
      ├── Дедупликация → СТОП при известном URL
      │
      ├── snippet_lead ← description из RSS (всегда есть!)
      │
      ├── GET на canonical_url (за полным текстом)
      │   crawl_delay = 1.0 сек
      │
      ├── Из HTML:
      │   trafilatura.bare_extraction(html, favor_precision=True)
      │   Если len(text) < 200 → paywall → quality="paywall"
      │
      └── Сохранить
          news: (url, canonical_url, title, content, snippet_lead,
                 published_at, source_id, ...)
          news_raw: (raw_content=html, raw_format='html')
          extra JSONB: {
            "category": "Мир",
            "thumbnail": "https://..." или null,
            "feed_source": "news" / "corp" / "main",
            "quality": "ok" / "paywall",
            "extraction_method": "trafilatura_precision"
          }
```

---

## 8. Расписание опроса

| Параметр | news.xml | corp.xml | main.xml |
|----------|---------|---------|---------|
| `crawl_interval` | 30 мин | 60 мин | 120 мин |
| `crawl_delay` | 1.0 сек | 1.0 сек | 1.0 сек |
| `priority` | `high` | `medium` | `medium` |

**Нагрузка:** news.xml — 666 items в фиде (~1 день), ~4 новых за 30 мин опрос.
corp.xml — 132 items, main.xml — 14 items, оба меняются медленно.

**Почему crawl_delay = 1.0, а не 1.5:**
ETag и Last-Modified поддерживаются всеми тремя фидами → экономят трафик при 304.
Robots.txt не содержит Crawl-delay. Авторизация не нужна. Сервер отвечает нормально.
1.0 сек — стандартный вежливый дефолт (как у Ленты и РИА).

**Важно:** ETag влияет только на экономию трафика RSS-фидов (570 KB → 0 при 304).
Crawl_delay — отдельно, для запросов к страницам статей (`/doc/...`).

---

## 9. Итоговый конфиг для таблицы sources

```python
# Коммерсантъ: три записи в таблице sources

# 1. Лента новостей
{
    "name": "Коммерсантъ (новости)",
    "type": "rss",
    "url": "https://www.kommersant.ru/rss/news.xml",
    "config": {
        "feed_url": "https://www.kommersant.ru/rss/news.xml",
        "feed_source": "news",
        "fetch_full_text": True,
        "stop_early_on_known": True,
        "paywall_threshold": 200,
    },
    "crawl_interval": 30,
    "crawl_delay": 1.0,
    "trust_score": 0.85,
    "reliability": "A",
    "priority": "periodic",
    "default_info_type": "daily",
    "default_content_type": "news",
    "legal_status": "public_rss",
    "is_active": True,
}

# 2. Материалы сайта
{
    "name": "Коммерсантъ (сайт)",
    "type": "rss",
    "url": "https://www.kommersant.ru/rss/corp.xml",
    "config": {
        "feed_url": "https://www.kommersant.ru/rss/corp.xml",
        "feed_source": "corp",
        "fetch_full_text": True,
        "stop_early_on_known": True,
        "paywall_threshold": 200,
    },
    "crawl_interval": 60,
    "crawl_delay": 1.0,
    "trust_score": 0.85,
    "reliability": "A",
    "priority": "periodic",
    "default_info_type": "daily",
    "default_content_type": "analysis",
    "legal_status": "public_rss",
    "is_active": True,
}

# 3. Газета. Главное
{
    "name": "Коммерсантъ (газета)",
    "type": "rss",
    "url": "https://www.kommersant.ru/rss/main.xml",
    "config": {
        "feed_url": "https://www.kommersant.ru/rss/main.xml",
        "feed_source": "main",
        "fetch_full_text": True,
        "stop_early_on_known": True,
        "paywall_threshold": 200,
    },
    "crawl_interval": 120,
    "crawl_delay": 1.0,
    "trust_score": 0.90,
    "reliability": "A",
    "priority": "control",
    "default_info_type": "analytics",
    "default_content_type": "analysis",
    "legal_status": "public_rss",
    "is_active": True,
}
```

---

## 10. Открытые вопросы

- [x] Поддерживает ли Коммерсантъ ETag/Last-Modified?
      **Ответ:** ДА, оба. news.xml и corp.xml — строгий ETag (`"..."`). main.xml — слабый ETag (`W/"..."`).
      Last-Modified поддерживается у всех трёх. Условные запросы работают → **304 Not Modified подтверждён**.
      Второй запрос с If-None-Match вернул 304 и 0 байт — экономия 100% трафика при неизменном фиде (570 KB → 0).
- [x] Сколько items в каждом фиде?
      **Ответ:** news.xml — 666 items (~1 день), corp.xml — 132 items, main.xml — 14 items.
      news.xml значительно больше чем ожидалось — это ~1 день истории, не 100.
- [x] Есть ли пересечения между тремя фидами?
      **Ответ:** НЕТ. 0 пересечений из 812 статей. Фиды полностью независимы.
- [x] Статический HTML или JS-рендеринг?
      **Ответ:** Статический HTML. Playwright не нужен. trafilatura работает отлично.
- [ ] Какой % статей за paywall?
      В тесте все три проверенные статьи — quality=ok. Нужно наблюдать в процессе,
      особенно для main.xml (газетные материалы).

## 11. Результаты тестирования (апрель 2026)

Запущен `test_kommersant.py`:

**Фиды:**
- news.xml: HTTP 200, ETag `"6cd0c541..."`, Last-Modified ✓, 570 KB, **666 items**
- corp.xml: HTTP 200, ETag `"1fb4d743..."`, Last-Modified ✓, 173 KB, **132 items**
- main.xml: HTTP 200, ETag `W/"2735803c..."` (слабый), Last-Modified ✓, 21 KB, **14 items**

**Дедупликация:** 0 пересечений между фидами ✓

**Thumbnail:**
- news.xml: 122/666 (18%) — есть у части новостей
- corp.xml: 56/132 (42%) — у статей с фото
- main.xml: 9/14 (64%) — почти всегда

**Полный текст (trafilatura):**
- news: 814 симв — короткая новость ✓
- corp: 4,136 симв — развёрнутая статья ✓
- main: 5,458 симв — газетный материал ✓
- Paywall: не обнаружен в тесте (все quality=ok)

**HTML:** статический (101-191 KB на страницу). Playwright не нужен ✓

**Заголовки corp/main:** двойные через `//` (основной // подзаголовок).
Функция `split_title()` корректно разбивает.

---

## 12. Итоговые правила для коллектора

```text
1. Подключать три RSS-фида как три отдельные записи sources
2. Для всех фидов использовать link/guid как основной URL статьи
3. description сохранять как snippet_lead даже если full-text extraction провалился
4. За полным текстом ходить на HTML-страницы; Playwright не нужен
5. Для main.xml учитывать риск paywall, но даже там description полезен как fallback
6. Заголовки с // можно сохранять как есть или разбирать на title/subtitle
7. В metadata сохранять category, thumbnail, feed_kind и quality=ok/paywall
8. Для ранжирования news.xml полезнее как оперативный поток, main.xml как аналитический
```

---

## 13. Краткая оценка пригодности для MVP

| Критерий | Оценка |
|----------|--------|
| Техническая простота | `средняя` |
| Юридический риск | `средний` |
| Качество данных | `высокое` |
| Нагрузка на сайт | `средняя` |
| Польза для MVP | `взять` |

Итоговый вывод:
- `Берём в MVP`, особенно `news.xml` и `corp.xml`; `main.xml` тоже полезен, но как менее частый аналитический поток
