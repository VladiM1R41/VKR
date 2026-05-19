"""Compare current RSS-first Layer 1 extraction with experimental candidates.

This script is read-only for the project and database. It is intended for Group E
source audits where the production path extracts full text from RSS payloads
instead of article HTML.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

from bs4 import BeautifulSoup
import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jarvis.ingestion.bootstrap.source_seed_data import SOURCE_SEED_DATA
from jarvis.ingestion.collectors.rss import RSSCollector
from jarvis.ingestion.extraction.source_specific_candidates import extract_aif_turbo_candidate


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare RSS current extraction with Group E candidate.")
    parser.add_argument("--source-key", default="aif_articles")
    parser.add_argument("--rss-url", default=None)
    parser.add_argument("--url", action="append", default=[], help="Filter RSS items by article URL. Repeatable.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--mode", choices=["shortest", "latest"], default="shortest")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--trust-env", action="store_true", help="Use environment proxies for httpx.")
    args = parser.parse_args()

    source = _build_source_stub(args.source_key)
    rss_url = args.rss_url or source.config.get("feed_url")
    if not rss_url:
        raise SystemExit("RSS URL is required.")

    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(follow_redirects=True, timeout=args.timeout, trust_env=args.trust_env) as client:
        rss_text = _fetch_text(client, rss_url)
        items = _select_items(rss_text, source, urls=args.url, limit=args.limit, mode=args.mode)
        results = []
        for index, article, item in items:
            html = _fetch_optional_text(client, article.url)
            candidate = _run_candidate(item=item, source=source, html=html, thumbnail_url=(article.extra or {}).get("thumbnail"))
            result = _compare_article(article=article, candidate=candidate)
            if out_dir is not None:
                _write_outputs(out_dir=out_dir, index=index, result=result)
            results.append(result)

    print(json.dumps({"source_key": args.source_key, "rss_url": rss_url, "out_dir": str(out_dir) if out_dir else None, "items": results}, ensure_ascii=False, indent=2))


def _build_source_stub(source_key: str) -> SimpleNamespace:
    for row in SOURCE_SEED_DATA:
        if row["config"]["source_key"] == source_key:
            return SimpleNamespace(
                id=row.get("id", 1),
                name=row["name"],
                url=row["url"],
                config=dict(row["config"]),
                default_info_type=row["default_info_type"],
                default_content_type=row["default_content_type"],
                crawl_delay=row["crawl_delay"],
            )
    raise SystemExit(f"Unknown source_key: {source_key}")


def _fetch_text(client: httpx.Client, url: str) -> str:
    response = client.get(url, headers={"User-Agent": "JarvisLayer1/0.1 (+research project; contact: local-dev)"})
    response.raise_for_status()
    return response.text


def _fetch_optional_text(client: httpx.Client, url: str) -> str | None:
    try:
        return _fetch_text(client, url)
    except httpx.HTTPError as exc:
        print(f"WARNING: failed to fetch article HTML {url}: {exc}", file=sys.stderr)
        return None


def _select_items(
    rss_text: str,
    source: SimpleNamespace,
    *,
    urls: list[str],
    limit: int,
    mode: str,
) -> list[tuple[int, Any, Any]]:
    soup = BeautifulSoup(rss_text, "xml")
    channel = soup.find("channel")
    if channel is None:
        raise SystemExit("RSS channel not found.")

    wanted_urls = set(urls)
    collector = RSSCollector(source, http_client=None)
    parsed: list[tuple[int, Any, Any]] = []
    for index, item in enumerate(channel.find_all("item", recursive=False), start=1):
        article = collector._parse_item(item)
        if article is None:
            continue
        if wanted_urls and article.url not in wanted_urls:
            continue
        parsed.append((index, article, item))

    if wanted_urls:
        return parsed
    if mode == "shortest":
        parsed.sort(key=lambda entry: len(entry[1].content or ""))
    return parsed[:limit]


def _run_candidate(*, item: Any, source: SimpleNamespace, html: str | None, thumbnail_url: str | None) -> Any:
    if source.config.get("source_key") == "aif_articles":
        return extract_aif_turbo_candidate(item=item, source=source, html_content=html, thumbnail_url=thumbnail_url)
    raise SystemExit(f"No RSS candidate for source_key={source.config.get('source_key')}")


def _compare_article(*, article: Any, candidate: Any) -> dict[str, Any]:
    current_content = article.content or ""
    candidate_content = candidate.content or ""
    candidate_extra = dict(article.extra or {})
    candidate_extra.update(candidate.extra or {})
    return {
        "url": article.url,
        "title": article.title,
        "current_content": current_content,
        "candidate_content": candidate_content,
        "current": _summarize(
            content=current_content,
            method=article.extraction_method,
            content_status=article.content_status,
            extra=article.extra or {},
        ),
        "candidate": _summarize(
            content=candidate_content,
            method=candidate.method,
            content_status=candidate.content_status,
            extra=candidate_extra,
            quality=candidate.quality,
        ),
        "delta": {
            "length_delta": len(candidate_content) - len(current_content),
            "method_changed": article.extraction_method != candidate.method,
            "status_changed": article.content_status != candidate.content_status,
        },
    }


def _summarize(
    *,
    content: str,
    method: str | None,
    content_status: str,
    extra: dict[str, Any],
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paragraphs = [line.strip() for line in content.splitlines() if line.strip()]
    return {
        "method": method,
        "content_status": content_status,
        "length": len(content),
        "paragraphs": len(paragraphs),
        "first_paragraph": paragraphs[0][:400] if paragraphs else None,
        "last_paragraph": paragraphs[-1][:400] if paragraphs else None,
        "extra_keys": sorted(extra.keys()),
        "quality": quality or {},
    }


def _write_outputs(*, out_dir: Path, index: int, result: dict[str, Any]) -> None:
    stem = f"{index:02d}"
    current_content = result.pop("current_content", "")
    candidate_content = result.pop("candidate_content", "")
    header = f"URL: {result['url']}\nTITLE: {result['title']}\n\n"
    (out_dir / f"{stem}_current.txt").write_text(header + current_content, encoding="utf-8")
    (out_dir / f"{stem}_candidate.txt").write_text(header + candidate_content, encoding="utf-8")


if __name__ == "__main__":
    main()
