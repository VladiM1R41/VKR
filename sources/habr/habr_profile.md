# Профиль источника: Хабр

> Всё что нужно знать для правильного сбора новостей с Хабра.
> Составлено на основе реального исследования: robots.txt, живой RSS-фид, документация.
> Дата последней проверки: `2026-04-03`
> Исследовательский скрипт: [test_habr.py](/c:/code/diplom/sources/habr/test_habr.py)

---

## 1. Зачем этот источник

Хабр — крупнейшая русскоязычная IT-платформа. Статьи пишут разработчики, аналитики,
технические специалисты. Это **не новостное агентство** — это профессиональное сообщество.

Что даёт «Джарвису»:
- Длинные технические разборы (чего нет в ТАСС и РИА)
- Покрытие IT-тематики: AI, DevOps, безопасность, разработка
- Живые мнения и опыт практиков, а не пресс-релизы
- Теги и хабы — готовая тематическая разметка (не нужно Слою 2 классифицировать самому)

Контент медленный: ~20-40 публикаций в день, часто длиннее 2000 слов.
Это `information_type = "analytics"`, не `"daily"` и уж точно не `"breaking"`.

---

## 2. Тип источника и доступ

| Параметр | Значение |
|----------|----------|
| Тип | RSS |
| Протокол | HTTPS, pull-режим |
| Аутентификация | Не нужна |
| Полный текст в RSS | **НЕТ** (только лид + «Читать далее») |
| Нужен Playwright | Нет (статический HTML) |

### Официальная документация RSS

Источник: `https://habr.com/en/docs/help/lenta/`

Хабр поддерживает RSS для:
- Всех статей подряд (без порога, ≥10, ≥25, ≥50, ≥100 рейтинга)
- Лучших за день/неделю/месяц
- По хабам (разделам), по потокам, по тегам

Доступные параметры URL:
- `?fl=ru` — только русскоязычные статьи
- `?with_hubs=true` — добавить хабы (разделы) в `<category>`
- `?with_tags=true` — добавить пользовательские теги в `<category>`
- `?limit=100` — увеличить выдачу до 100 публикаций (дефолт ~20)

### Итоговый RSS URL

```
https://habr.com/ru/rss/articles/?fl=ru&limit=100&with_hubs=true
```

Почему именно такой:
- `fl=ru` — нас интересует русскоязычный контент
- `limit=100` — за один запрос берём максимум, экономим обращения к серверу
- `with_hubs=true` — хабы попадут в `<category>`, Слой 2 получит тематическую разметку

---

## 3. Что реально отдаёт RSS (исследование живого фида)

**Проверено:** `https://habr.com/ru/rss/articles/?fl=ru` (апрель 2026)

Структура одного `<item>`:

```xml
<item>
  <title><![CDATA[ Заголовок статьи ]]></title>

  <!-- GUID — чистый URL без UTM-параметров -->
  <guid isPermaLink="true">https://habr.com/ru/articles/1019062/</guid>

  <!-- link — URL с UTM-параметрами -->
  <link>https://habr.com/ru/articles/1019062/?utm_source=habrahabr&utm_medium=rss&utm_campaign=1019062</link>

  <!-- description — ТОЛЬКО ЛИД, не полный текст -->
  <description>
    <![CDATA[
      <p>Первый абзац статьи...</p>
      <a href="...#habracut">Читать далее</a>
    ]]>
  </description>

  <!-- pubDate — время в UTC (GMT) -->
  <pubDate>Fri, 03 Apr 2026 14:37:35 GMT</pubDate>

  <!-- dc:creator — username автора -->
  <dc:creator><![CDATA[ username ]]></dc:creator>

  <!-- category — теги пользователя (несколько) -->
  <category>python</category>
  <category>machine learning</category>
</item>
```

### Ключевые наблюдения

**Полного текста нет.** `<description>` содержит только лид (1-2 абзаца) и ссылку «Читать далее».
Тега `<content:encoded>` нет. За полным текстом нужно идти на страницу статьи.

**Время в UTC.** `pubDate` в формате GMT = UTC. Это корректно.
Москва = UTC+3, поэтому «14:38 GMT» = «17:38 МСК» — это не баг, а правильное UTC-время.
Парсить нужно через `calendar.timegm()`, не `time.mktime()` (иначе сдвиг на 3 часа).

**Два URL в одном item.** `<guid>` — чистый URL без UTM. `<link>` — с UTM-параметрами.
- Для получения полного текста используем **guid** (чистый) или стрипаем UTM из link
- Для `canonical_url` в базе — тоже чистый URL (без utm_, без www)
- UTM-ссылка запрещена в robots.txt (Disallow: `/*?*utm_`), чистая — разрешена

---

## 4. robots.txt (исследование)

Источник: `https://habr.com/robots.txt` (апрель 2026)

```
User-agent: *
Crawl-delay: 10
Disallow: /search/
Disallow: /*?*utm_
Disallow: /ru/companies/*/fans/
Disallow: /en/companies/*/fans/
...
```

