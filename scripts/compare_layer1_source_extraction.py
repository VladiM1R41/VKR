"""Compare current Layer 1 extraction with experimental Group E candidates.

The script is read-only for the project and database. It fetches or reads the
same HTML pages, runs the current extraction cascade and the candidate extractor,
then prints a compact JSON report that can be reviewed before promoting code to
the production ingestion path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jarvis.ingestion.bootstrap.source_seed_data import SOURCE_SEED_DATA
from jarvis.ingestion.extraction.postprocess import apply_postprocess_rules, apply_pre_extraction_rules
from jarvis.ingestion.extraction.source_specific import extract_source_specific
from jarvis.ingestion.extraction.source_specific_candidates import (
    candidate_noise_markers,
    extract_candidate,
    starts_with_title,
)
from jarvis.ingestion.extraction.trafilatura_extractor import extract_with_precision, extract_with_recall


NOISE_MARKERS = (
    "Реклама",
    "Читайте также",
    "Подписаться",
    "Лента новостей",
    "Все новости",
    "Поделиться",
    "Комментарии",
    "Доступ к чату заблокирован",
    "Чтобы участвовать в дискуссии",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare current and candidate Layer 1 extraction.")
    parser.add_argument("--source-key", required=True, help="Source key from SOURCE_SEED_DATA, e.g. ria.")
    parser.add_argument("--url", action="append", default=[], help="Article URL to fetch. Repeat 3-5 times.")
    parser.add_argument("--html-file", action="append", default=[], help="Local HTML file to compare.")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Optional directory for full current/candidate text files.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    source = _build_source_stub(args.source_key)
    inputs = _load_inputs(urls=args.url, html_files=args.html_file, timeout=args.timeout)
    if not inputs:
        raise SystemExit("Provide at least one --url or --html-file.")

    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for index, (label, html) in enumerate(inputs, start=1):
        result = _compare_one(source=source, label=label, html=html)
        if out_dir is not None:
            _write_text_outputs(out_dir=out_dir, index=index, result=result)
        results.append(result)

    print(json.dumps({"source_key": args.source_key, "out_dir": str(out_dir) if out_dir else None, "items": results}, ensure_ascii=False, indent=2))


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
            )
    raise SystemExit(f"Unknown source_key: {source_key}")


def _load_inputs(*, urls: list[str], html_files: list[str], timeout: float) -> list[tuple[str, str]]:
    inputs: list[tuple[str, str]] = []

    for html_file in html_files:
        path = Path(html_file)
        inputs.append((str(path), path.read_text(encoding="utf-8")))

    if urls:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            for url in urls:
                try:
                    response = client.get(url, headers={"User-Agent": "JarvisLayer1/0.1 (+research project; contact: local-dev)"})
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    print(f"WARNING: failed to fetch {url}: {exc}", file=sys.stderr)
                    continue
                inputs.append((url, response.text))

    return inputs


def _compare_one(*, source: SimpleNamespace, label: str, html: str) -> dict[str, Any]:
    current = _run_current_cascade(html, source)
    candidate = extract_candidate(html, source)

    return {
        "input": label,
        "current_content": current["content"],
        "candidate_content": candidate.content if candidate else None,
        "current": _summarize_result(
            content=current["content"],
            method=current["method"],
            content_status=current["content_status"],
            title=None,
            extra=current.get("extra") or {},
            quality=current.get("quality") or {},
        ),
        "candidate": _summarize_result(
            content=candidate.content if candidate else None,
            method=candidate.method if candidate else None,
            content_status=candidate.content_status if candidate else "not_available",
            title=None,
            extra=candidate.extra if candidate else {},
            quality=candidate.quality if candidate else {},
        ),
        "candidate_delta": _build_delta(current, candidate),
    }


def _run_current_cascade(html: str, source: SimpleNamespace) -> dict[str, Any]:
    postprocess_rules = list((source.config or {}).get("postprocess_rules") or [])
    prepared_html = apply_pre_extraction_rules(html, postprocess_rules)

    source_specific = extract_source_specific(prepared_html, source)
    source_specific_content = source_specific.get("content") if source_specific else None
    source_specific_extra = source_specific.get("extra") if source_specific else {}

    if source_specific_content and len(source_specific_content) >= 200:
        content = source_specific_content
        method = "html_source_specific"
        status = "ok"
    else:
        content = extract_with_precision(prepared_html)
        method = "trafilatura_precision" if content else "failed_all_levels"
        status = "ok" if content else "extraction_failed"
        if content is None:
            recall = extract_with_recall(prepared_html)
            if recall:
                content = recall
                method = "trafilatura_recall"
                status = "partial"

    content, _ = apply_postprocess_rules(
        content=content,
        snippet_lead=None,
        rules=postprocess_rules,
    )

    return {
        "content": content,
        "method": method,
        "content_status": status,
        "extra": source_specific_extra,
        "quality": {
            "source_specific_returned": bool(source_specific_content),
            "source_specific_length": len(source_specific_content or ""),
        },
    }


def _summarize_result(
    *,
    content: str | None,
    method: str | None,
    content_status: str,
    title: str | None,
    extra: dict[str, Any],
    quality: dict[str, Any],
) -> dict[str, Any]:
    paragraphs = [line.strip() for line in (content or "").splitlines() if line.strip()]
    return {
        "method": method,
        "content_status": content_status,
        "length": len(content or ""),
        "paragraphs": len(paragraphs),
        "first_paragraph": paragraphs[0][:400] if paragraphs else None,
        "last_paragraph": paragraphs[-1][:400] if paragraphs else None,
        "noise_markers": _find_noise_markers(content),
        "candidate_noise_markers": candidate_noise_markers(content),
        "starts_with_title": starts_with_title(content, title),
        "extra_keys": sorted(extra.keys()),
        "quality": quality,
    }


def _build_delta(current: dict[str, Any], candidate) -> dict[str, Any]:
    current_content = current.get("content")
    candidate_content = candidate.content if candidate else None
    return {
        "length_delta": len(candidate_content or "") - len(current_content or ""),
        "candidate_has_less_noise": len(_find_noise_markers(candidate_content)) < len(_find_noise_markers(current_content)),
        "candidate_available": candidate is not None and bool(candidate_content),
        "current_method": current.get("method"),
        "candidate_method": candidate.method if candidate else None,
    }


def _write_text_outputs(*, out_dir: Path, index: int, result: dict[str, Any]) -> None:
    stem = f"{index:02d}"
    current_content = result.pop("current_content", None) or ""
    candidate_content = result.pop("candidate_content", None) or ""
    input_label = result.get("input") or ""

    (out_dir / f"{stem}_current.txt").write_text(
        f"INPUT: {input_label}\n\n{current_content}",
        encoding="utf-8",
    )
    (out_dir / f"{stem}_candidate.txt").write_text(
        f"INPUT: {input_label}\n\n{candidate_content}",
        encoding="utf-8",
    )


def _find_noise_markers(content: str | None) -> list[str]:
    if not content:
        return []
    lowered = content.lower()
    return [marker for marker in NOISE_MARKERS if marker.lower() in lowered]


if __name__ == "__main__":
    main()
