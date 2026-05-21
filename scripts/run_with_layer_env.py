#!/usr/bin/env python
"""Run a command with the local Layer 1-5 runtime environment.

Examples:
    python scripts/run_with_layer_env.py -- python -m jarvis.ingestion.cli.enrich_source --source BFM.ru --limit 5
    python scripts/run_with_layer_env.py -- celery -A jarvis.ingestion.tasks.celery_app worker -Q processing_queue
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "GIT_HTTP_PROXY",
    "GIT_HTTPS_PROXY",
)


def build_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env["PROCESSING_EMBEDDING_BACKEND"] = "flagembedding"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    for key in PROXY_VARS:
        env.pop(key, None)
    return env


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a command with flagembedding, offline model cache, and clean proxy env."
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command after --")
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("provide a command after --")

    return subprocess.run(command, env=build_env(), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
