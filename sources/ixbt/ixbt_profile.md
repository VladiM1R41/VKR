# Профиль источника: iXBT.com

> Составлено на основе исследования: robots.txt, условия цитирования, живой RSS-фид.
> Дата последней проверки: `2026-04-04`
> Исследовательский скрипт: [test_ixbt.py](/c:/code/diplom/sources/ixbt/test_ixbt.py)

---

## 1. Зачем этот источник

iXBT.com — авторитетный российский технический ресурс с 2002 года. Освещает: hardware,
AI/ML, смартфоны, космос, гаджеты, игры, периферия, электроника. **Единственный технический
источник** в наборе (все остальные — политика/общество).

Что даёт «Джарвису»:
- Покрытие технической тематики (hardware, AI, tech-новости)
- Anti-bubble: балансирует политический контент других источников
- **Полный текст в description** — нулевая нагрузка на сайт
- Реальные псевдонимы авторов

---

## 2. Юридический статус

### Владелец

**ООО «Аспект Исследования и Публикации»** — российское юридическое лицо.

### Условия цитирования

**Прямая цитата:** «Цитирование материалов сайта iXBT.com допускается **без предварительного
согласия** в информационных, **учебных и научных целях** в соответствии с действующим
законодательством РФ.»

ВКР = учебные/научные цели → прямо разрешено.

**Ограничение:** «Для регулярного использования значительного объёма новостей (более 70%
ленты) требуется предварительное согласование.»
→ Мы берём 100% ленты, но для ВКР (не публикация, не коммерция) — академическое цитирование.

### Для ВКР

✅ Допустимо:
- Читать RSS → full-text из description → RAG (ВКР = учебные/научные цели)
- Обязательно: указывать автора + ссылку на ixbt.com
- Не более 30% текста одного материала при цитировании в тексте ВКР (для RAG-контекста — ok)

❌ Нельзя:
- Использовать фотографии и иллюстрации без согласия
- Коммерческое использование без согласования

**Нормализованное значение для БД: `legal_status = "public_rss"`**.

---

## 3. Тип источника и доступ

| Параметр | Значение |
|----------|----------|
| Тип | RSS |
| RSS URL | `https://www.ixbt.com/export/news.rss` |
| **Полный текст в RSS** | **ДА — `<description>` содержит полный HTML** |
| Нужен HTTP-запрос к статье | **НЕТ** |
| Аутентификация | Не нужна |

---

## 4. Что реально отдаёт RSS (исследование живого фида)

**Проверено:** апрель 2026

Структура одного `<item>`:

```xml
<item>
  <!-- guid = link (isPermaLink="true") -->
  <guid isPermaLink="true">https://www.ixbt.com/news/2026/04/04/1000-titan-army-u275m.html</guid>
  <title>Киберспортивный монитор с частотой свыше 1000 Гц. Titan Army готовит к выпуску U275M</title>
  <link>https://www.ixbt.com/news/2026/04/04/1000-titan-army-u275m.html</link>

  <!-- description — ПОЛНЫЙ HTML-ТЕКСТ статьи -->
  <description><![CDATA[
    <p>Компания Titan Army готовит к выпуску монитор U275M...</p>
    <a href="..."><figure><img src="..."/></figure></a>
    Фото&nbsp;X (Titan Army)
    <p>Но даже при родном разрешении 1440p...</p>
  ]]></description>

  <!-- author — email + псевдоним в скобках -->
  <author>mpak@ixbt.com (MPAK)</author>

  <!-- category — ВСЕГДА ПУСТОЙ -->
  <category/>

  <pubDate>Sat, 04 Apr 2026 20:41:00 +0300</pubDate>
</item>
```

### Ключевые наблюдения

**✅ Полный текст в `<description>`:**
feedparser декодирует CDATA → HTML-строка. Нужна BS4-очистка.
Структура HTML внутри description:

```html
<p>Обычный параграф текста...</p>
<p>...с <a href="ixbt.com/news/...">внутренними ссылками</a>...</p>

<!-- Изображения — ВЫРЕЗАТЬ (нам нельзя использовать иллюстрации) -->
<a href="ixbt.com/img/...large.jpg"><figure><img src="ixbt.com/img/.../780x...jpg"/></figure></a>
Фото&nbsp;NASA   ← текстовая подпись после figure (отдельный текстовый узел)

<p>Продолжение текста...</p>
```

**HTML-сущности:** `&nbsp;`, `&mdash;`, `&laquo;`, `&raquo;` — feedparser декодирует часть, BS4 остальное.

