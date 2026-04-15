# Профиль источника: РБК

> Составлено на основе исследования: robots.txt, живой RSS-фид, правила использования.
> Дата последней проверки: `2026-04-04`
> Исследовательский скрипт: [test_rbc.py](/c:/code/diplom/sources/rbc/test_rbc.py)

---

## 1. Зачем этот источник

РБК (РосБизнесКонсалтинг) — крупнейший российский деловой медиахолдинг.
Покрывает: финансы, экономику, бизнес, политику, технологии. Очень высокая частота публикаций.

Что даёт «Джарвису»:
- Деловая и финансовая повестка (дополняет Коммерсантъ)
- **`<rbc_news:full-text>`** — полный текст прямо в RSS, как у ТАСС → не нужно ходить на страницы
- `<author>` — имя журналиста
- `<rbc_news:tag>` — несколько тегов на статью (реальная тематика)
- `<rbc_news:newsline>` — тематическая линия (society, politics, economics...)
- `<rbc_news:type>` — тип материала (short_news, article...)

---

## 2. ⚠️ Юридический статус

### Правила использования (rbc.ru)

**Ключевые пункты:**
- «Цитирование материалов сайта допускается безвозмездно в объеме, оправданном целью цитирования» — ст. 1274 п.1 ГК РФ
- «Запрещается автоматизированное извлечение информации сайта любыми сервисами без официального разрешения» — прямой запрет scraping'а
- «Использование материалов в соответствии с **п.3** части 1 ст. 1274 без разрешения запрещается» — п.3 это воспроизведение в прессе/СМИ

**Важное юридическое разграничение:**
РБК запрещает **п.3 ст.1274** (воспроизведение в прессе). Но **п.1 ст.1274** (цитирование в
информационных, научных, учебных целях) — НЕ запрещён.
Прямой запрет «автоматизированного извлечения» касается коммерческих сервисов-агрегаторов.

### Для ВКР

Та же логика что у ТАСС: научно-учебное использование по п.1 ст.1274 ГК РФ.

✅ Допустимо:
- Читать RSS → извлекать текст → использовать как RAG-контекст (ВКР, не коммерция)
- Генерировать дайджест + ссылка на оригинал РБК
- Указывать «РБК» с гиперссылкой на rbc.ru (прямое требование правил)

❌ Недопустимо:
- Коммерческое использование
- Создание конкурирующего агрегатора
- Воспроизведение полных статей без ссылки

**`legal_status = "restricted"`** — ограниченный доступ, допустимо для ВКР по ст.1274 п.1.

---

## 3. Тип источника и доступ

| Параметр | Значение |
|----------|----------|
| Тип | RSS |
| Протокол | HTTPS, pull-режим |
| Аутентификация | Не нужна |
| Полный текст в RSS | **ДА** — `<rbc_news:full-text>` |
| Нужен Playwright | **Нет** — полный текст уже в RSS |

### RSS URL

```
https://rssexport.rbc.ru/rbcnews/news/30/full.rss
```

Домен `rssexport.rbc.ru` — отдельный поддомен специально для RSS-выгрузки.
Число `30` в URL = TTL в минутах = количество items в фиде (всё совпадает: `<ttl>30</ttl>`, 30 items, 30 мин).

---

## 4. Что реально отдаёт RSS (исследование живого фида)

**Проверено:** `https://rssexport.rbc.ru/rbcnews/news/30/full.rss` (апрель 2026)

Структура одного `<item>`:

```xml
<item>
  <title><![CDATA[ В центре Москвы произошла стрельба ]]></title>

  <!-- link = pdalink = canonical URL статьи -->
  <link>https://www.rbc.ru/rbcfreenews/69d0456a9a79476ee8b6e42c</link>
  <pdalink>https://www.rbc.ru/rbcfreenews/69d0456a9a79476ee8b6e42c</pdalink>

  <!-- guid — НЕ URL! Нельзя использовать как canonical_url -->
  <guid isPermaLink="false">rssexport.rbc.ru:society:69d0456a9a79476ee8b6e42c</guid>

  <pubDate>Sat, 04 Apr 2026 01:58:06 +0300</pubDate>
  <description><![CDATA[ На улице Солянка... ]]></description>
  <category>Общество</category>
  <author>Дарья Лебедева</author>

  <!-- Кастомные поля RBC namespace -->
  <rbc_news:type>short_news</rbc_news:type>
  <rbc_news:newsline>society</rbc_news:newsline>
  <rbc_news:news_id>69d0456a9a79476ee8b6e42c</rbc_news:news_id>
  <rbc_news:newsDate_timestamp>1775257086</rbc_news:newsDate_timestamp>
  <rbc_news:newsModifDate>Sat, 04 Apr 2026 01:58:08 +0300</rbc_news:newsModifDate>

  <!-- Теги — несколько штук -->
  <rbc_news:tag><![CDATA[ стрельба ]]></rbc_news:tag>
  <rbc_news:tag><![CDATA[ Москва ]]></rbc_news:tag>
  <rbc_news:tag><![CDATA[ пострадавший ]]></rbc_news:tag>

  <!-- ПОЛНЫЙ ТЕКСТ — самое ценное! -->
  <rbc_news:full-text>
    <![CDATA[ На улице Солянка в центре Москвы в ночь на 4 апреля произошла стрельба.
    Один человек ранен... Подозреваемый задержан. Материал дополняется ]]>
  </rbc_news:full-text>

  <!-- Связанные материалы (есть у части items) -->
  <rbc_news:related_links>
    <link url="https://www.rbc.ru/rbcfreenews/...">
      <rbc_news:title><![CDATA[ ... ]]></rbc_news:title>
      <rbc_news:thumbnail>
        <url>https://s0.rbk.ru/...</url>
        <type>image/jpeg</type>
      </rbc_news:thumbnail>
    </link>
  </rbc_news:related_links>
</item>
```

### Ключевые наблюдения

**`<rbc_news:full-text>` — полный текст в RSS.** Как у ТАСС yandex.xml.
Не нужно делать HTTP-запросы на страницы статей → 1 запрос на весь цикл.
Текст — HTML-фрагмент → обрабатывать через BeautifulSoup как у ТАСС.
100% items содержат full-text (подтверждено тестом).

**⚠️ КРИТИЧЕСКИЙ БАГ feedparser: `<link>` ненадёжен.**
`<rbc_news:related_links>` содержит вложенные `<link url="...">` элементы.
feedparser видит их и подхватывает последний вложенный `<link>` как URL статьи
вместо настоящего `<link>`. В итоге `entry.link` возвращает URL связанного материала.
**Решение для коллектора:**
1. Использовать `<pdalink>` через ElementTree — он однозначный, не встречается внутри related_links
2. Сопоставлять feedparser и ElementTree по позиции в списке, не по URL
```python
# НЕПРАВИЛЬНО:
url = entry.link  # может быть URL из related_links!

# ПРАВИЛЬНО:
pdalink_el = item.find("pdalink")   # через ElementTree
url = pdalink_el.text.strip()
```

**`<guid>` — НЕ URL!** Формат: `rssexport.rbc.ru:society:69d0456a9a79476ee8b6e42c`.
`isPermaLink="false"` прямо указывает. feedparser возвращает это в `entry.id`.
Для canonical_url использовать только `<pdalink>` (через ET), не `entry.link` и не `entry.id`.

**`<author>` — имя журналиста.** 93% items. Остальные 7% — вероятно агентские сообщения.
У Коммерсанта автора в RSS нет — у РБК есть, это плюс.

**`<rbc_news:tag>` — несколько тегов на статью.**
В отличие от одной `<category>` у Коммерсанта. Реальные ключевые слова.
feedparser не парсит этот namespace → только ElementTree.

**`<rbc_news:newsline>`** — машиночитаемая линия: politics, society, sport, radio...
Наблюдаемые значения: politics (16), sport (8), society (5), radio (1) из 30 items.
Удобно для классификации без NLP.

**`<rbc_news:type>`** — тип: `article` (17) или `short_news` (13) из 30 items.
Влияет на `information_type`: article → "analytical", short_news → "daily".

**`<rbc_news:newsDate_timestamp>`** — Unix timestamp публикации.
Резерв если pubDate не парсится (unlikely, но полезно иметь).

**`<rbc_news:related_links>`** — связанные материалы с thumbnail.
Thumbnail есть только здесь, не в `<enclosure>`. Для MVP не извлекаем.

