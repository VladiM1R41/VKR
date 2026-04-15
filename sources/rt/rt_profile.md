# Профиль источника: RT на русском

> Составлено на основе исследования: robots.txt, живой RSS-фид.
> Дата последней проверки: `2026-04-04`
> Исследовательский скрипт: [test_rt.py](/c:/code/diplom/sources/rt/test_rt.py)

---

## 1. Зачем этот источник

RT (Russia Today) на русском — крупный международный новостной канал с российским государственным
финансированием. Покрывает: мировую политику, международные отношения, конфликты, спорт.

Что даёт «Джарвису»:
- Международная повестка — покрытие событий за рубежом с российской точки зрения
- Дополняет ТАСС/РИА другим углом подачи (контрарный взгляд — anti-confirmation bias)
- Быстрые короткие новости (похожи на РИА по стилю)
- `<description>` есть — краткий лид (хотя содержит HTML)

---

## 2. Юридический статус

### Владелец

**АНО «ТВ-Новости»** — автономная некоммерческая организация, государственное финансирование.
Зарегистрировано в России.

### Правила использования

Страница с явными правилами не найдена. Применяем стандартную логику:
- Цитирование с гиперссылкой на russian.rt.com — общепринятая норма
- RSS публично предоставлен для агрегации → использование RSS правомерно
- Коммерческое использование — вне контракта недопустимо

### Для ВКР

✅ Допустимо:
- Читать RSS → full-text со страницы → RAG-контекст (ВКР, не коммерция)
- Генерировать дайджест + ссылка на оригинал RT
- Ст. 1274 ГК РФ п.1 (цитирование в научных целях)

❌ Недопустимо:
- Коммерческое использование
- Воспроизведение без ссылки

**`legal_status = "restricted"`** — государственное СМИ, допустимо для ВКР.

---

## 3. Тип источника и доступ

| Параметр | Значение |
|----------|----------|
| Тип | RSS |
| Протокол | HTTPS, pull-режим |
| Аутентификация | Не нужна |
| Полный текст в RSS | **НЕТ** — только лид в description |
| Нужен Playwright | Нет |

### RSS URL

```
https://russian.rt.com/rss
```

---

## 4. Что реально отдаёт RSS (исследование живого фида)

**Проверено:** апрель 2026

Объявленные namespace: `media`, `content`, `atom`, `dc` — но реально используется только `dc:creator`.

Структура одного `<item>`:

```xml
<item>
  <title><![CDATA[ Пашинян возглавит правящую партию Армении ]]></title>

  <!-- ⚠️ СОДЕРЖИТ UTM-ПАРАМЕТРЫ — обязательно убирать! -->
  <!-- ⚠️ robots.txt Disallow: *? — URLs с query params запрещены -->
  <link><![CDATA[
    https://russian.rt.com/ussr/news/1615700-pashinyan-vybory-parlament-armeniya
    ?utm_source=rss&utm_medium=rss&utm_campaign=RSS
  ]]></link>

  <!-- guid isPermaLink="true" — но содержит UTM, всё равно убирать -->
  <guid isPermaLink="true"><![CDATA[
    https://russian.rt.com/ussr/news/1615700-pashinyan-vybory-parlament-armeniya
    ?utm_source=rss&utm_medium=rss&utm_campaign=RSS
  ]]></guid>

  <!-- description = HTML-фрагмент с лидом + ссылкой "Читать далее" -->
  <description><![CDATA[
    Премьер-министр Армении Никол Пашинян возглавит правящую партию...
    <br/><a href="https://russian.rt.com/...?utm_source=rss...">Читать далее</a>
  ]]></description>

  <pubDate>Sat, 04 Apr 2026 14:33:39 +0300</pubDate>

  <!-- dc:creator всегда "RT на русском" — не журналист, игнорировать -->
  <dc:creator>RT на русском</dc:creator>

  <!-- ОТСУТСТВУЮТ: enclosure, media:content, content:encoded, author, category -->
</item>
```

### URL структура

```
https://russian.rt.com/{section}/news/{id}-{slug}
```
Секции: `ussr`, `world`, `sport`, `russia`, `business` и др.
ID + slug встроены в путь — без query params URL читабелен и уникален.

### Ключевые наблюдения

**⚠️ UTM в `<link>` и `<guid>` — двойная проблема:**
1. Для дедупликации нужен чистый canonical_url (без UTM)
2. robots.txt `Disallow: *?` запрещает **любой** URL с query-параметром
→ Стриппинг UTM — не просто хорошая практика, а **требование robots.txt**

```python
# НЕПРАВИЛЬНО — robots.txt запрещает этот URL:
url = "https://russian.rt.com/ussr/news/1615700-...?utm_source=rss&utm_medium=rss"

# ПРАВИЛЬНО:
canonical = "https://russian.rt.com/ussr/news/1615700-pashinyan-vybory-parlament-armeniya"
```