**✅ author — email + псевдоним:**
Формат: `mpak@ixbt.com (MPAK)`. Извлекать псевдоним из скобок:

```python
import re
def extract_author(raw: str) -> str | None:
    raw = (raw or "").strip()
    m = re.search(r'\(([^)]+)\)', raw)
    if m:
        return m.group(1)          # "MPAK", "Jin"
    return raw.split("@")[0] if "@" in raw else (raw or None)
```

**⚠️ `<category/>` — всегда пустой:**
iXBT не заполняет категории в RSS → `categories = []`.

**Нет `<enclosure>` — thumbnail из первого `<img>`:**

```python
def extract_thumbnail(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    img = soup.find("img")
    return img.get("src") if img else None
```

**URL структура:**
```
https://www.ixbt.com/news/{YYYY}/{MM}/{DD}/{slug}.html
```

**⚠️ Виджет «Смотрите также» прямо в тексте:**
iXBT встраивает блок похожих статей прямо в HTML description — между параграфами:
```html
<a href="...?utm_campaign=seealso"><figure><img/></figure></a>
<a href="...?utm_campaign=seealso">Заголовок похожей статьи</a>
```
Метка `utm_campaign=seealso` — надёжный признак. Удалять ДО остальной очистки:
```python
for a in soup.find_all("a", href=True):
    if "seealso" in a.get("href", ""):
        a.decompose()
```

**Подписи к фото — вырезать из текста:**
После каждого `<figure>` идёт текстовый узел `Фото ASRock через Guru3D` или `Создано Grok`.
При очистке: удалить `<figure>` + `<a>` вокруг них → подпись убирается фильтрацией строк,
начинающихся с `("фото", "создано", "photo", ...)`.

---

## 5. Парсинг description

```python
def parse_ixbt_content(html: str) -> tuple[str, str | None]:
    """
    Извлечь (text, thumbnail) из description iXBT.
    Thumbnail — первый <img> в HTML.
    Text — plain text без изображений.
    """
    if not html:
        return "", None
    soup = BeautifulSoup(html, "html.parser")

    # Thumbnail из первого <img>
    img = soup.find("img")
    thumbnail = img.get("src") if img else None

    # Удалить все <figure> и содержащие их <a> (иллюстрации)
    for fig in soup.find_all("figure"):
        parent = fig.parent
        if parent and parent.name == "a":
            parent.decompose()
        else:
            fig.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Убрать строки-подписи "Фото NASA", "Создано Grok" — остатки после удаления figure
    lines = [
        line for line in text.split("\n")
        if line.strip() and not line.strip().startswith(("Фото", "Создано", "Photo"))
    ]
    return "\n".join(lines), thumbnail
```

---

## 6. robots.txt (исследование)

Статьи `/news/2026/04/04/slug.html` — разрешены (не попадают ни под один Disallow).

Ключевые ограничения для нас:

| Директива | Значение |
|-----------|---------|
| `Disallow: /?` | Query params запрещены → URL без `?` |
| `Disallow: /news/*.php` | Только старые .php-новости |
| `Disallow: /news/archive/` | Архивы — запрещены |
| **`/news/YYYY/MM/DD/slug.html`** | **РАЗРЕШЁН** |

**Нет Crawl-delay** → `crawl_delay = 1.0`.

`Googlebot-News` явно разрешён для `/news/2025/`, `/news/2026/` и т.д. Наш бот под `User-agent: *`.

---

## 7. Путь одной статьи: от RSS до базы

```
[RSS-фид iXBT] https://www.ixbt.com/export/news.rss
  │
  ├── GET RSS (проверить ETag/Last-Modified)
  │
  ├── feedparser:
  │   title, link (URL), guid (=link),
  │   description (HTML, полный текст!),
  │   author (email+псевдоним → extract_author()),
  │   pubDate
  │
  └── Для каждого <item>:
      ├── canonical_url ← из link (нормализация)
      ├── author ← extract_author("mpak@ixbt.com (MPAK)") → "MPAK"
      ├── content, thumbnail ← parse_ixbt_content(description)
      ├── snippet_lead ← первый абзац из content
      │
      └── Сохранить
          news: (canonical_url, title, content, snippet_lead,
                 published_at, author, source_id, ...)
          extra JSONB: {
            "thumbnail": "https://www.ixbt.com/img/...",
          }
```

**Нет HTTP-запросов к статьям → нет нагрузки, нет блокировок.**

---