**`<description>` = `<rbc_news:anons>`** — одно и то же содержимое, короткий лид.

**⚠️ HTML-сущности в description.** Поле description содержит HTML-энтити:
`&laquo;Ковер&raquo;` вместо `«Ковер»`. При сохранении в БД прогонять через
`html.unescape()` или извлекать через BeautifulSoup.

**⚠️ Рекламный хвост в full-text.** Каждая статья заканчивается:
`«Оставайтесь на связи с РБК в Max.»`
В реальном коллекторе обрезать через:
```python
import re
text = re.sub(r'\s*Оставайтесь на связи с РБК.*$', '', text, flags=re.DOTALL).strip()
```

---

## 5. robots.txt (исследование)

Источник: `https://www.rbc.ru/robots.txt`

Ключевые правила для `User-agent: *`:

```
Disallow: /*?q=           # поисковые запросы
Disallow: /search/        # поиск
Disallow: *page*          # пагинация
Disallow: /ajax/          # AJAX
Disallow: /companies/     # раздел компаний
# НЕТ Crawl-delay
# /rbcfreenews/ — НЕ в Disallow → статьи доступны
```

Clean-param (огромный список): все UTM-параметры, трекинг-параметры.
Нас не касается — в RSS URLs чистые.

### Что это значит для нас

| Директива | Значение | Наше действие |
|-----------|---------|---------------|
| **Нет Crawl-delay** | Нет ограничения | `crawl_delay = 1.0` (вежливый дефолт) |
| `/rbcfreenews/` | НЕ в Disallow | Ходить на страницы **можно** (если нужно) |
| `Disallow: *page*` | Пагинация | Нас не касается |
| `Disallow: /ajax/` | AJAX | Нас не касается |

**Важно:** robots.txt на `www.rbc.ru`. RSS живёт на `rssexport.rbc.ru` —
технически другой поддомен. Но статьи сами на `www.rbc.ru` — robots.txt применим.

---

## 6. Путь одной статьи: от RSS до базы

```
[RSS-фид РБК]
  │
  ├── GET https://rssexport.rbc.ru/rbcnews/news/30/full.rss
  │   Проверить ETag/Last-Modified (предположительно поддерживаются)
  │
  ├── Парсинг:
  │   feedparser → title, link, pubDate, description, category, author
  │   ElementTree (xmlns:rbc_news="https://www.rbc.ru") →
  │     rbc_news:full-text, rbc_news:tag (несколько!),
  │     rbc_news:newsline, rbc_news:type, rbc_news:news_id
  │
  └── Для каждого <item>:

      ├── canonical_url ← entry.link  (НЕ guid! guid — не URL)
      ├── Дедупликация → СТОП при встрече известного URL
      │
      ├── Контент из RSS (НЕ нужен HTTP-запрос на страницу!):
      │   rbc_news:full-text → BeautifulSoup → clean text
      │   Fallback: description если full-text пустой
      │
      └── Сохранить
          news: (url, canonical_url, title, content, snippet_lead,
                 published_at, source_id, author, ...)
          news_raw: (raw_content=html_fragment, raw_format='html_fragment')
          extra JSONB: {
            "rbc_newsline": "society",
            "rbc_type": "short_news",
            "rbc_news_id": "69d0456a9a79476ee8b6e42c",
            "rbc_tags": ["стрельба", "Москва", "пострадавший"],
            "extraction_method": "rbc_full_text"
          }
```

---

## 7. Расписание опроса

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| `crawl_interval` | 30 минут | `<ttl>30</ttl>` в фиде — официальная рекомендация |
| `crawl_delay` | 1.0 сек | Нет Crawl-delay; но full-text в RSS — запросов на страницы почти нет |
| `priority` | `high` | Высокая частота публикаций, деловая повестка |

**Нагрузка:** 1 HTTP-запрос на весь цикл (только RSS). Страницы не нужны.
TTL=30 в самом фиде подсказывает: опрашивать каждые 30 минут.

---

## 8. Итоговый конфиг для таблицы sources

