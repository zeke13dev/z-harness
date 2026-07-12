#!/usr/bin/env python3
"""stats.py — mechanical report subcommands for /z-stats.

Every /z-stats report phase that used to be inline jq/awk against
metrics.jsonl (or, for the absorbed /z-where behavior, an inline python
one-liner against active-plan-registry.py's --json output) shells out to one
subcommand here instead. No subcommand dispatches a subagent or calls an LLM
— this module only reads existing files (TASKS.md, metrics.jsonl, FIX.md,
TESTS.md) and shells out to the two existing read-only scripts that already
own registry state (plan-path.sh, active-plan-registry.py).

Subcommands:
  header                         Base/Repo-id/Active-plan-count header block.
  active-plans [--run-id ID]     Active-plan table + overlap section
                                  (absorbs the former /z-where command body).
  progress BASE SLUG             TASKS.md done/in_progress/pending/skipped.
  walltime METRICS               Per-phase-kind wall_ms sum/avg, desc by sum.
  tokens METRICS                 Per-subagent_model input/output token split.
  coordination METRICS [--run-id ID]
                                  Tally of the 7 coordination event kinds.
  halts METRICS                  Last 10 halt/decision/security-warn events.
  next-command BASE METRICS      Suggested next command from plan state.

Every subcommand is read-only: no writes, no subagent dispatch, no LLM calls.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_COORD_KINDS = [
    "lease_claimed",
    "lease_released",
    "wait_started",
    "wait_cleared",
    "wait_timeout",
    "wait_interrupted",
    "coordination_warning",
]

_HALT_KINDS = {
    "task_halt",
    "decision_gate",
    "task_security_warn",
    "review_agent_failed",
    "review_agent_malformed",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _plugin_root() -> Path:
    for var in ("ANTIGRAVITY_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT"):
        val = os.environ.get(var)
        if val:
            return Path(val)
    return Path(__file__).resolve().parent.parent


def _run_capture(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _read_events(metrics_path: Path | None) -> list[dict]:
    if metrics_path is None or not metrics_path.is_file():
        return []
    events: list[dict] = []
    with metrics_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _list_active_plans(registry_py: Path) -> list[dict] | None:
    try:
        proc = subprocess.run(
            ["python3", str(registry_py), "list", "--json"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _truncate(value: str | None, width: int) -> str:
    value = value or ""
    return value if len(value) <= width else value[:width]


def _parse_age_seconds(heartbeat: str | None) -> float | None:
    if not heartbeat:
        return None
    dt = None
    try:
        dt = datetime.strptime(heartbeat, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            dt = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
        except ValueError:
            return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _fmt_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h"


def _resolve_status(rec: dict) -> str:
    status = rec.get("status", "")
    age = _parse_age_seconds(rec.get("last_heartbeat"))
    if status == "stale" or (age is not None and age > 1800):
        return "stale"
    if status == "running":
        return "running"
    return status or "?"


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------

def compute_progress(tasks_path: Path) -> dict:
    """Count done/in_progress/pending task headings and **SKIP:** markers.

    Delegates the actual heading/status parse to
    scripts/session-helpers.sh task_status_counts — the SAME inline-heading
    (`## T001 — title \\`[x]\\``) and list-checkbox parser used by
    check-compaction.sh, context-curator, and SESSION resume, so /z-stats
    counts never drift from what the orchestrator itself considers "done".
    """
    if not tasks_path.is_file():
        return {"exists": False, "done": 0, "in_progress": 0, "pending": 0, "skipped": 0, "total": 0}
    plugin_root = _plugin_root()
    session_helpers_sh = plugin_root / "scripts" / "session-helpers.sh"
    counts_line = _run_capture(["bash", str(session_helpers_sh), "task_status_counts", str(tasks_path)])
    counts = {"done": 0, "pending": 0, "in_progress": 0, "other": 0}
    for pair in counts_line.split():
        key, _, value = pair.partition("=")
        if key in counts:
            try:
                counts[key] = int(value)
            except ValueError:
                counts[key] = 0
    skipped = len(re.findall(r"\*\*SKIP:", tasks_path.read_text(encoding="utf-8")))
    total = counts["done"] + counts["in_progress"] + counts["pending"] + counts["other"]
    return {
        "exists": True,
        "done": counts["done"],
        "in_progress": counts["in_progress"],
        "pending": counts["pending"],
        "skipped": skipped,
        "total": total,
    }


def cmd_progress(args: argparse.Namespace) -> int:
    progress = compute_progress(Path(args.base_dir) / "TASKS.md")
    if not progress["exists"]:
        print(f"Plan: {args.slug}")
        print("Progress: (TASKS.md not found)")
        return 0
    print(f"Plan: {args.slug}")
    print(
        f"Progress: {progress['done']}/{progress['total']} done · "
        f"{progress['in_progress']} in_progress · {progress['pending']} pending · "
        f"{progress['skipped']} skipped"
    )
    return 0


# ---------------------------------------------------------------------------
# walltime
# ---------------------------------------------------------------------------

def compute_walltime(events: list[dict]) -> list[tuple[str, int, int]]:
    """Per-`*_end`-kind (count, sum_wall_ms), sorted by sum descending."""
    sums: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for ev in events:
        kind = ev.get("kind") or ""
        if not kind.endswith("_end"):
            continue
        wall_ms = ev.get("wall_ms") or 0
        try:
            wall_ms = int(wall_ms)
        except (TypeError, ValueError):
            wall_ms = 0
        sums[kind] += wall_ms
        counts[kind] += 1
    rows = [(kind, counts[kind], sums[kind]) for kind in sums]
    rows.sort(key=lambda row: row[2], reverse=True)
    return rows


def cmd_walltime(args: argparse.Namespace) -> int:
    events = _read_events(Path(args.metrics) if args.metrics else None)
    rows = compute_walltime(events)
    for kind, n, total_ms in rows:
        avg_ms = total_ms // n if n else 0
        minutes = total_ms // 60000
        print(f"{kind:<25} n={n:<4} sum={minutes}m  avg={avg_ms}ms")
    return 0


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------

def compute_tokens(events: list[dict]) -> list[tuple[str, int, int, int]]:
    """Per-subagent_model (calls, input_tok, output_tok), sorted by model name."""
    in_tok: dict[str, float] = defaultdict(float)
    out_tok: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for ev in events:
        model = ev.get("subagent_model")
        if not model:
            continue
        input_val = ev.get("subagent_input_tokens")
        if input_val is None:
            input_val = (ev.get("prompt_chars") or 0) / 4
        output_val = ev.get("subagent_output_tokens")
        if output_val is None:
            output_val = (ev.get("response_chars") or 0) / 4
        in_tok[model] += float(input_val or 0)
        out_tok[model] += float(output_val or 0)
        counts[model] += 1
    return [(m, counts[m], int(in_tok[m]), int(out_tok[m])) for m in sorted(counts)]


def cmd_tokens(args: argparse.Namespace) -> int:
    events = _read_events(Path(args.metrics) if args.metrics else None)
    for model, calls, input_tok, output_tok in compute_tokens(events):
        print(f"{model:<10} calls={calls:<4} input_tok={input_tok} output_tok={output_tok}")
    return 0


# ---------------------------------------------------------------------------
# coordination
# ---------------------------------------------------------------------------

def compute_coordination(events: list[dict], run_id: str | None = None) -> dict[str, int]:
    """Tally the 7 coordination event kinds; always includes all 7 keys."""
    counts = {kind: 0 for kind in _COORD_KINDS}
    for ev in events:
        kind = ev.get("kind")
        if kind not in counts:
            continue
        if run_id and ev.get("run_id") and ev.get("run_id") != run_id:
            continue
        counts[kind] += 1
    return counts


def cmd_coordination(args: argparse.Namespace) -> int:
    events = _read_events(Path(args.metrics) if args.metrics else None)
    counts = compute_coordination(events, args.run_id)
    print("Coordination events:")
    for kind in _COORD_KINDS:
        print(f"  {kind:<28} {counts[kind]}")
    return 0


# ---------------------------------------------------------------------------
# halts
# ---------------------------------------------------------------------------

def compute_halts(events: list[dict], limit: int = 10) -> list[dict]:
    matches = [ev for ev in events if ev.get("kind") in _HALT_KINDS]
    return matches[-limit:]


def cmd_halts(args: argparse.Namespace) -> int:
    events = _read_events(Path(args.metrics) if args.metrics else None)
    for ev in compute_halts(events):
        print(json.dumps(ev, separators=(",", ":")))
    return 0


# ---------------------------------------------------------------------------
# header (absorbs /z-where's resolved-base line)
# ---------------------------------------------------------------------------

def cmd_header(args: argparse.Namespace) -> int:  # noqa: ARG001 (argparse contract)
    plugin_root = _plugin_root()
    base = _run_capture(["bash", str(plugin_root / "scripts" / "plan-path.sh"), "base_dir"])
    repo_id = _run_capture(["bash", str(plugin_root / "scripts" / "plan-path.sh"), "z_harness_repo_id"])
    records = _list_active_plans(plugin_root / "scripts" / "active-plan-registry.py")

    print(f"Base:        {base or '(unavailable)'}")
    print(f"Repo-id:     {repo_id or '(unavailable)'}")
    if records is None:
        print("Active plans: (registry unavailable)")
    else:
        print(f"Active plans: {len(records)}")
    return 0


# ---------------------------------------------------------------------------
# active-plans (absorbs /z-where's table + overlap phases)
# ---------------------------------------------------------------------------

def cmd_active_plans(args: argparse.Namespace) -> int:
    plugin_root = _plugin_root()
    registry_py = plugin_root / "scripts" / "active-plan-registry.py"
    records = _list_active_plans(registry_py)

    if records is None:
        print("Active plans: (registry unavailable)")
    elif not records:
        print("Active plans: 0 — no active plans registered.")
    else:
        print(f"Active plans: {len(records)}\n")
        print(f"{'slug':<20}{'command':<20}{'phase':<10}{'branch':<16}{'current_task':<14}{'age':<8}status")
        for rec in records:
            slug = _truncate(rec.get("slug", ""), 20)
            command = _truncate(rec.get("command", ""), 20)
            phase = _truncate(rec.get("phase", ""), 10)
            branch = _truncate(rec.get("branch", ""), 16)
            task = _truncate(rec.get("current_task", "") or "(none)", 14)
            age_secs = _parse_age_seconds(rec.get("last_heartbeat"))
            age_str = _fmt_age(age_secs) if age_secs is not None else "?"
            status = _resolve_status(rec)
            print(f"{slug:<20}{command:<20}{phase:<10}{branch:<16}{task:<14}{age_str:<8}{status}")

    run_id = args.run_id or os.environ.get("Z_HARNESS_RUN_ID", "")
    print()
    if not run_id:
        print(
            "Overlaps: pass --run-id <id> or set Z_HARNESS_RUN_ID to see path-overlap "
            "with a specific active run.\n"
            "          (The active plan list above shows all concurrent runs regardless.)"
        )
        return 0

    try:
        proc = subprocess.run(
            ["python3", str(registry_py), "overlaps", "--run-id", run_id],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("Overlaps: (registry error — could not compute)")
        return 0

    if proc.returncode == 0:
        print("Overlaps: none (no shared paths with other active plans)")
    elif proc.returncode == 10:
        print("Overlaps:")
        print(proc.stdout.strip())
    elif proc.returncode == 20:
        print("[BLOCKING] Overlaps:")
        print(proc.stdout.strip())
    else:
        print("Overlaps: (registry error — could not compute)")
    return 0


# ---------------------------------------------------------------------------
# next-command
# ---------------------------------------------------------------------------

def _fix_docs_touched_nonempty(fix_path: Path) -> bool:
    if not fix_path.is_file():
        return False
    text = fix_path.read_text(encoding="utf-8")
    match = re.search(r"^## Docs touched\s*\n(.*?)(?=\n## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return False
    body = match.group(1).strip()
    return bool(body) and body.lower() not in ("none", "none.", "n/a")


def compute_next_command(base_dir: Path, events: list[dict]) -> dict:
    """Deterministic state -> suggested-command lookup (SKILL.md Phase 7 table)."""
    tasks_path = base_dir / "TASKS.md"
    progress = compute_progress(tasks_path)
    tests_path = base_dir / "TESTS.md"
    fix_path = base_dir / "FIX.md"

    recent_halts = compute_halts(events)
    has_task_start = any(ev.get("kind") == "task_start" for ev in events)
    review_all_ends = [ev for ev in events if ev.get("kind") == "review_all_end"]
    review_all_ran = bool(review_all_ends)
    review_all_accepted = bool(review_all_ends) and review_all_ends[-1].get("user_action") in (
        "shipped_clean",
        "artifact_promoted",
    )

    if not progress["exists"]:
        if fix_path.is_file():
            docs_touched = _fix_docs_touched_nonempty(fix_path)
            if docs_touched:
                return {"state": "light_mode_shipped", "label": "/z-maintain-docs (refresh affected docs)"}
            return {"state": "light_mode_shipped_clean", "label": "Done — no follow-up required"}
        return {
            "state": "no_plan",
            "label": "/z-plan (feature or small fix) or /z-debug (existing bug)",
        }

    if recent_halts:
        return {"state": "halts_pending", "label": "Resolve halts before continuing", "halts": recent_halts}

    if progress["pending"] == 0 and progress["in_progress"] == 0 and progress["total"] > 0:
        if not review_all_ran:
            return {"state": "all_done_no_review", "label": "/z-review-all"}
        if review_all_accepted:
            return {"state": "review_all_accepted", "label": "/z-maintain-docs (or /z-maintain-docs --audit)"}

    if progress["pending"] > 0 and not has_task_start:
        # Fresh plan (never executed yet): recommend /z-test first unless
        # TESTS.md is already drafted — checked BEFORE the generic pending-
        # tasks fallback below, since a plan that already started executing
        # has passed the point where drafting tests first still makes sense.
        if not tests_path.is_file():
            return {
                "state": "fresh_no_tests",
                "label": "/z-test (optional, recommended for risky/financial code) then /z-execute",
            }
        return {"state": "fresh_with_tests", "label": "/z-execute (will pick up TESTS.md automatically)"}

    if progress["pending"] > 0:
        return {"state": "pending_tasks", "label": "/z-execute"}

    return {"state": "unknown", "label": "(no clear next step — review plan state manually)"}


def cmd_next_command(args: argparse.Namespace) -> int:
    events = _read_events(Path(args.metrics) if args.metrics else None)
    result = compute_next_command(Path(args.base_dir), events)
    if result["state"] == "halts_pending":
        print("Resolve halts before continuing:")
        for halt in result["halts"]:
            print(f"  {json.dumps(halt, separators=(',', ':'))}")
    else:
        print(f"Suggested next: {result['label']}")
    return 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stats.py", description=__doc__)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    sub.add_parser("header", help="Base/Repo-id/Active-plan-count header block.")

    p_active = sub.add_parser("active-plans", help="Active-plan table + overlap section.")
    p_active.add_argument("--run-id", default="")

    p_progress = sub.add_parser("progress", help="TASKS.md progress counts.")
    p_progress.add_argument("base_dir")
    p_progress.add_argument("slug")

    p_wall = sub.add_parser("walltime", help="Per-phase-kind wall_ms sum/avg.")
    p_wall.add_argument("metrics")

    p_tok = sub.add_parser("tokens", help="Per-subagent_model token split.")
    p_tok.add_argument("metrics")

    p_coord = sub.add_parser("coordination", help="Coordination event tallies.")
    p_coord.add_argument("metrics")
    p_coord.add_argument("--run-id", default="")

    p_halts = sub.add_parser("halts", help="Last 10 halt/decision/security-warn events.")
    p_halts.add_argument("metrics")

    p_next = sub.add_parser("next-command", help="Suggested next command from plan state.")
    p_next.add_argument("base_dir")
    p_next.add_argument("metrics", nargs="?", default="")

    return parser


_DISPATCH = {
    "header": cmd_header,
    "active-plans": cmd_active_plans,
    "progress": cmd_progress,
    "walltime": cmd_walltime,
    "tokens": cmd_tokens,
    "coordination": cmd_coordination,
    "halts": cmd_halts,
    "next-command": cmd_next_command,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return _DISPATCH[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())
