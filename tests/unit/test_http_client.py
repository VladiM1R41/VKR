from datetime import datetime, timedelta, timezone

import httpx
import pytest

from jarvis.ingestion.network import http_client as network_http


class _FakeAsyncClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    async def get(self, url: str, headers: dict[str, str] | None = None):
        self.calls.append((url, headers))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeCharsetMatch:
    def __init__(self, *, encoding: str | None, percent_coherence: float) -> None:
        self.encoding = encoding
        self.percent_coherence = percent_coherence


class _FakeCharsetResults:
    def __init__(self, match: object | None) -> None:
        self._match = match

    def best(self):
        return self._match


@pytest.mark.asyncio
async def test_fetch_with_retry_retries_on_429_and_respects_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []
    request = httpx.Request("GET", "https://example.com/feed.xml")
    client = _FakeAsyncClient(
        [
            httpx.Response(429, headers={"Retry-After": "2"}, request=request),
            httpx.Response(200, content=b"<rss />", request=request),
        ]
    )

    monkeypatch.setattr(network_http.asyncio, "sleep", _capture_sleep(sleep_calls))

    response = await network_http.fetch_with_retry(client, "https://example.com/feed.xml")

    assert response.status_code == 200
    assert sleep_calls == [2.0]
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_fetch_with_retry_retries_on_request_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []
    request = httpx.Request("GET", "https://example.com/article")
    client = _FakeAsyncClient(
        [
            httpx.ReadTimeout("timed out", request=request),
            httpx.Response(200, content=b"<html></html>", request=request),
        ]
    )

    monkeypatch.setattr(network_http.asyncio, "sleep", _capture_sleep(sleep_calls))

    response = await network_http.fetch_with_retry(client, "https://example.com/article")

    assert response.status_code == 200
    assert sleep_calls == [2.0]
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_fetch_with_retry_does_not_retry_non_retryable_404(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep_calls: list[float] = []
    request = httpx.Request("GET", "https://example.com/missing")
    client = _FakeAsyncClient(
        [httpx.Response(404, content=b"missing", request=request)]
    )

    monkeypatch.setattr(network_http.asyncio, "sleep", _capture_sleep(sleep_calls))

    response = await network_http.fetch_with_retry(client, "https://example.com/missing")

    assert response.status_code == 404
    assert sleep_calls == []
    assert len(client.calls) == 1


def test_decode_response_text_prefers_high_confidence_charset_normalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_bytes = bytes([207, 240, 232, 226, 229, 242, 32, 236, 232, 240])
    response = httpx.Response(200, content=raw_bytes, headers={"content-type": "text/html"})
    expected = raw_bytes.decode("cp1251")

    monkeypatch.setattr(
        network_http,
        "from_bytes",
        lambda payload: _FakeCharsetResults(_FakeCharsetMatch(encoding="cp1251", percent_coherence=92.0)),
    )

    decoded = network_http.decode_response_text(response)

    assert decoded == expected


def test_decode_response_text_falls_back_to_utf8_replace_on_unknown_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx.Response(
        200,
        content=b"\xff\xfeinvalid",
        headers={"content-type": "text/html; charset=x-broken"},
    )

    monkeypatch.setattr(network_http, "from_bytes", lambda payload: _FakeCharsetResults(None))

    decoded = network_http.decode_response_text(response)

    assert "\ufffd" in decoded


def test_parse_retry_after_http_date_uses_future_delta() -> None:
    retry_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    delay = network_http._parse_retry_after_seconds(retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT"))

    assert delay is not None
    assert 0.0 <= delay <= 6.0


def _capture_sleep(store: list[float]):
    async def _sleep(seconds: float) -> None:
        store.append(seconds)

    return _sleep