### Что это значит для нас

| Директива | Что значит | Наше действие |
|-----------|-----------|---------------|
| `Crawl-delay: 10` | Минимум 10 сек между запросами | `crawl_delay = 10.0` в конфиге |
| `Disallow: /*?*utm_` | Нельзя запрашивать URL с utm-параметрами | Использовать guid (чистый URL), не link |
| `Disallow: /search/` | Поиск закрыт | Нас не касается, мы читаем статьи |
| Страницы статей | Не в Disallow | Ходить за полным текстом можно |

**Вывод:** ходить на страницы статей за полным текстом **легально** при соблюдении `Crawl-delay: 10`.

---

## 5. Путь одной статьи: от RSS до базы

```
[RSS-фид Хабра]
  │
  ├── GET https://habr.com/ru/rss/articles/?fl=ru&limit=100&with_hubs=true
  │   Заголовки запроса:
  │   - User-Agent: JarvisNewsBot/1.0 (academic-research)
  │   - If-None-Match: {etag из прошлого запроса}
  │   - If-Modified-Since: {modified из прошлого запроса}
  │
  ├── Если 304 Not Modified → ничего нового, выходим
  │
  ├── Если 200 OK → парсим через feedparser
  │   Сохраняем новый ETag и Last-Modified → в sources.config
  │
  └── Для каждого <item>:

      ├── Шаг 1: Извлечь URL
      │   Взять entry.id (guid) — он уже без UTM
      │   Canonical URL = убрать www, убрать trailing slash, схема https
      │
      ├── Шаг 2: Дедупликация
      │   Проверить canonical_url — есть в базе? → пропустить
      │   Проверить title_hash (MD5 lowercase) → похожая новость есть? → кластер
      │
      ├── Шаг 3: Получить полный текст
      │   GET на canonical_url (чистый, не UTM!)
      │   Ждать: crawl_delay = 10 секунд после предыдущего запроса к habr.com
      │   trafilatura.bare_extraction(html, favor_precision=True)
      │   Если текст < 200 символов → fallback: trafilatura(favor_recall=True)
      │   Если всё равно пусто → сохранить summary из RSS, пометить quality='low'
      │
      ├── Шаг 4: Извлечь метаданные
      │   title   ← entry.title
      │   author  ← entry.dc_creator (или trafilatura нашла автора)
      │   tags    ← entry.tags (список category)
      │   hubs    ← entry.tags где с_hubs=true (с параметром with_hubs)
      │   date    ← entry.published_parsed через calendar.timegm() → UTC datetime
      │
      └── Шаг 5: Сохранить
          INSERT INTO news (url, canonical_url, title, content, snippet_lead,
                            published_at, source_id, channel_type, ...)
          INSERT INTO news_raw (news_id, raw_content='html страницы', raw_format='html')
```

---

## 6. Извлечение полного текста: особенности Хабра

Хабр — стандартный статический HTML-сайт. Playwright не нужен.
trafilatura справляется хорошо: плотный текст статьи легко отделяется от навигации.

**Потенциальные проблемы:**
- Статьи с большим количеством кода: trafilatura может схлопнуть блоки кода
- Статьи с таблицами: нужен `include_tables=True`
- Статьи за paywall: у Хабра нет paywall, все статьи открыты

**Что брать из trafilatura:**
```python
doc = trafilatura.bare_extraction(
    html,
    url=article_url,
    include_comments=False,  # комментарии — отдельный контент
    include_tables=True,     # таблицы часто содержат данные (бенчмарки, сравнения)
    favor_precision=True,    # не захватывать боковую панель
    deduplicate=True,        # убрать повторы абзацев
)
# doc.text  — полный текст
# doc.author — автор (перепроверяет dc:creator из RSS)
# doc.date  — дата публикации (перепроверяет pubDate из RSS)
# doc.categories — хабы (дополнительно к RSS-тегам)
```

---

## 7. Дедупликация

Хабр — специфический источник с точки зрения дубликатов:

**Что встречается:**
- Переводы: помечаются в заголовке `[Перевод]`. Это оригинальный контент Хабра,
  дублями они не являются.
- Корпоративные статьи: `habr.com/ru/companies/ggsel/articles/...` — путь другой,
  но guid указывает на `habr.com/ru/articles/...`. Важно: canonical_url должен брать
  именно путь из guid, а не из link.

**Уровень 1 (URL):** canonical_url уникален для каждой статьи Хабра.

**Уровень 2 (title_hash):** маловероятно что два источника напишут с одинаковым заголовком.
Хабр — уникальные авторские статьи. Дублей по title_hash практически не будет.

**Вывод:** для Хабра дедупликация — не главная проблема.
Одна статья = один уникальный URL = один уникальный `event_cluster_id`.

---

## 8. Расписание опроса

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| `crawl_interval` | 120 минут | ~30 статей в день = ~1.25 статьи в час |
| `crawl_delay` | 10.0 сек | robots.txt `Crawl-delay: 10` |
| `priority` | `control` | Не breaking news, нет смысла проверять часто |

