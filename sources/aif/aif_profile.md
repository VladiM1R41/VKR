# Профиль источника: Аргументы и Факты

> Составлено на основе исследования: живых RSS-фидов, правил использования материалов и `robots.txt`.
> Дата последней проверки: `2026-04-07`
> Исследовательский скрипт: [test_aif.py](/c:/code/diplom/sources/aif/test_aif.py)
> Режимы запуска:
> `python sources/aif/test_aif.py`
> `python sources/aif/test_aif.py articles`

---

## 1. Зачем этот источник

`Аргументы и факты` полезен для `Jarvis` как крупный российский массовый источник с сильным покрытием:
- политика
- общество
- происшествия
- экономика
- Москва и регионы
- аналитические и объясняющие статьи

Что дает проекту:
- одновременно закрывает и `daily news`, и более длинный формат `articles`
- RSS выглядит очень богатым по метаданным
- усиливает массовую общественно-политическую повестку и объясняющий контент

Рекомендуемая роль в проекте:
- `MVP`

---

## 2. Юридический статус

Источник правил:
- приписка на странице: `Все права защищены. Копирование и использование полных материалов запрещено, частичное цитирование возможно только при условии гиперссылки на сайт www.aif.ru.`

Ключевые выводы:
- полное копирование и использование материалов запрещено
- частичное цитирование допускается только с гиперссылкой на `aif.ru`
- источник нужно считать юридически строгим

Для ВКР:
- допустимо использовать RSS и HTML для внутреннего анализа, индексации и retrieval
- в пользовательском продукте надо опираться на пересказ и ссылку
- нельзя рассчитывать на свободное полнотекстовое воспроизведение

Нормализованное значение для БД:
- `legal_status = "restricted"`

---

## 3. Тип источника и доступ

| Параметр | Значение |
|----------|----------|
| Тип | `rss` |
| Основной URL | `https://aif.ru/` |
| RSS новости | `https://aif.ru/rss/news.php` |
| RSS статьи | `https://aif.ru/rss/articles.php` |
| Протокол | `pull` |
| Аутентификация | не нужна |
| Полный текст в RSS | `да`, через `yandex:full-text` и `turbo:content` |
| Нужен HTTP-запрос к статье | `необязательно` |
| Нужен Playwright | `скорее всего нет` |
| Paywall | `не видно по RSS, проверить тестом` |

Предварительный вывод:
- это один из самых богатых по структуре RSS-источников
- можно рассматривать как почти готовый full-text source даже без HTML-fetch
- для `MVP` логично начать с новостного RSS, а `articles` держать как отдельный поток того же источника

---

## 4. Что реально отдает источник

### 4.1. Структура RSS

По предоставленному RSS `news.php`:

```xml
<item turbo="true">
  <title><![CDATA[ ... ]]></title>
  <link>https://aif.ru/...</link>
  <description><![CDATA[ ... ]]></description>
  <pdalink>https://aif.ru/...</pdalink>
  <category>Политика</category>
  <author>Игорь Бердичевский</author>
  <pubDate>Tue, 07 Apr 2026 15:51:49 +0300</pubDate>
  <yandex:full-text><![CDATA[ <p>...</p> ]]></yandex:full-text>
  <enclosure url="https://aif-s3.aif.ru/images/...webp" type="image/jpeg"/>
  <yandex:related type="infinity">...</yandex:related>
  <turbo:content><![CDATA[ <header>...</header><p>...</p> ]]></turbo:content>
</item>
```

### 4.2. Ключевые наблюдения

- есть два разных RSS-потока:
  - `news.php` для новостей
  - `articles.php` для более длинных материалов
- `author` есть уже в RSS
- `category` есть
- `enclosure` есть и выглядит полезным thumbnail
- есть `yandex:full-text` с чистым полным текстом в HTML-разметке
- есть `turbo:content`, который содержит более богатую структуру статьи:
  - подзаголовки
  - inline-изображения
  - подписи к изображениям
  - иногда slider-галереи с несколькими изображениями
- `turbo:content` нельзя брать "как есть", потому что в нем есть:
  - `header` с дублирующим заголовком и главной картинкой
  - виджеты `ExtRetellWidget`, `Ext24smiWidget`, `ExtSvkNativeWidget`
  - рекламные placeholder-блоки `figure[data-turbo-ad-id]`
  - injected related-feed блоки `div[data-block="feed"]`
  - вложенные `div[data-block="slider"]`, которые нельзя включать в plain text