**`isPermaLink="true"` у guid, но guid содержит UTM.** Не доверять `isPermaLink` — всегда нормализовать.

**`<description>` — HTML-фрагмент, нужна очистка:**
- Содержит `<br/>` → заменить на пробел
- Содержит `<a href="...">Читать далее</a>` → при очистке HTML текст «Читать далее» останется
- Нужно после HTML-очистки убрать «Читать далее» через strip или regex

```python
from bs4 import BeautifulSoup

def clean_rt_description(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    # Удалить ссылку "Читать далее"
    for a in soup.find_all("a"):
        a.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return text.strip()
```

**`<dc:creator>` = «RT на русском» всегда** — название канала, не автор статьи.
Игнорировать, сохранять `author = null`.

**Нет `<category>`** — секция встроена в URL (`/world/`, `/ussr/`, `/sport/`).
Можно извлечь из URL: `url.split("/")[3]` → `"world"`, `"ussr"`, `"sport"`.

**Нет `<enclosure>` / `<media:content>`** — namespace `media:` объявлен но не используется.
Thumbnail в RSS нет совсем.

**`<content:encoded>`** — namespace объявлен, элемент не используется. Полный текст только со страницы.

---

## 5. robots.txt (исследование)

Источник: `https://russian.rt.com/robots.txt`

```
User-agent: *
Disallow: /inotv/print
Disallow: /search
Disallow: /c/
Disallow: /nbc/
Disallow: /nbc-stats/
Disallow: *?            # ВСЕ URLs с ЛЮБЫМ query-параметром
Disallow: /widget/
Disallow: /quiz/*
Allow: *css?            # исключение для CSS (они с ? но разрешены явно)
# НЕТ Crawl-delay
```

### Что это значит для нас

| Директива | Значение | Наше действие |
|-----------|---------|---------------|
| `Disallow: *?` | Любой URL с `?` запрещён | Убирать UTM **обязательно** перед любым запросом |
| Статьи `/world/news/...` (без `?`) | НЕ в Disallow | Ходить за полным текстом **можно** |
| **Нет Crawl-delay** | Нет ограничения | `crawl_delay = 1.0` |
| `/search`, `/widget/` | Запрещены | Нас не касается |

---

## 6. Извлечение секции из URL

Т.к. `<category>` в RSS отсутствует, секцию можно получить из URL:

```python
from urllib.parse import urlparse

def extract_rt_section(url: str) -> str | None:
    """
    "https://russian.rt.com/world/news/1615698-indiya..." → "world"
    "https://russian.rt.com/ussr/news/..."               → "ussr"
    "https://russian.rt.com/sport/news/..."              → "sport"
    """
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0] if parts else None
```

Известные секции: `world`, `ussr`, `russia`, `sport`, `business`, `science`.

---

## 7. Путь одной статьи: от RSS до базы

```
[RSS-фид RT]
  │
  ├── GET https://russian.rt.com/rss
  │   Проверить ETag/Last-Modified (предположительно — надо проверить)
  │
  ├── feedparser:
  │   title, link (с UTM!), guid (с UTM!), description (HTML), pubDate, dc:creator
  │
  └── Для каждого <item>:

      ├── canonical_url ← убрать UTM из entry.link
      │   (robots.txt Disallow: *? — это ОБЯЗАТЕЛЬНО, не опционально)
      ├── Дедупликация по canonical_url
      │
      ├── description → clean_rt_description() → BeautifulSoup → убрать "Читать далее"
      │   → snippet_lead
      │
      ├── section ← extract_rt_section(canonical_url)  # из URL, нет в RSS
      │
      ├── GET на canonical_url (за полным текстом, без UTM!)
      │   crawl_delay = 1.0 сек
      │
      ├── trafilatura.bare_extraction(html, favor_precision=True)
      │   Если < 200 символов → возможен paywall или JS-рендеринг
      │
      └── Сохранить
          news: (canonical_url, title, content, snippet_lead,
                 published_at, source_id, ...)
          extra JSONB: {
            "rt_section": "world",
            "thumbnail": null,   # нет в RSS
            "extraction_method": "trafilatura_precision",
          }
```

---

## 8. Расписание опроса

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| `crawl_interval` | 30 мин | Активная новостная лента |
| `crawl_delay` | 1.0 сек | Нет Crawl-delay в robots.txt |
| `priority` | `medium` | Международная повестка, не оперативное агентство |

---

## 9. Итоговый конфиг для таблицы sources

```python
{
    "name": "RT на русском",
    "type": "rss",
    "url": "https://russian.rt.com/rss",
    "config": {
        "feed_url": "https://russian.rt.com/rss",
        "strip_utm": True,              # UTM в link/guid — убирать ОБЯЗАТЕЛЬНО
        "utm_params": ["utm_source", "utm_medium", "utm_campaign"],
        "description_has_html": True,  # <br/> и <a>Читать далее</a>
        "author_from_dc_creator": True, # "RT на русском" — не журналист, но сохраняем
        "fetch_full_text": True,
        "stop_early_on_known": True,
        "section_from_url": True,      # category нет в RSS, берём из URL
    },
    "crawl_interval": 30,
    "crawl_delay": 1.0,
    "trust_score": 0.70,
    "reliability": "B",
    "priority": "periodic",
    "default_info_type": "daily",
    "default_content_type": "news",
    "legal_status": "restricted",
    "is_active": True,
}
```

