#!/usr/bin/env python3
"""
evaluate-session.py — Analyze a z-harness session for patterns worth preserving as memories or skills.

Usage:
    python3 scripts/evaluate-session.py <archive_dir>

Reads events.jsonl + run-brief.json from a run archive.
Detects patterns: repeated explorations, multi-review-cycle tasks, uncovered file patterns.
Produces Markdown output with memory candidates and skill candidates.

Confidence heuristic:
  HIGH = 3+ occurrences of the pattern in the session
  MEDIUM = 2 occurrences
  LOW = 1 occurrence (suppressed — not emitted)

Max 5 memory candidates + 3 skill candidates.
Handles: corrupt events.jsonl, no patterns found, empty archive gracefully.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

MAX_MEMORY_CANDIDATES = 5
MAX_SKILL_CANDIDATES = 3


def _confidence(n: int) -> str:
    """Return confidence tier string based on occurrence count."""
    if n >= 3:
        return "HIGH"
    if n >= 2:
        return "MEDIUM"
    return "LOW"


def _scan_events(events_path: Path) -> dict:
    """Scan events.jsonl and return a dict of detected patterns."""
    if not events_path.is_file():
        return {}

    events: list[dict] = []
    try:
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return {}

    # Pattern detectors
    task_review_cycles: Counter = Counter()  # task_id → review cycles
    task_retries: Counter = Counter()         # task_id → retry count
    task_halts: Counter = Counter()           # task_id → halt count
    exploration_kinds: Counter = Counter()    # kind → count
    uncategorized_files: set = set()          # files touched but not in expected set
    all_files_touched: set = set()

    for ev in events:
        kind = ev.get("kind", "")
        task_id = ev.get("id", ev.get("task_id", ""))

        if kind == "task_done":
            if task_id:
                cycles = ev.get("review_cycles", 1)
                retries = ev.get("retries", ev.get("total_retries", 0))
                task_review_cycles[task_id] = max(task_review_cycles.get(task_id, 0), cycles)
                task_retries[task_id] = max(task_retries.get(task_id, 0), retries)

        elif kind == "task_halt":
            if task_id:
                task_halts[task_id] += 1

        elif kind in ("explore_start", "exploration_start"):
            exploration_kinds["explore"] += 1

        elif kind == "subagent_dispatch":
            st = ev.get("subagent_type", "")
            if "explore" in st.lower():
                exploration_kinds[f"subagent:{st}"] += 1
            if "doc-fetcher" in st.lower():
                exploration_kinds["doc_fetcher"] += 1

    multi_cycle_tasks = {tid: c for tid, c in task_review_cycles.items() if c >= 2}
    multi_retry_tasks = {tid: c for tid, c in task_retries.items() if c >= 1}
    halted_tasks = dict(task_halts)

    total_explorations = sum(exploration_kinds.values())

    return {
        "multi_cycle_tasks": multi_cycle_tasks,
        "multi_retry_tasks": multi_retry_tasks,
        "halted_tasks": halted_tasks,
        "exploration_kinds": dict(exploration_kinds),
        "total_explorations": total_explorations,
        "total_events": len(events),
    }


def _build_candidates(patterns: dict, slug: str = "") -> tuple[list[dict], list[dict]]:
    """Build memory and skill candidates from detected patterns."""
    memory_candidates: list[dict] = []
    skill_candidates: list[dict] = []

    # 1. Multi-review-cycle tasks → memory candidate
    multi_cycle = patterns.get("multi_cycle_tasks", {})
    if multi_cycle:
        n = len(multi_cycle)
        conf = _confidence(n)
        if conf != "LOW":
            task_list = ", ".join(sorted(multi_cycle.keys())[:5])
            memory_candidates.append({
                "slug": f"multi-review-tasks-{slug}" if slug else "multi-review-tasks",
                "evidence": f"{n} tasks required multiple review cycles: {task_list}",
                "confidence": conf,
            })

    # 2. Repeated explorations → memory candidate
    total_expl = patterns.get("total_explorations", 0)
    if total_expl >= 2:
        conf = _confidence(total_expl)
        if conf != "LOW":
            memory_candidates.append({
                "slug": f"high-exploration-session-{slug}" if slug else "high-exploration-session",
                "evidence": f"{total_expl} exploration events fired in this session",
                "confidence": conf,
            })

    # 3. Halted tasks → memory candidate
    halted = patterns.get("halted_tasks", {})
    if halted:
        n = len(halted)
        conf = _confidence(n)
        if conf != "LOW":
            task_list = ", ".join(sorted(halted.keys())[:5])
            memory_candidates.append({
                "slug": f"task-halts-pattern-{slug}" if slug else "task-halts-pattern",
                "evidence": f"{n} tasks halted: {task_list}",
                "confidence": conf,
            })

    # 4. Multi-retry tasks → skill candidate (reviewer improvement)
    multi_retry = patterns.get("multi_retry_tasks", {})
    if multi_retry:
        n = len(multi_retry)
        conf = _confidence(n)
        if conf != "LOW":
            task_list = ", ".join(sorted(multi_retry.keys())[:5])
            skill_candidates.append({
                "name": "reviewer-improvement",
                "trigger": f"{n} tasks needed retries after review: {task_list}",
                "confidence": conf,
            })

    # 5. High exploration → skill candidate (better docs)
    expl_kinds = patterns.get("exploration_kinds", {})
    if total_expl >= 2:
        conf = _confidence(total_expl)
        if conf != "LOW":
            skill_candidates.append({
                "name": "improve-docs-coverage",
                "trigger": f"Session had {total_expl} explorations — gaps in doc coverage likely",
                "confidence": conf,
            })

    # Cap candidates
    memory_candidates.sort(key=lambda x: (0 if x["confidence"] == "HIGH" else 1 if x["confidence"] == "MEDIUM" else 2))
    skill_candidates.sort(key=lambda x: (0 if x["confidence"] == "HIGH" else 1 if x["confidence"] == "MEDIUM" else 2))

    memory_candidates = memory_candidates[:MAX_MEMORY_CANDIDATES]
    skill_candidates = skill_candidates[:MAX_SKILL_CANDIDATES]

    return memory_candidates, skill_candidates


def _render(patterns: dict, mem_candidates: list[dict], skill_candidates: list[dict],
            run_dir: Path) -> str:
    """Render Markdown output."""
    lines: list[str] = []
    run_name = run_dir.name

    lines.append(f"## Session Evaluation — {run_name}")
    lines.append("")

    total_events = patterns.get("total_events", 0)
    if total_events == 0:
        lines.append("No telemetry data — session had no events.\n")
        return "\n".join(lines)

    # Pattern summary
    multi_cycle = patterns.get("multi_cycle_tasks", {})
    halted = patterns.get("halted_tasks", {})
    total_expl = patterns.get("total_explorations", 0)

    lines.append("### Detected Patterns")
    lines.append("")
    if multi_cycle:
        lines.append(f"- **{len(multi_cycle)} tasks** required multiple review cycles")
    if halted:
        lines.append(f"- **{len(halted)} tasks** were halted during the session")
    if total_expl >= 1:
        lines.append(f"- **{total_expl} explorations** fired during the session")
    if not multi_cycle and not halted and total_expl == 0:
        lines.append("No patterns detected — session was routine.")
    lines.append("")

    # Memory candidates
    if mem_candidates:
        lines.append("### Memory Candidates")
        lines.append("")
        for mc in mem_candidates:
            lines.append(f"- **{mc['slug']}** ({mc['confidence']})")
            lines.append(f"  {mc['evidence']}")
        lines.append("")
    else:
        lines.append("### Memory Candidates")
        lines.append("")
        lines.append("(none)")
        lines.append("")

    # Skill candidates
    if skill_candidates:
        lines.append("### Skill Candidates")
        lines.append("")
        for sc in skill_candidates:
            lines.append(f"- **{sc['name']}** ({sc['confidence']})")
            lines.append(f"  {sc['trigger']}")
        lines.append("")
    else:
        lines.append("### Skill Candidates")
        lines.append("")
        lines.append("(none)")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a z-harness session for patterns worth preserving."
    )
    parser.add_argument("run_dir", help="Path to a run archive directory")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    slug = run_dir.parent.parent.name if run_dir.parent.parent.name != "archive" else ""

    patterns = _scan_events(run_dir / "events.jsonl")
    mem_candidates, skill_candidates = _build_candidates(patterns, slug)
    output = _render(patterns, mem_candidates, skill_candidates, run_dir)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
