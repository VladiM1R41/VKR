"""Context assembler для Слоя 5 — сбор, группировка и обрезка контекста.

Архитектура (по FINAL_LAYER_5_GUIDE.md, раздел 10.4):
  1. Взять shortlist от Слоя 4 (или результаты Слоя 3).
  2. Дополнить полными текстами из БД (news.content, news.snippet_lead, source.name).
  3. Сгруппировать документы по event_cluster_id (digest / analytical mode).
  4. Внутри группы выбрать representative + supporting fragments.
  5. Отсортировать по приоритету: personalized score → trust → freshness → urgency.
  6. Обрезать контекст по token budget.
  7. Сформировать список DocumentContext для prompt builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from jarvis.db.models import News, Source
from jarvis.db.session import SyncSessionLocal
from jarvis.generation.services.prompt_builder import (
    DocumentContext,
    estimate_token_count,
)

_URGENCY_RANK: dict[str, int] = {
    "critical": 3,
    "high": 2,
    "normal": 1,
    "low": 0,
}


def _primary_score(item: "NewsWithContext") -> float:
    return item.personalized_score if item.personalized_score is not None else item.score


def _priority_key(item: "NewsWithContext") -> tuple[float, float, str, int, float]:
    """Order context by relevance first, then trust and freshness signals."""
    return (
        _primary_score(item),
        float(item.trust_score or 0.0),
        item.published_at_str or "",
        _URGENCY_RANK.get((item.urgency or "normal").lower(), 1),
        item.score,
    )


# ───────────────────────────────────────────────────────────
# Data-классы
# ───────────────────────────────────────────────────────────

@dataclass
class NewsWithContext:
    """Новость, дополненная полным контекстом из БД."""
    news_id: int
    source_id: int
    source_name: str
    title: str
    content: str | None          # полный текст (может быть None)
    snippet_lead: str | None     # первые 2-3 предложения
    score: float
    rerank_score: float | None
    personalized_score: float | None
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    published_at_str: str = ""
    trust_score: float = 0.5
    content_grade: int = 6
    information_type: str = "daily"
    urgency: str = "normal"
    event_cluster_id: int | None = None


# ───────────────────────────────────────────────────────────
# Загрузка полных текстов из БД
# ───────────────────────────────────────────────────────────

def fetch_news_full(session, news_ids: list[int]) -> dict[int, News]:
    """Загрузить полные записи News по списку news_id.

    Returns:
        dict[news_id, News] — только найденные записи.
    """
    stmt = select(News).where(News.id.in_(news_ids))
    rows = session.scalars(stmt).all()
    return {row.id: row for row in rows}


def fetch_sources_map(session, source_ids: set[int]) -> dict[int, Source]:
    """Загрузить маппинг source_id → Source.

    Returns:
        dict[source_id, Source]
    """
    if not source_ids:
        return {}
    stmt = select(Source).where(Source.id.in_(source_ids))
    rows = session.scalars(stmt).all()
    return {row.id: row for row in rows}


def enrich_with_db_data(
    news_ids: list[int],
    source_ids: set[int],
    titles: dict[int, str],
    snippets: dict[int, str],
    scores: dict[int, float],
    rerank_scores: dict[int, float | None],
    personalized_scores: dict[int, float | None],
    topics_map: dict[int, list[str]],
    entities_map: dict[int, list[str]],
    published_map: dict[int, str],
    trust_map: dict[int, float],
    grade_map: dict[int, int],
    info_type_map: dict[int, str],
    urgency_map: dict[int, str],
    cluster_map: dict[int, int | None],
) -> list[NewsWithContext]:
    """Собрать NewsWithContext из разрозненных данных.

    Этот helper принимает «плоские» данные из API-слоя (Pydantic-моделей
    SearchResult / PersonalizedResult) и дополняет их полными текстами
    из БД.
    """
    with SyncSessionLocal() as session:
        news_map = fetch_news_full(session, news_ids)
        db_source_ids = {int(news.source_id) for news in news_map.values()}
        sources_map = fetch_sources_map(session, source_ids | db_source_ids)

    results: list[NewsWithContext] = []
    for nid in news_ids:
        news = news_map.get(nid)
        source = sources_map.get(int(news.source_id)) if news else None
        source_name = ""
        if news:
            source_name = str(source.name) if source else ""
            # Если в БД есть более полный контент — используем его
            content = news.content if news.content else None
            snippet = news.snippet_lead if news.snippet_lead else None
        else:
            content = None
            snippet = None

        # Fallback: если нет content, берём snippet
        body = content or snippet or snippets.get(nid, "")

        results.append(NewsWithContext(
            news_id=nid,
            source_id=news.source_id if news else 0,
            source_name=source_name or "",
            title=titles.get(nid, ""),
            content=body,
            snippet_lead=snippet,
            score=scores.get(nid, 0.0),
            rerank_score=rerank_scores.get(nid),
            personalized_score=personalized_scores.get(nid),
            topics=topics_map.get(nid, []),
            entities=entities_map.get(nid, []),
            published_at_str=published_map.get(nid, ""),
            trust_score=float(source.trust_score) if source else trust_map.get(nid, 0.5),
            content_grade=int(news.content_grade) if news else grade_map.get(nid, 6),
            information_type=str(news.information_type) if news else info_type_map.get(nid, "daily"),
            urgency=str(news.urgency) if news else urgency_map.get(nid, "normal"),
            event_cluster_id=getattr(news, "event_cluster_id", None) if news else cluster_map.get(nid),
        ))
    return results


# ───────────────────────────────────────────────────────────
# Группировка по event_cluster_id (digest mode)
# ───────────────────────────────────────────────────────────

@dataclass
class EventCluster:
    """Группа документов, относящихся к одному событию."""
    cluster_id: int | None  # None = «одиночные» новости без кластера
    representatives: list[NewsWithContext] = field(default_factory=list)
    supporting: list[NewsWithContext] = field(default_factory=list)

    @property
    def priority_score(self) -> float:
        """Приоритет кластера = max personalized_score среди документов."""
        all_docs = self.representatives + self.supporting
        scores = [_primary_score(d) for d in all_docs if d.personalized_score is not None or d.score]
        return max(scores, default=0.0)


def group_by_event_clusters(
    news_items: list[NewsWithContext],
) -> list[EventCluster]:
    """Сгруппировать документы по event_cluster_id.

    Внутри каждого кластера:
      - representative = документ с наивысшим score из самого надёжного источника
      - supporting = остальные документы (до 2 штук)

    Кластеры без event_cluster_id (None) трактуются как «одиночные» новости.
    """
    groups: dict[int | None, list[NewsWithContext]] = {}
    for item in news_items:
        cid = item.event_cluster_id
        groups.setdefault(cid, []).append(item)

    clusters: list[EventCluster] = []
    for cid, items in groups.items():
        items_sorted = sorted(items, key=_priority_key, reverse=True)
        cluster = EventCluster(cluster_id=cid)
        cluster.representatives = [items_sorted[0]] if items_sorted else []
        # Берём до 2 supporting fragments
        cluster.supporting = items_sorted[1:3] if len(items_sorted) > 1 else []
        clusters.append(cluster)

    # Сортируем кластеры по лучшему документу внутри кластера.
    clusters.sort(
        key=lambda c: max(
            (_priority_key(item) for item in c.representatives + c.supporting),
            default=(0.0, 0.0, "", 0, 0.0),
        ),
        reverse=True,
    )
    return clusters


# ───────────────────────────────────────────────────────────
# Обрезка по token budget
# ───────────────────────────────────────────────────────────

def trim_documents_to_budget(
    documents: list[DocumentContext],
    max_context_tokens: int,
    system_tokens: int,
    user_tokens: int,
) -> list[DocumentContext]:
    """Обрезать список документов, чтобы уложиться в token budget.

    Алгоритм:
      1. Считаем budget = max_context_tokens - system_tokens - user_tokens.
      2. Последовательно добавляем документы, пока не исчерпаем budget.
      3. Если последний документ не влезает целиком — пробуем сократить content.

    Args:
        documents: список документов (уже отсортированных по приоритету).
        max_context_tokens: общий лимит входных токенов (из settings).
        system_tokens: оценка токенов системного промпта.
        user_tokens: оценка токенов пользовательского блока.

    Returns:
        Список документов, укладывающийся в budget.
    """
    budget = max_context_tokens - system_tokens - user_tokens
    if budget <= 0:
        return []

    result: list[DocumentContext] = []
    used_tokens = 0

    for doc in documents:
        doc_tokens = estimate_token_count(doc.content)
        # Также учитываем оверлей: source_name, date, title
        overhead_tokens = estimate_token_count(
            f"source: {doc.source_name} date: {doc.published_at} title: {doc.title}"
        )
        total_tokens = doc_tokens + overhead_tokens

        if used_tokens + total_tokens <= budget:
            result.append(doc)
            used_tokens += total_tokens
        else:
            # Пробуем сократить content до remaining budget
            remaining = budget - used_tokens - overhead_tokens
            if remaining > 0:
                max_chars = max(1, remaining * 2 - 3)
                trimmed_content = doc.content[:max_chars].rstrip() + "..."
                result.append(
                    DocumentContext(
                        index=doc.index,
                        news_id=doc.news_id,
                        source_name=doc.source_name,
                        published_at=doc.published_at,
                        title=doc.title,
                        content=trimmed_content,
                    )
                )
            break

    return result


# ───────────────────────────────────────────────────────────
# Высокоуровневый интерфейс: AssembledContext
# ───────────────────────────────────────────────────────────

@dataclass
class AssembledContext:
    """Результат сборки контекста — готов к передаче в prompt builder."""
    documents: list[DocumentContext]
    total_tokens: int
    max_tokens: int
    n_sources: int
    n_clusters: int
    trimmed: bool  # True если документы были обрезаны


def assemble_context_for_chat(
    news_items: list[NewsWithContext],
    max_input_tokens: int = 20000,
    system_prompt: str = "",
    user_query: str = "",
) -> AssembledContext:
    """Собрать контекст для chat-режима (factual/capability/intent).

    Без группировки по кластерам — просто отсортированные по score документы,
    обрезанные по token budget.
    """
    sorted_items = sorted(news_items, key=_priority_key, reverse=True)

    documents = [
        DocumentContext(
            index=i + 1,
            news_id=item.news_id,
            source_name=item.source_name,
            published_at=item.published_at_str,
            title=item.title,
            content=item.content or "(нет текста)",
        )
        for i, item in enumerate(sorted_items)
    ]

    system_tokens = estimate_token_count(system_prompt)
    user_tokens = estimate_token_count(user_query)
    trimmed_docs = trim_documents_to_budget(documents, max_input_tokens, system_tokens, user_tokens)

    total_tokens = system_tokens + user_tokens + sum(
        estimate_token_count(d.content) + estimate_token_count(
            f"source: {d.source_name} title: {d.title}"
        )
        for d in trimmed_docs
    )

    return AssembledContext(
        documents=trimmed_docs,
        total_tokens=total_tokens,
        max_tokens=max_input_tokens,
        n_sources=len(set(d.source_name for d in trimmed_docs)),
        n_clusters=0,
        trimmed=len(trimmed_docs) < len(documents),
    )


def assemble_context_for_digest(
    news_items: list[NewsWithContext],
    max_input_tokens: int = 20000,
    system_prompt: str = "",
) -> AssembledContext:
    """Собрать контекст для digest-режима.

    Группирует документы по event_cluster_id, выбирает representative
    и supporting fragments, обрезает по token budget.
    """
    clusters = group_by_event_clusters(news_items)

    # Разворачиваем кластеры в плоский список (representative + supporting)
    flat_items: list[NewsWithContext] = []
    for cluster in clusters:
        flat_items.extend(cluster.representatives)
        flat_items.extend(cluster.supporting)

    documents = [
        DocumentContext(
            index=i + 1,
            news_id=item.news_id,
            source_name=item.source_name,
            published_at=item.published_at_str,
            title=item.title,
            content=item.content or "(нет текста)",
        )
        for i, item in enumerate(flat_items)
    ]

    system_tokens = estimate_token_count(system_prompt)
    trimmed_docs = trim_documents_to_budget(documents, max_input_tokens, system_tokens, user_tokens=0)

    total_tokens = system_tokens + sum(
        estimate_token_count(d.content) + estimate_token_count(
            f"source: {d.source_name} title: {d.title}"
        )
        for d in trimmed_docs
    )

    return AssembledContext(
        documents=trimmed_docs,
        total_tokens=total_tokens,
        max_tokens=max_input_tokens,
        n_sources=len(set(d.source_name for d in trimmed_docs)),
        n_clusters=len(clusters),
        trimmed=len(trimmed_docs) < len(flat_items),
    )