## 8. Расписание опроса

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| `crawl_interval` | 30 мин | Активная лента (десятки новостей в день) |
| `crawl_delay` | 1.0 сек | Нет Crawl-delay в robots.txt |
| `priority` | `medium` | Технический источник, специализированная аудитория |

---

## 9. Итоговый конфиг для таблицы sources

```python
{
    "name": "iXBT.com",
    "type": "rss",
    "url": "https://www.ixbt.com/export/news.rss",
    "config": {
        "feed_url": "https://www.ixbt.com/export/news.rss",
        "full_text_in_rss": True,           # description содержит полный HTML-текст
        "fetch_full_text": False,            # HTTP-запросы к статьям НЕ нужны
        "description_has_html": True,        # CDATA с HTML → BS4 очистка
        "has_author": True,                  # author = псевдоним из email
        "author_format": "email_pseudonym",  # "mpak@ixbt.com (MPAK)" → "MPAK"
        "thumbnail_from_content_img": True,  # первый <img> в description
        "strip_utm": False,                  # UTM нет в ссылках
        "categories_empty": True,            # <category/> всегда пустой
    },
    "crawl_interval": 30,
    "crawl_delay": 1.0,
    "trust_score": 0.80,
    "reliability": "B",
    "priority": "periodic",
    "default_info_type": "daily",
    "default_content_type": "news",
    "legal_status": "public_rss",
    "is_active": True,
}
```

---

## 10. Открытые вопросы

- [x] Поддерживает ли RSS ETag/Last-Modified → **НЕТ**, оба отсутствуют
- [x] Сколько items в фиде → **10 items** (маленький фид!)
- [x] description всегда содержит полный текст → **100% (10/10)**
- [x] Thumbnail доступен → **100% (10/10)**, URL формат: `ixbt.com/img//x780/n1/news/...`
- [x] Виджет «Смотрите также» → подтверждён, удаляется по `utm_campaign=seealso`

## 11. Результаты тестирования

**Проверено:** апрель 2026, `test_ixbt.py`

### RSS-фид

| Параметр | Значение |
|----------|----------|
| Items в фиде | **10** — очень маленький фид |
| Размер | 29,418 байт |
| ETag | **НЕТ** |
| Last-Modified | **НЕТ** |
| Кэширование | Невозможно — полный GET каждый раз |

**Внимание: всего 10 items** — iXBT держит в RSS только последние 10 новостей.
При интервале опроса 30 минут это нормально (за 30 мин публикуется < 10 новостей).
При более редком опросе — риск пропустить публикации.

### Полный текст в description

- 100% статей (10/10) имеют полный текст в `<description>`
- Длины текстов: мин 617, макс 1712, **средняя ~988 символов**
- Технические статьи длиннее политических (RT ~695, Life.ru ~496)

### Авторы

Псевдонимы из `email (псевдоним)`:
- `MPAK` — основной автор hardware-новостей
- `Jin` — научные/космические темы

### Виджет «Смотрите также»

Между параграфами iXBT встраивает ссылки на похожие статьи с `utm_campaign=seealso`.
Без обработки попадают в текст как случайные заголовки.
**Решение**: удалять `<a href="...seealso...">` до очистки HTML — работает надёжно.

### Thumbnail

URL из первого `<img>` в description: `https://www.ixbt.com/img//x780/n1/news/...jpg`
(двойной `//` — баг iXBT, но URL рабочий). Все 10/10 статей имеют thumbnail.

---

## 12. Итоговые правила для коллектора

```text
1. Забрать RSS по URL https://www.ixbt.com/export/news.rss
2. Использовать link/guid как URL статьи — они совпадают
3. За полным текстом на HTML-страницу не ходить: description уже содержит полный HTML-текст
4. Из description извлекать text + thumbnail через BS4
5. До очистки удалять seealso-блоки по признаку utm_campaign=seealso
6. Author извлекать из формата email (Псевдоним), сохраняя псевдоним
7. В metadata сохранять thumbnail, extraction_method, cleaned_author
8. Источник считать техническим новостным RSS с низкой нагрузкой на хост
```

---

## 13. Краткая оценка пригодности для MVP

| Критерий | Оценка |
|----------|--------|
| Техническая простота | `высокая` |
| Юридический риск | `низкий` |
| Качество данных | `высокое` |
| Нагрузка на сайт | `низкая` |
| Польза для MVP | `взять` |

Итоговый вывод:
- `Берём в MVP` как сильный технический источник с почти идеальным RSS для первого слоя
