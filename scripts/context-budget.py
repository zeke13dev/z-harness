#!/usr/bin/env python3
"""
context-budget.py — Analyze z-harness telemetry for context utilization insights.

Usage:
    python3 scripts/context-budget.py <archive_dir> [--events <events.jsonl>]
    python3 scripts/context-budget.py --help

Reads events.jsonl and filesystem artifacts from a run archive directory.
Produces a Markdown analysis with metrics table and actionable recommendations.

Handles: empty event log, missing archive, very large event logs gracefully.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# Thresholds for warnings
MAX_ARTIFACT_BYTES = 5 * 1024  # 5KB — artifacts above this are flagged
HIGH_TOOL_CALL_DENSITY = 30     # tool calls per 100 events
REPEATED_SUBAGENT_THRESHOLD = 3  # dispatches to same subagent type
LARGE_EVENT_LOG_LINES = 1000    # warn when event log is large


def _format_size(n_bytes: int) -> str:
    if n_bytes >= 1024 * 1024:
        return f"{n_bytes / (1024 * 1024):.1f} MB"
    if n_bytes >= 1024:
        return f"{n_bytes / 1024:.0f} KB"
    return f"{n_bytes} B"


def _status_icon(ok: bool, warn: bool = False, critical: bool = False) -> str:
    if critical:
        return "🔴"
    if warn:
        return "⚠️"
    return "✅"


def analyze(run_dir: Path) -> str:
    """Analyze a run archive directory and return Markdown output."""
    lines: list[str] = []
    run_name = run_dir.name

    lines.append(f"## Context Budget — {run_name}")
    lines.append("")
    lines.append("| Metric | Value | Status |")
    lines.append("|--------|-------|--------|")

    warnings: list[str] = []
    recommendations: list[str] = []

    # --- 1. Events.jsonl analysis ---
    events_path = run_dir / "events.jsonl"
    events: list[dict] = []
    event_kinds: Counter = Counter()
    tool_calls = 0
    subagent_dispatches: Counter = Counter()
    total_events = 0

    if events_path.is_file():
        try:
            with events_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                        events.append(ev)
                        total_events += 1
                        kind = ev.get("kind", "")
                        event_kinds[kind] += 1

                        # Count tool calls (events that represent tool invocations)
                        if kind in ("implement_start", "review_start", "precheck_start",
                                     "subagent_dispatch"):
                            tool_calls += 1
                        if kind == "subagent_dispatch":
                            st = ev.get("subagent_type", "unknown")
                            subagent_dispatches[st] += 1
                    except json.JSONDecodeError:
                        continue
        except OSError:
            lines.append("| Events log | unreadable | 🔴 |")
            warnings.append("events.jsonl is unreadable or corrupted")
    else:
        lines.append("| Events log | not found | ⚠️ |")
        warnings.append("No events.jsonl found in archive")

    # Event count status
    if total_events == 0:
        lines.append("| Event count | 0 | ⚠️ |")
    elif total_events >= LARGE_EVENT_LOG_LINES:
        lines.append(f"| Event count | {total_events} | ⚠️ |")
        warnings.append(f"Large event log ({total_events} entries) — consider archiving")
    else:
        lines.append(f"| Event count | {total_events} | ✅ |")

    # Tool call density
    if total_events > 0:
        density = (tool_calls / total_events) * 100
        density_str = f"{density:.0f}%"
        if density > HIGH_TOOL_CALL_DENSITY:
            lines.append(f"| Tool call density | {tool_calls}/{total_events} ({density_str}) | ⚠️ |")
            recommendations.append(
                f"High tool-call density ({density_str}). Consider batching operations "
                "or reducing subagent fan-out width."
            )
        else:
            lines.append(f"| Tool call density | {tool_calls}/{total_events} ({density_str}) | ✅ |")

    # --- 2. Archive artifact sizes ---
    large_artifacts: list[tuple[str, int]] = []
    total_archive_bytes = 0

    if run_dir.is_dir():
        for fpath in sorted(run_dir.rglob("*")):
            if fpath.is_file():
                size = fpath.stat().st_size
                total_archive_bytes += size
                rel = str(fpath.relative_to(run_dir))
                if size > MAX_ARTIFACT_BYTES:
                    large_artifacts.append((rel, size))

    lines.append(f"| Archive size | {_format_size(total_archive_bytes)} | "
                 f"{_status_icon(total_archive_bytes < 10 * 1024 * 1024)} |")

    if large_artifacts:
        oversized = len(large_artifacts)
        lines.append(f"| Artifacts >5KB | {oversized} | ⚠️ |")
        for name, size in large_artifacts[:5]:
            warnings.append(f"Large artifact: {name} ({_format_size(size)})")
        if len(large_artifacts) > 5:
            warnings.append(f"...and {len(large_artifacts) - 5} more oversized artifacts")
        recommendations.append(
            "Consider trimming large diff patches or summary files in the archive."
        )

    # --- 3. Subagent dispatch analysis ---
    if subagent_dispatches:
        repeated = [(st, c) for st, c in subagent_dispatches.most_common()
                     if c >= REPEATED_SUBAGENT_THRESHOLD]
        if repeated:
            detail = ", ".join(f"{st}×{c}" for st, c in repeated[:3])
            lines.append(f"| Repeated subagents | {detail} | ⚠️ |")
            recommendations.append(
                "Repeated dispatches to the same subagent type detected. "
                "Consider consolidating tasks to reduce round-trips."
            )
        else:
            lines.append(f"| Subagent dispatches | {sum(subagent_dispatches.values())} unique | ✅ |")

    # --- 4. Recommendations ---
    lines.append("")

    if recommendations:
        lines.append("### Recommendations")
        lines.append("")
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")
    else:
        lines.append("### Analysis")
        lines.append("")
        lines.append("Session is healthy — no actionable budget concerns detected.")
        lines.append("")

    if warnings:
        lines.append("### Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze z-harness telemetry for context utilization insights."
    )
    parser.add_argument(
        "run_dir",
        help="Path to a run archive directory (contains events.jsonl)",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        print(f"context-budget: directory not found: {run_dir}", file=sys.stderr)
        # Still produce output for graceful handling
        print("## Context Budget\n\nNo telemetry data — archive directory not found.\n")
        return 0

    result = analyze(run_dir)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
