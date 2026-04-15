# Профиль источника: РИА Новости

> Составлено на основе исследования: robots.txt, живой RSS-фид, правила использования, исходник страницы.
> Дата последней проверки: `2026-04-03`
> Исследовательский скрипт: [test_ria.py](/c:/code/diplom/sources/ria/test_ria.py)

---

## 1. Зачем этот источник

РИА Новости — второе по значимости государственное информационное агентство России
(входит в МИА «Россия сегодня» вместе с Sputnik). Очень высокая частота публикаций:
~150 новостей в день, 24/7.

Что даёт «Джарвису»:
- Широкое международное покрытие (В мире, Украина, экономика)
- Оперативная лента: самые быстрые из всех рассматриваемых источников
- Поле `<rian:priority>` — встроенный приоритет редакции
- Исходник страниц — статический HTML, trafilatura работает хорошо

---

## 2. ⚠️ Юридический статус

### Правила использования (ria.ru/docs/about/copyright.html)

**Пункт 2.2:** «Кроме установленных действующим законодательством РФ случаев любое
Использование Контента без получения предварительного письменного разрешения
правообладателя запрещено.»

**Пункт 2.5:** Аналитические и авторские материалы — только после письменного
разрешения, запрещена переработка.

**Важное отличие от ТАСС:** В правилах РИА **нет явного запрета на RSS-ленты**
(как в п.4.5 ТАСС). Ограничение общее, а не специфическое для автоматического сбора.

### Для ВКР

Та же логика что у ТАСС: п.2.3 разрешает свободное использование по законодательству РФ
(ст. 1274 ГК — цитирование в информационных целях).

✅ Допустимо:
- Читать RSS → извлекать текст → использовать как RAG-контекст
- Генерировать дайджест + ссылка на оригинал РИА
- Указывать «РИА Новости» с прямой гиперссылкой (п.2.3.2)

❌ Недопустимо:
- Показывать raw-текст пользователям без ссылки
- Коммерческое использование
- Переработка аналитических материалов без разрешения

Для использования новостных лент: россиясегодня.рф/russian-news-feeds/
(коммерческий сервис, для ВКР не нужен).

---

## 3. Тип источника и доступ

| Параметр | Значение |
|----------|----------|
| Тип | RSS |
| Протокол | HTTPS, pull-режим |
| Аутентификация | Не нужна |
| Полный текст в RSS | **НЕТ** (беднейший RSS — только заголовок + ссылка) |
| Нужен Playwright | **Нет** — статический HTML, контент в исходнике |

### RSS URL

```
https://ria.ru/export/rss2/archive/index.xml
```

---

## 4. Что реально отдаёт RSS (исследование живого фида)

**Проверено:** `https://ria.ru/export/rss2/archive/index.xml` (апрель 2026)

Структура одного `<item>`:

```xml
<item>
  <title>"Ненависть к русским". Дерзкое заявление Мерца о России поразило Запад</title>

  <!-- guid = link, без UTM, URL с датой в пути -->
  <link>https://ria.ru/20260403/merts-2085130256.html</link>
  <guid>https://ria.ru/20260403/merts-2085130256.html</guid>

  <!-- pubDate в МОСКОВСКОМ ВРЕМЕНИ (+0300) -->
  <pubDate>Fri, 03 Apr 2026 21:57:07 +0300</pubDate>

  <!-- category всегда одна и та же — бесполезна -->
  <category>Лента новостей</category>

  <!-- кастомные поля РИА — самое ценное в RSS! -->
  <rian:priority xmlns:rian="http://rian.ru/ns">3</rian:priority>
  <rian:type xmlns:rian="http://rian.ru/ns">article</rian:type>

  <!-- Отсутствуют: description, content:encoded, author, enclosure -->
</item>
```

### Ключевые наблюдения

**RSS отдаёт только заголовок и ссылку — самый бедный из всех источников.**
Нет description (Лента), нет full-text в RSS (ТАСС), нет даже thumbnail (Лента/ТАСС).
Полный текст — только со страницы статьи, обязательно.

**`<rian:priority>` — встроенный редакционный приоритет.**
У всех проверенных items = 3. Вероятно, шкала 1-5:
- priority 1 или 2 → breaking news → `information_type = "breaking"`
- priority 3 → обычная новость → `information_type = "daily"`
feedparser может не парсить этот namespace → извлекать через ElementTree.

**`<rian:type>` — тип материала.**
"article" — обычная статья. Могут быть: "news", "analysis", "interview".
Полезно для классификации `content_type`.

