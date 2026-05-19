"""Chunking helpers for Layer 2."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class PreparedChunk:
    """Chunk ready for embedding and indexing."""

    zone: str
    text: str
    lemma_text: str = ""
    chunk_index: int = 0
    total_chunks: int = 0
    char_start: int = 0
    char_end: int = 0
    token_count: int = 0


@dataclass(frozen=True, slots=True)
class _SentenceSpan:
    text: str
    char_start: int
    char_end: int
    token_count: int


def _token_count(text: str) -> int:
    return len([token for token in re.split(r"\s+", text.strip()) if token])


def _sentence_spans(text: str) -> list[_SentenceSpan]:
    """Split text with Razdel while preserving offsets in the original body."""

    from razdel import sentenize

    spans: list[_SentenceSpan] = []
    for sentence in sentenize(text):
        raw_text = text[sentence.start:sentence.stop]
        sentence_text = raw_text.strip()
        if not sentence_text:
            continue

        leading_ws = len(raw_text) - len(raw_text.lstrip())
        trailing_ws = len(raw_text) - len(raw_text.rstrip())
        char_start = sentence.start + leading_ws
        char_end = sentence.stop - trailing_ws
        spans.append(
            _SentenceSpan(
                text=sentence_text,
                char_start=char_start,
                char_end=char_end,
                token_count=_token_count(sentence_text),
            )
        )
    return spans


def _lemmatize_chunk(text: str) -> str:
    from jarvis.processing.ir.lemmatize import lemmatize_text

    lemma = lemmatize_text(text).strip()
    return lemma or text.lower()


def _chunk_body_text(text: str, max_tokens: int = 420, overlap_tokens: int = 70) -> list[tuple[str, int, int]]:
    sentences = _sentence_spans(text)
    if not sentences:
        stripped = text.strip()
        return [(stripped, 0, len(stripped))] if stripped else []

    windows: list[tuple[str, int, int]] = []
    start_idx = 0
    while start_idx < len(sentences):
        current_tokens = 0
        end_idx = start_idx
        while end_idx < len(sentences):
            sentence = sentences[end_idx]
            if end_idx > start_idx and current_tokens + sentence.token_count > max_tokens:
                break
            current_tokens += sentence.token_count
            end_idx += 1

        char_start = sentences[start_idx].char_start
        char_end = sentences[end_idx - 1].char_end
        windows.append((text[char_start:char_end].strip(), char_start, char_end))

        if end_idx >= len(sentences):
            break

        overlap_count = 0
        next_start_idx = end_idx
        while next_start_idx > start_idx and overlap_count < overlap_tokens:
            next_start_idx -= 1
            overlap_count += sentences[next_start_idx].token_count
        start_idx = max(start_idx + 1, next_start_idx)

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

    ``lemma_body`` is kept for backwards-compatible callers. Body chunks are
    lemmatized independently so each ``lemma_text`` describes exactly the same
    text span as the chunk itself.
    """

    chunks: list[PreparedChunk] = []
    title_text = title.strip()
    if title_text:
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

    _ = lemma_body
    body_text = (body or "").strip() or (fallback_body or "").strip()
    if body_text:
        for chunk_text, char_start, char_end in _chunk_body_text(body_text):
            chunks.append(
                PreparedChunk(
                    zone="body",
                    text=chunk_text,
                    lemma_text=_lemmatize_chunk(chunk_text),
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
