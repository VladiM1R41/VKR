"""Chunking helpers for Layer 2."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class PreparedChunk:
    """Chunk ready for embedding and indexing.

    Attributes:
        zone: 'title' или 'body' — для зонного поиска.
        text: Оригинальный текст чанка (для embedding и display).
        lemma_text: Лемматизированный текст (для Qdrant FTS / BM25).
        chunk_index: Порядковый номер чанка в статье.
        total_chunks: Всего чанков в статье.
        char_start: Позиция начала в исходном тексте.
        char_end: Позиция конца в исходном тексте.
        token_count: Приблизительное число токенов.
    """

    zone: str
    text: str
    lemma_text: str = ""
    chunk_index: int = 0
    total_chunks: int = 0
    char_start: int = 0
    char_end: int = 0
    token_count: int = 0


def _token_count(text: str) -> int:
    return len([token for token in re.split(r"\s+", text.strip()) if token])


def _split_sentences(text: str) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    return [part.strip() for part in parts if part.strip()]


def _chunk_body_text(text: str, max_tokens: int = 420, overlap_sentences: int = 1) -> list[tuple[str, int, int]]:
    sentences = _split_sentences(text)
    if not sentences:
        stripped = text.strip()
        return [(stripped, 0, len(stripped))] if stripped else []

    windows: list[tuple[str, int, int]] = []
    start_idx = 0
    while start_idx < len(sentences):
        current: list[str] = []
        current_tokens = 0
        end_idx = start_idx
        while end_idx < len(sentences):
            sentence = sentences[end_idx]
            sentence_tokens = _token_count(sentence)
            if current and current_tokens + sentence_tokens > max_tokens:
                break
            current.append(sentence)
            current_tokens += sentence_tokens
            end_idx += 1

        chunk_text = " ".join(current).strip()
        char_start = text.find(current[0]) if current else 0
        char_end = char_start + len(chunk_text) if chunk_text else char_start
        windows.append((chunk_text, max(char_start, 0), max(char_end, 0)))

        if end_idx >= len(sentences):
            break
        start_idx = max(start_idx + 1, end_idx - overlap_sentences)

    return windows


def build_chunks(
    *,
    title: str,
    body: str | None,
    fallback_body: str | None = None,
    lemma_title: str = "",
    lemma_body: str = "",
) -> list[PreparedChunk]:
    """Build title/body chunks with graceful degradation.

    Args:
        title: Заголовок статьи (оригинал).
        body: Полный текст статьи (или None).
        fallback_body: snippet_lead как fallback, если body пуст.
        lemma_title: Лемматизированный заголовок (опционально).
        lemma_body: Лемматизированный текст статьи (опционально).

    Returns:
        Список PreparedChunk с lemma_text (если передан).
    """

    def _get_lemma_for_range(text_range_start: int, text_range_end: int, lemma_full: str, orig_full: str) -> str:
        """Приблизительно извлечь леммы для диапазона символов оригинала.

        Для простого MVP: если леммы есть — берём соответствующий срез.
        Если lemma_full пустой — возвращаем пустую строку.
        """
        if not lemma_full:
            return ""
        # MVP: пропорциональный срез (не идеально, но работает для большинства)
        if len(orig_full) == 0:
            return ""
        ratio_start = text_range_start / len(orig_full)
        ratio_end = text_range_end / len(orig_full)
        lemma_start = int(ratio_start * len(lemma_full))
        lemma_end = int(ratio_end * len(lemma_full))
        return lemma_full[max(0, lemma_start):min(len(lemma_full), lemma_end)].strip()

    chunks: list[PreparedChunk] = []
    title_text = title.strip()
    if title_text:
        # Для title лемма = весь lemma_title (он короткий)
        chunks.append(
            PreparedChunk(
                zone="title",
                text=title_text,
                lemma_text=lemma_title.strip() if lemma_title else title_text.lower(),
                chunk_index=0,
                total_chunks=0,
                char_start=0,
                char_end=len(title_text),
                token_count=_token_count(title_text),
            )
        )

    body_text = (body or "").strip() or (fallback_body or "").strip()
    # Определяем какой lemma_body использовать
    lemma_for_body = (lemma_body or "").strip()
    if not lemma_for_body and lemma_title:
        # Если lemma_body нет, но есть lemma_title — body леммы будут пустыми
        # (fallback: lower)
        lemma_for_body = ""

    if body_text:
        for chunk_text, char_start, char_end in _chunk_body_text(body_text):
            lemma_chunk = _get_lemma_for_range(char_start, char_end, lemma_for_body, body_text)
            if not lemma_chunk:
                # Fallback: просто lowercase
                lemma_chunk = chunk_text.lower()
            chunks.append(
                PreparedChunk(
                    zone="body",
                    text=chunk_text,
                    lemma_text=lemma_chunk,
                    chunk_index=0,
                    total_chunks=0,
                    char_start=char_start,
                    char_end=char_end,
                    token_count=_token_count(chunk_text),
                )
            )

    total_chunks = len(chunks)
    return [
        PreparedChunk(
            zone=chunk.zone,
            text=chunk.text,
            lemma_text=chunk.lemma_text,
            chunk_index=index,
            total_chunks=total_chunks,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            token_count=chunk.token_count,
        )
        for index, chunk in enumerate(chunks)
    ]

