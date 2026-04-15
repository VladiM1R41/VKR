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
    # Шаг 1: rule-based
    rule_matches = map_source_categories(source_categories)
    if rule_matches:
        return rule_matches

    # Шаг 2: zero-shot fallback
    # Берём title + первые 300 символов body для классификации
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

