"""URL normalization helpers for Layer 1."""

from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAM_NAMES = {
    "yclid",
    "ysclid",
    "gclid",
    "fbclid",
    "from",
    "fromrss",
    "fromtg",
}


def canonicalize_url(url: str, keep_params: list[str] | None = None) -> str:
    """Normalize a URL for exact deduplication."""
    if not url:
        return ""

    keep_params = keep_params or []
    parts = urlsplit(url.strip())

    scheme = (parts.scheme or "https").lower()
    hostname = (parts.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]

    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    filtered_params: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in keep_params:
            filtered_params.append((key, value))
            continue
        if lowered in TRACKING_PARAM_NAMES:
            continue
        if any(lowered.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES):
            continue
        filtered_params.append((key, value))

    query = urlencode(filtered_params, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def normalized_title_hash(title: str) -> str:
    """Return MD5(normalize(title)) as cheap duplicate/debug signal."""
    normalized = html.unescape(title or "")
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()