- после структурного парсинга `turbo:content` выглядит как лучший источник rich-content, а `yandex:full-text` остается хорошим fallback и cross-check
- `guid` отсутствует
- есть `pdalink`, который в примерах совпадает с основным URL
- есть `lastBuildDate`
- есть `ttl = 24`
- есть `yandex:related` со связанными материалами
- есть `yandex:theme_tags`, например `story-5189`, что может быть полезно для event/story grouping

### 4.3. Поля, которые брать в коллектор

| Поле Jarvis | Откуда брать |
|-------------|--------------|
| `url` | `entry.link` |
| `canonical_url` | нормализованный `entry.link` |
| `title` | `entry.title` |
| `content` | структурно очищенный `turbo:content` |
| `snippet_lead` | `entry.summary` / `description` |
| `published_at` | `entry.published_parsed` |
| `author` | `entry.author` |
| `tags` | `category` |
| `thumbnail` | `enclosure.url` |
| `raw_content` | raw `yandex:full-text` / `turbo:content` |
| `related_links` | `yandex:related` |
| `story_tag` | `yandex:theme_tags` |
| `inline_images` | извлекать из body-`figure` в `turbo:content` |

---

## 5. robots.txt и техническая вежливость

Источник:
- `https://aif.ru/robots.txt`

Ключевые директивы:

```txt
User-agent: *
Allow: /comments
Allow: /authors/
Allow: *?erid=*
Disallow: /search
Disallow: /media
Disallow: /images
Disallow: /docs
Clean-param: email
Clean-param: giclickid
Clean-param: subscription_id

User-agent: Bingbot
Disallow: /
```

Что это значит для нас:

| Директива | Значение | Действие коллектора |
|-----------|----------|---------------------|
| страницы статей явно не запрещены | article URL выглядят разрешенными | HTML-fetch допустим как fallback |
| `Clean-param` есть | query-параметры нужно чистить | canonicalization обязательна |
| `Bingbot: Disallow: /` | ограничение только для Bingbot | для нашего сценария не критично |
| `Crawl-delay` отсутствует | жесткого лимита нет | стартово использовать `crawl_delay = 1.0` |

Итог:
- с точки зрения `robots.txt` источник выглядит удобным
- при этом HTML-fetch, вероятно, вообще не нужен на первом этапе, потому что полный текст уже есть в RSS

---

## 6. Извлечение полного текста

Нужно ли идти на страницу:
- `скорее нет`, если `turbo:content` и `yandex:full-text` стабильны

Рекомендуемая стратегия:
1. брать `description` как `snippet_lead`
2. парсить `turbo:content` не как строку, а как структуру блоков статьи
3. из `turbo:content` сохранять только полезные блоки:
   - `h2/h3/h4` как секционные заголовки
   - `p` как абзацы
   - body-`figure` как inline-изображения
4. из `turbo:content` удалять:
   - `header`
   - widget-теги
   - ad-placeholders
   - injected related-feed блоки
   - вложенные slider-галереи из текста абзаца
5. `yandex:full-text` держать как fallback и средство валидации текста
6. ходить на HTML-страницу только если оба RSS-представления плохие или неполные

Что ожидаем:
- это один из самых удобных источников для full-text ingestion
- длина текста не должна быть главным критерием выбора между `yandex:full-text` и `turbo:content`
- "сырой" `turbo:content` грязный, но структурно очищенный `turbo:content` может быть лучшим представлением статьи
- `yandex:full-text` полезен как более чистый текстовый fallback
- HTML-fetch может быть запасным, а не обязательным шагом

Что пока не подтверждено:
- насколько стабилен структурный формат `turbo:content` на большой выборке
- у всех ли inline-изображений одинаково предсказуемая разметка
- нужен ли HTML fallback в реальности

---

## 7. Дедупликация и каноникализация

Предварительные правила:
- использовать `link` как основной URL статьи
- `pdalink` можно игнорировать, если он совпадает с основным URL
- чистить query-параметры по `robots.txt`

Итог:
- `canonical_url` строится из `entry.link`
- `title_hash` использовать как второй уровень дедупликации
- `lastBuildDate` можно использовать как cheap-signal обновления фида
- `yandex:related` и `yandex:theme_tags` можно использовать как дополнительные сигналы story clustering

---