```python
{
    "name": "РБК",
    "type": "rss",
    "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
    "engine": "auto",
    "delivery_mode": "pull",

    "config": {
        "feed_url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
        "rbc_ns": "https://www.rbc.ru",           # namespace для ElementTree
        "fetch_full_text": False,                  # full-text уже в RSS!
        "use_guid_as_url": False,                  # guid НЕ URL — использовать link
        "stop_early_on_known": True,
    },

    "crawl_interval": 30,        # TTL=30 в самом фиде
    "crawl_delay": 1.0,

    "trust_score": 0.85,
    "reliability": "A",
    "priority": "periodic",

    "default_info_type": "daily",
    "default_content_type": "news",
    "legal_status": "restricted",   # запрет автоматизации, допустимо для ВКР по ст.1274 п.1
    "is_active": True,
}
```

---

## 9. Открытые вопросы

- [x] Поддерживает ли RSS ETag/Last-Modified?
      **Ответ:** НЕТ. Ни ETag, ни Last-Modified. Фид скачивается полностью каждый раз (189 KB).
      Аналогично ТАСС и РИА — без условных запросов.
- [x] Сколько items в фиде?
      **Ответ:** ровно 30. Совпадает с `<ttl>30</ttl>` и числом `30` в URL. ~1-2 часа истории.
- [x] Всегда ли rbc_news:full-text присутствует?
      **Ответ:** ДА, 100% (30/30). Полный текст гарантирован.
- [x] rbc_news:type — какие значения?
      **Ответ:** `article` (17), `short_news` (13). Два типа в наблюдаемой выборке.
- [x] Есть ли thumbnail?
      **Ответ:** только в `<rbc_news:related_links>` (у связанных материалов), не у самого item.
      Для MVP не извлекаем — сложно и не приоритетно.
- [ ] Проверить: feedparser возвращает неверный link из-за related_links — задокументировано,
      исправлено использованием pdalink + позиционное сопоставление с ElementTree.
- [ ] Наблюдать: бывает ли author пустым (сейчас 93%, 2 из 30 без автора — вероятно агентские).

## 10. Результаты тестирования (апрель 2026)

Запущен `test_rbc.py`:
- HTTP 200, размер: 189,585 байт
- ETag: нет. Last-Modified: нет.
- Записей в фиде: **30** (ровно, не больше)
- `rbc_news:full-text`: **100%** ✓
- `author`: 93% (28/30)

**Распределение rbc_news:newsline:**
- politics: 16, sport: 8, society: 5, radio: 1

**Распределение rbc_news:type:**
- article: 17, short_news: 13

**Баг feedparser:** `<link>` из `<rbc_news:related_links>` перебивает настоящий `<link>` статьи.
feedparser возвращает URL связанного материала вместо URL самой статьи.
**Исправление:** использовать `<pdalink>` (однозначный элемент) через ElementTree.
Сопоставление feedparser ↔ ElementTree — по позиции в списке, не по URL.

**HTML-сущности в description:** `&laquo;Ковер&raquo;` — в snippet_lead попадают сырые HTML-энтити.
При сохранении в БД нужно прогнать через `html.unescape()` или BeautifulSoup.

**Рекламный хвост:** текст заканчивается «Оставайтесь на связи с РБК в Max.» — маркетинговый хвост
в full-text. При необходимости можно отрезать через regex `r'Оставайтесь на связи.*$'`.

---

## 11. Итоговые правила для коллектора

```text
1. Забрать RSS по URL https://rssexport.rbc.ru/rbcnews/news/30/full.rss
2. Для URL статьи не использовать entry.link и entry.id вслепую
3. Брать canonical URL из pdalink через ElementTree
4. Полный текст брать из rbc_news:full-text — на HTML-страницы ходить не нужно
5. description использовать как snippet_lead
6. В metadata сохранять author, newsline, type, tags и extraction_method=rss_full_text
7. При необходимости чистить HTML entities и маркетинговый хвост в конце full-text
8. Источник считать деловым RSS с высокой ценностью и низкой сетевой нагрузкой
```

---

## 12. Краткая оценка пригодности для MVP

| Критерий | Оценка |
|----------|--------|
| Техническая простота | `средняя` |
| Юридический риск | `средний` |
| Качество данных | `высокое` |
| Нагрузка на сайт | `низкая` |
| Польза для MVP | `взять` |

Итоговый вывод:
- `Берём в MVP` как один из самых удобных деловых источников благодаря full-text прямо в RSS