**`<category>` = "Лента новостей" у всех items — бесполезна.**
Тематику новости придётся определять из текста статьи (Слой 2) или из `page_tags`
которые видны в HTML страницы (в `window.dataLayer`).

**URL структура:** `/YYYYMMDD/slug-articleID.html` — дата встроена в URL.
Canonical URL: нормализация (https, без trailing slash, без query params).

**`<guid>` = `<link>` — одинаковые, без UTM.** Как у Ленты и ТАСС.

**`<pubDate>` в `+0300`.** feedparser конвертирует в UTC. Норма.

---

## 5. robots.txt (исследование)

Источник: `https://ria.ru/robots.txt` (апрель 2026)

Ключевые правила для `User-agent: *`:

```
User-agent: *
Disallow: *-print.html$      # версии для печати
Disallow: /sys_*             # системные страницы
Disallow: /search/           # поиск
Disallow: /*/?*              # URL с query-параметрами (кроме pagination)
Disallow: /*/*?*             # то же для двухуровневых путей
Allow:    /*?page=*          # pagination — разрешена
```

### Что это значит для нас

| Директива | Значение | Наше действие |
|-----------|---------|---------------|
| **Нет Crawl-delay** | Нет явного ограничения | Используем `crawl_delay = 1.0` |
| `Disallow: /*/?*` | URL с `?param=value` запрещены | Наши статьи чистые (`/20260403/article.html`) — ОК |
| Статьи `/YYYYMMDD/*.html` | НЕ в Disallow | Ходить за полным текстом **можно** |
| `Disallow: /specialprojects/` | Спецпроекты | Нас не касается |

**Вывод:** робот может ходить на страницы статей. Только query-params добавлять нельзя.

---

## 6. Страницы статей: рендеринг

**Проверено:** View Source (Ctrl+U) статьи в браузере.

HTML страниц РИА — **статический** (server-side rendered):
- Текст статьи виден в исходнике сразу, без JS-выполнения
- Playwright **не нужен**
- trafilatura справляется без CSS-селекторов

Полезная находка в исходнике:
```javascript
window.dataLayer.push({
    'page_tags': 'В мире, Украина, Россия, Германия, Фридрих Мерц, ...',
    'page_rubric': 'В мире',
    'article_length': '1021',
})
```
`page_tags` и `page_rubric` — реальная тематика статьи, которой нет в RSS `<category>`.
Можно извлекать через regex из HTML для сохранения в `extra` JSONB.

---

## 7. Путь одной статьи: от RSS до базы

```
[RSS-фид РИА]
  │
  ├── GET https://ria.ru/export/rss2/archive/index.xml
  │   Нет ETag — каждый раз полный фид
  │
  ├── Парсинг:
  │   feedparser → title, link, guid, pubDate
  │   ElementTree → rian:priority, rian:type (кастомные поля)
  │
  └── Для каждого <item> (от новых к старым):

      ├── canonical_url ← entry.link (нормализация, без query params)
      ├── Дедупликация → СТОП при встрече известного URL
      │
      ├── GET на canonical_url (обязательно — RSS пустой)
      │   crawl_delay = 1.0 сек
      │   Статус 200, статический HTML
      │
      ├── Из HTML:
      │   trafilatura.bare_extraction(html, favor_precision=True)
      │   Опционально: regex для page_tags, page_rubric из dataLayer
      │
      └── Сохранить
          news: (url, canonical_url, title, content, snippet_lead,
                 published_at, source_id, ...)
          news_raw: (raw_content=html, raw_format='html')
          extra JSONB: {
            "rian_priority": 3,
            "rian_type": "article",
            "page_rubric": "В мире",
            "page_tags": ["Украина", "Германия", ...]
          }
```

---

## 8. Извлечение метаданных из HTML

Помимо trafilatura для текста — полезные данные в `window.dataLayer`:

```python
import re

def extract_datalayer(html: str) -> dict:
    """Извлечь page_tags и page_rubric из window.dataLayer."""
    tags_match = re.search(r"'page_tags'\s*:\s*'([^']+)'", html)
    rubric_match = re.search(r"'page_rubric'\s*:\s*'([^']+)'", html)
    length_match = re.search(r"'article_length'\s*:\s*'(\d+)'", html)

    return {
        "page_tags": tags_match.group(1).split(", ") if tags_match else [],
        "page_rubric": rubric_match.group(1) if rubric_match else None,
        "article_length": int(length_match.group(1)) if length_match else None,
    }
```