## 8. Расписание опроса

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| `crawl_interval` | `30` минут | несмотря на `ttl = 24`, поток новостей активный |
| `crawl_delay` | `1.0` сек | в robots.txt нет `Crawl-delay` |
| `priority` | `periodic` | крупный, полезный и богатый по данным поток |

Классификация для Слоя 1:
- `news.php`:
  - `default_info_type = "daily"`
  - `default_content_type = "news"`
- `articles.php`:
  - `default_info_type = "analytical"`
  - `default_content_type = "article"`

---

## 9. Мониторинг здоровья

Что может сломаться:
- `yandex:full-text` может пропасть или стать неполным
- `turbo:content` может содержать рекламные и виджетные вставки
- `turbo:content` может содержать `slider`-галереи внутри абзацев, из-за чего в plain text попадают повторы caption вроде `© АиФ / ...`
- `author` или `category` могут исчезнуть у части записей
- структура `articles.php` и `news.php` может начать различаться сильнее
- основной `<link>` нельзя слепо брать из абстрактного RSS-парсера, если тот смешивает его со связанными ссылками из `yandex:related`

Минимальные health-check сигналы:
- RSS отвечает `200`
- в фиде есть записи
- даты парсятся
- `author` есть хотя бы у большинства записей
- `category` есть хотя бы у большинства записей
- `yandex:full-text` есть хотя бы у большинства записей

Нормальные значения:
- пока не зафиксированы, нужно подтвердить живым тестом:
- `items в фиде`: `300`
- `ETag`: не поддерживается
- `Last-Modified`: не поддерживается
- `author coverage`: `295/300`
- `category coverage`: `300/300`
- `thumbnail coverage`: `300/300`
- `yandex_full_text coverage`: `300/300`
- `turbo_content coverage`: `300/300`
- `related_links coverage`: `147/300`
- `theme_tags coverage`: `56/300`
- `lastBuildDate`: есть

---

## 10. Итоговые правила для коллектора

```text
1. Для MVP начать с RSS https://aif.ru/rss/news.php
2. link использовать как основной URL статьи
3. canonical_url строить через очистку query-параметров
4. snippet_lead брать из description
5. author брать из RSS
6. category использовать как tag / rubric
7. thumbnail брать из enclosure.url
8. `turbo:content` парсить структурно, а не превращать сразу в одну грязную строку
9. в основной content собирать только полезные блоки `h2/h3/h4` и `p` в исходном порядке
10. body-`figure` использовать как inline-изображения статьи, исключая дубликат thumbnail
11. `yandex:full-text` хранить как fallback-представление текста и сигнал контроля качества
12. HTML-fetch не делать по умолчанию, только как запасной режим
13. lastBuildDate можно использовать как cheap-signal обновления фида
14. related links из `yandex:related` сохранять в extra JSONB как полезный сигнал связанных материалов
15. `yandex:theme_tags` сохранять как story/event tag
16. articles.php подключать как отдельный source того же бренда, а не смешивать с news.php
```

---

## 11. Итоговый конфиг для таблицы `sources`

```python
{
    "name": "AIF News",
    "type": "rss",
    "url": "https://aif.ru/rss/news.php",
    "engine": "auto",
    "delivery_mode": "pull",
    "config": {
        "feed_url": "https://aif.ru/rss/news.php",
        "etag": False,
        "modified": False,
        "fetch_full_text": False,
        "full_text_method": "rss_turbo_structured",
        "description_has_html": True,
        "has_author": True,
        "has_category": True,
        "has_enclosure": True,
        "has_yandex_full_text": True,
        "has_turbo_content": True,
        "turbo_contains_inline_images": True,
        "has_related_links": True,
        "has_theme_tags": True,
        "has_last_build_date": True
    },
    "crawl_interval": 30,
    "crawl_delay": 1.0,
    "trust_score": 0.82,
    "reliability": "B",
    "priority": "periodic",
    "default_info_type": "daily",
    "default_content_type": "news",
    "legal_status": "restricted",
    "is_active": True
}
```

### Отдельный source для `AIF Articles`

