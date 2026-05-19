"""HTTP helpers for Layer 1 discovery and enrichment."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import inspect

from charset_normalizer import from_bytes
import httpx


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 2.0
DEFAULT_DECODE_ENCODING = "utf-8"
CHARSET_CONFIDENCE_THRESHOLD = 0.7


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> httpx.Response:
    """GET a URL with small bounded retries for transient failures."""
    last_exception: Exception | None = None
    last_response: httpx.Response | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.get(url, headers=headers)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            last_exception = exc
            if attempt >= max_attempts:
                raise
            await asyncio.sleep(_compute_backoff_delay(attempt, backoff_seconds))
            continue

        last_response = response
        if not _should_retry_status(response.status_code, attempt, max_attempts):
            return response

        await _close_response_quietly(response)
        retry_after = response.headers.get("Retry-After")
        await asyncio.sleep(_compute_retry_delay(retry_after, attempt, backoff_seconds))

    if last_response is not None:
        return last_response
    if last_exception is not None:
        raise last_exception
    raise RuntimeError(f"fetch_with_retry failed without response for {url}")


def decode_response_text(
    response: httpx.Response,
    *,
    default_encoding: str = DEFAULT_DECODE_ENCODING,
    confidence_threshold: float = CHARSET_CONFIDENCE_THRESHOLD,
) -> str:
    """Decode response bytes with a cautious fallback cascade.

    Cascade:
      1. httpx/declared encoding
      2. charset-normalizer when confidence is high enough
      3. utf-8 with replacement
    """
    raw_bytes = getattr(response, "content", None) or b""
    if not raw_bytes:
        return ""

    primary_encoding = getattr(response, "encoding", None)
    primary_text = _decode_with_encoding(raw_bytes, primary_encoding)

    detected_match = from_bytes(raw_bytes).best()
    if detected_match is not None:
        detected_encoding = getattr(detected_match, "encoding", None)
        confidence = _extract_confidence(detected_match)
        if (
            detected_encoding
            and confidence >= confidence_threshold
            and detected_encoding.lower() != (primary_encoding or "").lower()
        ):
            detected_text = _decode_with_encoding(raw_bytes, detected_encoding)
            if detected_text is not None:
                return detected_text

    if primary_text is not None:
        return primary_text

    return raw_bytes.decode(default_encoding, errors="replace")


def _should_retry_status(status_code: int, attempt: int, max_attempts: int) -> bool:
    if attempt >= max_attempts:
        return False
    return status_code in RETRYABLE_STATUS_CODES


def _compute_retry_delay(retry_after: str | None, attempt: int, backoff_seconds: float) -> float:
    parsed_retry_after = _parse_retry_after_seconds(retry_after)
    if parsed_retry_after is not None:
        return parsed_retry_after
    return _compute_backoff_delay(attempt, backoff_seconds)


def _compute_backoff_delay(attempt: int, backoff_seconds: float) -> float:
    return max(0.0, float(backoff_seconds) * (2 ** (attempt - 1)))


def _parse_retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None

    raw_value = value.strip()
    if not raw_value:
        return None

    try:
        return max(0.0, float(int(raw_value)))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)

    delay = (retry_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, delay)


def _extract_confidence(match: object) -> float:
    percent_coherence = getattr(match, "percent_coherence", None)
    if percent_coherence is not None:
        try:
            return float(percent_coherence) / 100.0
        except (TypeError, ValueError):
            pass

    coherence = getattr(match, "coherence", None)
    if coherence is not None:
        try:
            coherence_value = float(coherence)
        except (TypeError, ValueError):
            return 0.0
        return coherence_value if coherence_value <= 1.0 else coherence_value / 100.0

    return 0.0


def _decode_with_encoding(raw_bytes: bytes, encoding: str | None) -> str | None:
    if not encoding:
        return None
    try:
        return raw_bytes.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError):
        return None


async def _close_response_quietly(response: object) -> None:
    aclose = getattr(response, "aclose", None)
    if not callable(aclose):
        return

    result = aclose()
    if inspect.isawaitable(result):
        await result