**Расчёт:** если публикуется 30 статей в день, то при опросе каждые 2 часа
мы за один запрос получим ~5-6 статей (30/12 опросов). При `limit=100` — с запасом.

---

## 9. Мониторинг здоровья

**Что может сломаться:**
- Структура статей не изменится (trafilatura работает без CSS-селекторов)
- RSS URL стабилен годами
- Единственный риск: Хабр поменяет формат RSS или закроет доступ без авторизации

**Метрика здоровья:**
- `articles_last_24h` — норма: 20-40. Если 0 при обычном >20 → проблема
- `avg_content_length` — норма для Хабра: 3000-8000 символов. Если вдруг <500 → парсер сломался

**Health check:** раз в сутки попробовать скачать фид, проверить что есть записи
не старше 7 дней, извлечь текст из одной статьи, проверить длину.

---

## 10. Итоговый конфиг для таблицы sources

```python
{
    "name": "Хабр",
    "type": "rss",
    "url": "https://habr.com/ru/rss/articles/?fl=ru&limit=100&with_hubs=true",
    "engine": "auto",           # статический HTML, httpx справится
    "delivery_mode": "pull",

    "config": {
        "feed_url": "https://habr.com/ru/rss/articles/?fl=ru&limit=100&with_hubs=true",
        "etag": None,           # заполнится после первого запроса
        "modified": None,       # заполнится после первого запроса
        "fetch_full_text": True,    # RSS даёт только лид — нужен полный текст
        "use_guid_as_url": True,    # брать URL из <guid>, не из <link> (без UTM)
    },

    "crawl_interval": 120,      # каждые 2 часа
    "crawl_delay": 10.0,        # robots.txt Crawl-delay: 10

    "trust_score": 0.80,        # хорошее сообщество, но нет редакционной верификации
    "reliability": "B",         # надёжный источник, не официальное СМИ

    "priority": "control",      # не breaking news

    "default_info_type": "analytics",   # длинные технические статьи
    "default_content_type": "analysis", # аналитика и разборы

    "legal_status": "public_rss",       # публичный RSS, robots.txt соблюдён

    "is_active": True,
}
```

---

## 11. Открытые вопросы

- [x] Проверить: нужен ли `?with_tags=true` отдельно или `with_hubs=true` уже включает всё?
      **Ответ:** `with_tags=true` НЕ нужен. Пользовательские метки и так всегда в `<category>`
      по умолчанию. `with_tags=true` только добавляет «Метки: ...» в description — бесполезно.
- [x] Уточнить: есть ли разница между хабами и тегами в `<category>` после `with_hubs=true`
      **Ответ:** в `<category>` хабы и метки идут вперемешку — различить нельзя.
      Хабы (официальные разделы: Python, DIY или Сделай сам) и метки (свободные теги: умныйдом)
      разделяются только по тексту «Хабы: ...» в `<description>`.
      Для нашей системы смешанный список нормален — Layer 2 разберётся при классификации.
- [ ] Проверить robots.txt через несколько месяцев — Crawl-delay мог измениться

## 12. Результаты тестирования (апрель 2026)

Запущен `test_habr.py`:
- HTTP 200, размер фида: 270,221 байт
- Записей в фиде: 100 ✓
- **ETag: не поддерживается** — Хабр не возвращает ETag/Last-Modified.
  В конфиге `etag: null, modified: null` навсегда. Дедупликация по canonical_url.
- content:encoded: отсутствует ✓ (нужен fetch_full_text=True, подтверждено)
- trafilatura (favor_precision): 20,788 символов из HTML 288,693 → всё чисто
- Дата в UTC: `2026-04-03 15:20 UTC` (Москва = +3 ч = 18:20 МСК) ✓
- guid vs link: guid = `habr.com/ru/articles/1019078/` (чистый),
  link = `...?utm_source=habrahabr&utm_medium=rss&utm_campaign=1019078` (с UTM) ✓

---

## 13. Итоговые правила для коллектора

```text
1. Забрать RSS по URL https://habr.com/ru/rss/articles/?fl=ru&limit=100&with_hubs=true
2. Для URL статьи использовать guid / entry.id, а не link с UTM
3. canonical_url строить из чистого URL без query params
4. Не рассчитывать на content:encoded — полного текста в RSS нет
5. За полным текстом ходить на HTML-страницу статьи с crawl_delay=10 сек
6. Для текста использовать trafilatura, при необходимости fallback на favor_recall
7. В metadata сохранять автора, смешанный список tags/categories и extraction_method
8. Источник считать аналитическим, а не breaking-news
```

---

## 14. Краткая оценка пригодности для MVP

| Критерий | Оценка |
|----------|--------|
| Техническая простота | `средняя` |
| Юридический риск | `низкий` |
| Качество данных | `высокое` |
| Нагрузка на сайт | `средняя` |
| Польза для MVP | `взять` |

Итоговый вывод:
- `Берём в MVP` как главный технологический и аналитический источник, но не как оперативную новостную ленту
