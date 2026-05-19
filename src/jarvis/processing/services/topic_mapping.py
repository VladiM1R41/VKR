"""Topic mapping utilities for Layer 2.

Два уровня классификации:
1. Rule-based mapping из категорий источника (быстро, объяснимо)
2. Zero-shot NLI fallback если категорий нет (медленнее, но универсально)
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TopicMatch:
    """One resolved topic with a confidence score."""

    name: str
    confidence: float


_TOPIC_RULES: dict[str, tuple[str, ...]] = {
    "Экономика": ("экономика", "economy", "эконом", "макроэкономика"),
    "Финансы": ("финансы", "финансов", "банки", "банк", "денежно-кредитная политика", "ставка"),
    "Политика": ("политика", "власть", "госдума", "правительство"),
    "Международные отношения": ("международ", "мир", "дипломатия", "санкции"),
    "Технологии": ("технологии", "tech", "it", "ai", "ии", "разработка", "гаджеты"),
    "Бизнес": ("бизнес", "компании", "рынки", "корпорации", "предпринимательство"),
    "Общество": ("общество", "социум", "социальное", "образование", "здоровье"),
    "Безопасность": ("безопасность", "армия", "спецоперация", "теракт", "чп"),
    "Энергетика": ("энергетика", "нефть", "газ", "электроэнергия"),
    "Транспорт": ("транспорт", "авиация", "логистика", "поезд", "авто"),
    "Право": ("право", "суд", "закон", "регулирование"),
    "Наука": ("наука", "исследования", "открытие", "учёные", "ученые"),
}


def normalize_category_label(value: str) -> str:
    """Normalize source category labels before lookup."""

    collapsed = " ".join(value.strip().lower().split())
    collapsed = collapsed.replace("ё", "е")
    collapsed = re.sub(r"[^\w\s-]+", " ", collapsed)
    return " ".join(collapsed.split())


def map_source_categories(categories: list[str] | None) -> list[TopicMatch]:
    """Map source-specific categories to unified project topics.

    Уровень 1: быстрое rule-based сопоставление.
    """

    if not categories:
        return []

    matches: list[TopicMatch] = []
    seen: set[str] = set()

    for category in categories:
        normalized = normalize_category_label(category)
        if not normalized:
            continue
        for topic_name, markers in _TOPIC_RULES.items():
            if topic_name in seen:
                continue
            if normalized == normalize_category_label(topic_name) or any(marker in normalized for marker in markers):
                matches.append(TopicMatch(name=topic_name, confidence=0.95))
                seen.add(topic_name)
                break

    return matches


def classify_topics_lexical(*, title: str, body: str = "", max_topics: int = 3) -> list[TopicMatch]:
    """Resolve topics from title/body markers without loading the zero-shot model."""

    text = normalize_category_label(f"{title} {body[:1200]}")
    if not text:
        return []
    tokens = set(text.split())

    scored: list[TopicMatch] = []
    for topic_name, markers in _TOPIC_RULES.items():
        hits = 0
        for marker in markers:
            normalized_marker = normalize_category_label(marker)
            if not normalized_marker:
                continue
            if " " in normalized_marker or len(normalized_marker) > 3:
                matched = normalized_marker in text
            else:
                matched = normalized_marker in tokens
            if matched:
                hits += 1
        if hits:
            confidence = min(0.9, 0.62 + hits * 0.08)
            scored.append(TopicMatch(name=topic_name, confidence=round(confidence, 4)))

    scored.sort(key=lambda match: match.confidence, reverse=True)
    return scored[:max_topics]


def _merge_topic_matches(*groups: list[TopicMatch], max_topics: int = 3) -> list[TopicMatch]:
    by_name: dict[str, TopicMatch] = {}
    for group in groups:
        for match in group:
            current = by_name.get(match.name)
            if current is None or match.confidence > current.confidence:
                by_name[match.name] = match

    matches = sorted(by_name.values(), key=lambda match: match.confidence, reverse=True)
    return matches[:max_topics]


def resolve_topics(
    *,
    source_categories: list[str] | None,
    title: str,
    body: str = "",
) -> list[TopicMatch]:
    """Resolve topics для статьи: rule-based → zero-shot fallback.

    Алгоритм:
    1. Попробовать map_source_categories (быстро, confidence=0.95)
    2. Если ничего не нашли → zero-shot NLI (медленнее, confidence~0.4-0.8)
    3. Объединить, убрать дубликаты

    Args:
        source_categories: Категории из RSS-фида (news.extra.categories).
        title: Заголовок статьи.
        body: Текст статьи.

    Returns:
        Список уникальных TopicMatch, отсортированный по confidence.
    """
    rule_matches = map_source_categories(source_categories)
    if rule_matches:
        return rule_matches

    lexical_matches = classify_topics_lexical(title=title, body=body)
    if lexical_matches:
        return lexical_matches

    text_for_classification = title
    if body:
        text_for_classification += ". " + body[:300]

    from jarvis.processing.nlp.topics import classify_topics_zero_shot

    zero_shot_matches = classify_topics_zero_shot(text_for_classification)

    if zero_shot_matches:
        logger.info(
            "zero-shot topics resolved for article: %s",
            [m.name for m in zero_shot_matches],
        )

    return zero_shot_matches
