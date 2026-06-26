"""Deterministic watcher for Hermes `so` MCP sessions.

This script is intentionally not an MCP server and not an LLM. It performs one
bounded polling pass by default: capture active tmux sessions, let the MCP
backend emit `needs_input` lifecycle signals, and reap dead or expired
sessions. Run it from cron with the default one-shot mode, or pass `--loop`.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hermes.config import load_config  # noqa: E402
from hermes.mcp_hermes_orchestrator import poll_so_sessions  # noqa: E402


def poll_once(
    *, repo_root: str, ttl_seconds: int | None = None
) -> dict[str, Any]:
    config = load_config(repo_root)
    return poll_so_sessions(config, ttl_seconds=ttl_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Poll Hermes so sessions and emit deterministic state signals."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=os.environ.get("Z_HARNESS_REPO", "."),
        help="Repo root used to load Hermes config.",
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=None,
        help="Override session TTL for this polling pass.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously instead of one polling pass.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="Sleep interval for --loop mode.",
    )
    args = parser.parse_args(argv)

    while True:
        result = poll_once(
            repo_root=args.repo_root,
            ttl_seconds=args.ttl_seconds,
        )
        print(json.dumps(result, sort_keys=True))
        if not args.loop:
            return 0
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