Это даст реальную тематику вместо бесполезного «Лента новостей».

---

## 9. Расписание опроса

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| `crawl_interval` | 20 минут | ~150 новостей/день = ~6 в час, нужна частота |
| `crawl_delay` | 1.0 сек | Нет Crawl-delay, вежливый дефолт |
| `priority` | `high` | Оперативная лента, много breaking news |

**Нагрузка на их сервер:** при 20 мин интервале ~2 новые статьи за опрос.
Фид содержит 94 записи (~1 день). Размер фида: 59 KB (самый лёгкий из всех!).
94 статьи × 1 сек crawl_delay — только для новых статей (stop_early_on_known).

---

## 10. Итоговый конфиг для таблицы sources

```python
{
    "name": "РИА Новости",
    "type": "rss",
    "url": "https://ria.ru/export/rss2/archive/index.xml",
    "engine": "auto",
    "delivery_mode": "pull",

    "config": {
        "feed_url": "https://ria.ru/export/rss2/archive/index.xml",
        "etag": None,
        "modified": None,
        "fetch_full_text": True,        # RSS пустой, страница обязательна
        "use_guid_as_url": False,       # guid = link (одинаковые, без UTM)
        "extract_datalayer": True,      # парсить page_tags/page_rubric из JS
        "stop_early_on_known": True,    # прекращать при встрече известного URL
    },

    "crawl_interval": 20,       # каждые 20 минут
    "crawl_delay": 1.0,         # нет Crawl-delay в robots.txt

    "trust_score": 0.80,
    "reliability": "A",

    "priority": "periodic",

    "default_info_type": "daily",       # меняется если rian:priority ≤ 2
    "default_content_type": "news",

    "legal_status": "restricted",       # общий запрет без договора
                                         # допустимо для ВКР по ст.1274 ГК РФ
    "is_active": True,
}
```

---

## 11. Открытые вопросы

- [x] Поддерживает ли РИА ETag/Last-Modified?
      **Ответ:** НЕТ. Ни ETag, ни Last-Modified.
- [x] Сколько записей в фиде?
      **Ответ:** 94 записи (~1 день истории). Размер: 59 KB — самый лёгкий фид.
- [x] Работает ли парсинг window.dataLayer?
      **Ответ:** ДА, отлично. page_rubric="Происшествия" (не "Лента новостей"), 
      page_tags=['Происшествия', 'Россия', 'Санкт-Петербург', 'СК РФ'].
- [x] Точность trafilatura?
      **Ответ:** 871 символ vs 843 ожидаемых (dataLayer) → отношение 1.03x ✓
      Исключительно точное извлечение. favor_precision достаточно.
- [x] Статический или JS-рендеренный HTML?
      **Ответ:** Статический. Playwright не нужен. trafilatura работает.
- [ ] Диапазон значений rian:priority — все 94 items имели priority=3. Нужно наблюдать
      в процессе работы: при каком приоритете ТАСС пишет "срочно". Ожидаем 1-2 = breaking.
- [ ] Проверить яндекс-фид: `/export/rss2/yandex/index.xml` — есть ли full-text?

## 12. Результаты тестирования (апрель 2026)

Запущен `test_ria.py`:
- HTTP 200, размер фида: 59,180 байт (59 KB — самый компактный!)
- Записей в фиде: 94 (≈1 день истории)
- ETag: нет. Last-Modified: нет.
- rian:priority: все 94 items = 3 (breaking не наблюдалось)
- rian:type: все items = "article"
- window.dataLayer парсинг: работает идеально ✓
  - page_rubric: реальная рубрика (не "Лента новостей") ✓
  - page_tags: реальные теги статьи ✓
- trafilatura (favor_precision): 871 символ, отношение к article_length = 1.03x ✓
- Страницы: статический HTML 167K, Playwright не нужен ✓

---

## 13. Итоговые правила для коллектора

```text
1. Забрать RSS по стандартному фиду РИА
2. URL статьи брать из RSS, canonical_url строить обычной нормализацией
3. За полным текстом ходить на HTML-страницу статьи
4. Для текста использовать trafilatura как основной extractor
5. Дополнительные метаданные извлекать из window.dataLayer: rubric и tags
6. rian:priority сохранять в metadata и позже использовать для breaking-маркировки
7. Playwright не нужен, HTML статический
8. Источник считать быстрым агентским потоком общего назначения
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
- `Берём в MVP` как один из ключевых оперативных источников, но с юридической осторожностью и обязательной ссылкой на оригинал