**Примечание по trust_score:** RT — государственное СМИ с известной редакционной позицией.
Trust score 0.70 (Tier 3) отражает необходимость критической оценки контента.
Полезен для anti-confirmation bias (contrarian retrieval) в RAG-пайплайне.

---

## 10. Открытые вопросы

- [x] Проверить: поддерживает ли RSS ETag/Last-Modified → **НЕТ**, оба отсутствуют
- [x] Проверить: сколько items в фиде → **50 items**, 73,401 байт
- [x] Проверить: статический HTML или JS-рендеринг → **статический HTML** (200 OK, BS4 работает)
- [x] Проверить: есть ли paywall → **нет**, весь контент открыт
- [x] Уточнить: все ли секции в одном фиде → **да**, все 6 секций в одном RSS

## 11. Результаты тестирования

**Проверено:** апрель 2026, `test_rt.py`

### RSS-фид

| Параметр | Значение |
|----------|----------|
| Items в фиде | 50 |
| Размер | 73,401 байт |
| ETag | **НЕТ** |
| Last-Modified | **НЕТ** |
| Кэширование | Невозможно — полный GET каждый раз |

### Распределение по секциям (выборка)

| Секция | Items |
|--------|-------|
| /world/ | 19 |
| /sport/ | 9 |
| /russia/ | 7 |
| /nopolitics/ | 7 |
| /ussr/ | 6 |
| /business/ | 2 |

Все секции в одном фиде — отдельные RSS по секциям не нужны.

### Извлечение текста

**Критическая находка**: trafilatura с `favor_precision=True` берёт только блок `.article__summary` (лид, ~200–450 символов) и пропускает `.article__text` (основной текст).

**Решение**: BS4-fallback по CSS-классам всегда выигрывает:

```python
soup = BeautifulSoup(html, "html.parser")
parts = []
for cls in ("article__summary", "article__text"):
    block = soup.find(class_=cls)
    if block:
        for tag in block.find_all(["script", "style", "figure"]):
            tag.decompose()
        parts.append(block.get_text(separator="\n", strip=True))
text = "\n\n".join(parts)
```

В тесте: trafilatura → 446 симв., BS4 → 695 симв. (метод: `bs4_article_blocks`).

RT-новости короткие по природе (агентский стиль, 500–1500 символов) — это норма, не paywall.

### Теги статьи

Доступны в HTML в блоке `.article__tags-trends` — набор ссылок-тегов:

```python
tags_block = soup.find(class_="article__tags-trends")
tags = [a.get_text(strip=True) for a in tags_block.find_all("a")]
# → ['Венгрия', 'Виктор Орбан', 'Газ', 'ЕС', 'Европа', 'Роберт Фицо', ...]
```

Теги богаче, чем секция из URL — полезны для тематической индексации в Слое 2.
Сохранять в `extra JSONB` как `"tags": [...]`.

### Качество и paywall

- Paywall: **нет** — весь контент открыт
- HTML рендерится статически — Playwright **не нужен**
- Качество extraction: `ok` (BS4 по CSS-классам надёжнее trafilatura для RT)

### Итоговый конфиг для реального коллектора

```python
# Приоритет извлечения: BS4 по CSS > trafilatura
# Всегда проверять оба метода, брать более длинный
extraction_config = {
    "primary": "bs4_css_classes",
    "css_blocks": ["article__summary", "article__text"],
    "tags_block": "article__tags-trends",
    "fallback": "trafilatura_recall",
}
```

---

## 12. Итоговые правила для коллектора

```text
1. Забрать RSS по URL https://russian.rt.com/rss
2. Для URL статьи обязательно удалять UTM-параметры из link/guid
3. description использовать как HTML-лид для snippet_lead
4. За полным текстом ходить на HTML-страницу статьи
5. Для extraction сначала пробовать BS4 по article__summary/article__text, потом trafilatura
6. dc:creator сохранять как author канала, так как персональные авторы не указаны
7. В metadata сохранять section из URL, tags и extraction_method
8. Источник использовать как дополнительный международный и контрарный поток
```

---

## 13. Краткая оценка пригодности для MVP

| Критерий | Оценка |
|----------|--------|
| Техническая простота | `средняя` |
| Юридический риск | `средний` |
| Качество данных | `среднее` |
| Нагрузка на сайт | `средняя` |
| Польза для MVP | `взять` |

Итоговый вывод:
- `Берём в MVP` как дополнительный международный источник, но не как источник максимального доверия