```python
{
    "name": "AIF Articles",
    "type": "rss",
    "url": "https://aif.ru/rss/articles.php",
    "engine": "auto",
    "delivery_mode": "pull",
    "config": {
        "feed_url": "https://aif.ru/rss/articles.php",
        "etag": False,
        "modified": False,
        "fetch_full_text": False,
        "full_text_method": "rss_turbo_structured",
        "description_has_html": True,
        "has_author": True,
        "has_category": True,
        "has_enclosure": True,
        "has_yandex_full_text": True,
        "has_turbo_content": True,
        "turbo_contains_inline_images": True,
        "has_related_links": True,
        "has_theme_tags": True,
        "has_last_build_date": True
    },
    "crawl_interval": 30,
    "crawl_delay": 1.0,
    "trust_score": 0.82,
    "reliability": "B",
    "priority": "periodic",
    "default_info_type": "analytical",
    "default_content_type": "article",
    "legal_status": "restricted",
    "is_active": True
}
```

---

## 12. Результаты тестирования

Дата теста:
- живым скриптом подтверждено `2026-04-07`

Что уже подтверждено:
- RSS доступен
- в фиде `300` записей
- `ETag` нет
- `Last-Modified` нет
- `author` есть у `295/300`
- `category` есть у `300/300`
- `enclosure` есть у `300/300`
- есть `yandex:full-text`
- есть `turbo:content`
- `guid` нет
- есть `pdalink`
- есть `yandex:related`
- есть `yandex:theme_tags`
- есть `lastBuildDate`
- есть `ttl`
- `yandex:full-text` есть у `300/300`
- `turbo:content` есть у `300/300`
- `yandex:related` есть у `147/300`
- `yandex:theme_tags` есть у `56/300`
- основной `link` нужно брать строго из прямого тега `<item><link>`, а не из связанных ссылок
- для rich-content предпочтителен структурно очищенный `turbo:content`
- `yandex:full-text` стоит сохранять как текстовый fallback и контрольный источник

Что подтверждено живым тестом для `articles.php`:
- RSS доступен
- в фиде `72` записей
- `ETag` нет
- `Last-Modified` нет
- `author` есть у `72/72`
- `category` есть у `72/72`
- `enclosure` есть у `70/72`
- `yandex:full-text` есть у `72/72`
- `turbo:content` есть у `72/72`
- `yandex:related` есть у `13/72`
- `yandex:theme_tags` есть у `11/72`
- `inline_images` находятся у `19/72` после очистки `slider`-галерей из plain text
- для богатых материалов `turbo:content` хорошо сохраняет подзаголовки и inline-изображения
- `inline_images` сохраняются как объекты вида `{type, src, caption}`, а не как голые URL
- в `articles.php` встречаются slider-галереи, их надо исключать из plain text, но сохранять как изображения

Что нужно проверить живым скриптом:
- насколько стабилен структурный формат `turbo:content`
- насколько часто inline-изображения реально полезны для downstream-задач
- нужен ли вообще HTML-fetch
- корректно ли наш XML-парсер извлекает namespaced поля и основной `link`

| Проверка | Статус |
|----------|--------|
| RSS доступен | `да` |
| Items в фиде | `300` |
| ETag | `нет` |
| Last-Modified | `нет` |
| Author в RSS | `да` |
| Category в RSS | `да` |
| Enclosure в RSS | `да` |
| yandex:full-text | `да` |
| turbo:content | `да` |
| yandex:related | `да` |
| yandex:theme_tags | `да` |
| HTML fetch нужен | `скорее нет` |

---

## 13. Открытые вопросы

- [ ] Сколько записей реально в фиде
- [ ] Нужно ли вообще делать HTML-fetch
- [ ] Насколько стабилен структурный парсер `turbo:content` на большой выборке
- [ ] Во всех ли статьях body-изображения корректно отделяются от hero-изображения
- [ ] Насколько полезны inline-изображения из `turbo:content` для downstream-задач
- [ ] Стоит ли подключать `articles.php` отдельным source уже на этапе MVP
- [ ] Как лучше использовать `yandex:related` и `theme_tags` в будущем story clustering

---

## 14. Краткая оценка пригодности для MVP

| Критерий | Оценка |
|----------|--------|
| Техническая простота | `очень высокая` |
| Юридический риск | `средний` |
| Качество данных | `очень высокое` |
| Нагрузка на сайт | `низкая` |
| Польза для MVP | `взять` |

Итоговый вывод:
- `очень сильный кандидат для MVP`
- это один из самых богатых и удобных RSS-источников среди всех уже исследованных
- особенно ценны `author`, `category`, `thumbnail`, два варианта full text, `related links` и `theme_tags`
