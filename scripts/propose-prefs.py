#!/usr/bin/env python3
"""
Propose preference settings based on repeated command-pair patterns in metrics.jsonl.

Usage:
    python3 scripts/propose-prefs.py --check <command-name>

Exit codes:
  0 — success (stdout may be empty if no proposal, or JSON if threshold met)
  Any exception — exit 0, empty stdout, stderr log (never blocks calling command)

Environment:
  Z_HARNESS_PROPOSE_WINDOW_S   — max gap between cmd_a end and cmd_b start (default 3600)
  Z_HARNESS_PROPOSE_THRESHOLD  — min repetitions to fire a proposal (default 3)
  Z_HARNESS_PROPOSE_MAX_RUNS   — number of recent run_start events to scan (default 30)
  Z_HARNESS_METRICS            — override path to metrics.jsonl
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Watched patterns (hardcoded v1)
# ---------------------------------------------------------------------------

WATCHED_PATTERNS = [
    {
        "cmd_a": "z-audit-plan",
        "cmd_b": "z-amend",
        "question_id": "workflow.audit_to_amend",
        "proposed_value": "amend",
    },
    {
        "cmd_a": "z-audit-plan-style",
        "cmd_b": "z-amend",
        "question_id": "workflow.audit_to_amend",
        "proposed_value": "amend",
    },
]

# ---------------------------------------------------------------------------
# Repo root resolution
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Resolve repo root via git rev-parse, or fall back to cwd."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def _resolved_metrics_path(repo_root: Path) -> Path:
    """Aggregate metrics.jsonl under the resolved artifact base.

    Since the Phase-D flip the default base is EXTERNAL (XDG_STATE_HOME/...), so
    metrics.jsonl no longer lives under repo_root/z-harness by default. Resolve
    via plan-path.sh base_dir (honouring the full 5-tier fallback); fall back to
    the legacy in-repo path when plan-path.sh is unavailable or the resolved
    location does not exist yet. Best-effort; never raises.
    """
    import subprocess
    plan_path_sh = Path(__file__).resolve().parent / "plan-path.sh"
    resolved = None
    if plan_path_sh.exists():
        try:
            result = subprocess.run(
                ["bash", str(plan_path_sh), "base_dir"],
                capture_output=True, text=True,
                cwd=str(repo_root),
                env={**os.environ, "_Z_HARNESS_RESOLVING_BASE": "1"},
            )
            base = result.stdout.strip()
            if result.returncode == 0 and base:
                resolved = Path(base) / "metrics.jsonl"
        except (FileNotFoundError, OSError):
            pass
    legacy = repo_root / "z-harness" / "metrics.jsonl"
    if resolved is not None and (resolved.exists() or not legacy.exists()):
        return resolved
    return legacy


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

def _parse_ts(ts_str: str) -> float:
    """Parse an ISO 8601 UTC timestamp string to a POSIX float. Returns 0.0 on error."""
    try:
        # Python 3.7+ supports %z with 'Z' only from 3.11+; use fromisoformat workaround.
        ts_str = ts_str.rstrip("Z")
        dt = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0.0


# ---------------------------------------------------------------------------
# Command matching
# ---------------------------------------------------------------------------

def _event_command(event: dict) -> str | None:
    """
    Extract the command name from a metrics.jsonl event.

    Checks (in order):
    1. `command` field (set by orchestration run_start events).
    2. `cmd` field.
    3. `task` field parsed for command tokens (e.g., '/z-audit-plan').

    Returns None if no recognisable command found.
    """
    if "command" in event and isinstance(event["command"], str):
        return event["command"].lstrip("/")
    if "cmd" in event and isinstance(event["cmd"], str):
        return event["cmd"].lstrip("/")
    # task field: look for a '/z-<word>' token
    task = event.get("task", "")
    if isinstance(task, str):
        for token in task.split():
            clean = token.strip(",;:").lstrip("/")
            if clean.startswith("z-"):
                return clean
    return None


def _run_matches_command(event: dict, command_name: str) -> bool:
    """Return True when event's command field matches the given bare command name."""
    cmd = _event_command(event)
    if cmd is None:
        return False
    # Normalize: strip leading slash, lowercase
    return cmd.lower().lstrip("/") == command_name.lower().lstrip("/")


# ---------------------------------------------------------------------------
# Suppression file helpers
# ---------------------------------------------------------------------------

def _suppress_path(project_root: Path) -> Path:
    return project_root / ".z-harness" / ".propose-suppress"


def _load_suppression(project_root: Path) -> dict:
    """Load suppression dict {question_id: expiry_ts_str}. Returns empty dict on error."""
    path = _suppress_path(project_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _is_suppressed(suppression: dict, question_id: str) -> bool:
    """Return True if question_id is suppressed and hasn't expired yet."""
    expiry_ts_str = suppression.get(question_id)
    if not expiry_ts_str:
        return False
    try:
        expiry_ts = float(expiry_ts_str)
    except (ValueError, TypeError):
        return False
    return time.time() < expiry_ts


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def _load_events(metrics_path: Path) -> list[dict]:
    """Load all events from metrics.jsonl. Returns list of dicts."""
    if not metrics_path.exists():
        return []
    events = []
    with open(metrics_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _extract_slug(event: dict) -> str | None:
    """
    Extract the slug from an event.

    Checks `slug` field first, then parses the run ID (e.g.,
    '20260522T071910Z-brainstorm-and-research' → 'brainstorm-and-research').
    """
    slug = event.get("slug")
    if slug and isinstance(slug, str):
        return slug
    run = event.get("run", "")
    if isinstance(run, str) and run and run != "orchestration":
        # Run IDs are formatted as <timestamp>-<slug>
        # timestamp is always 16 chars: 20260522T071910Z
        parts = run.split("-", 1)
        if len(parts) == 2 and len(parts[0]) >= 8 and parts[0][0].isdigit():
            return parts[1] or None
    return None


def _collect_run_boundaries(
    events: list[dict],
    max_runs: int,
) -> list[dict]:
    """
    Return a list of run boundary entries in chronological order.

    Each entry:
      {
        "run": <run_id>,
        "slug": <slug_or_None>,
        "kind": "run_start"|"run_end",
        "ts": <float posix>,
        "ts_str": <original ts string>,
        "command": <str_or_None>,
        "project_root": <str_or_None>,
        "raw": <original event dict>,
      }

    We only keep the last `max_runs` unique run IDs (by first seen run_start).
    """
    # Collect all run_start / run_end events
    boundary_events = [
        e for e in events
        if e.get("kind") in ("run_start", "run_end")
    ]

    # Find the last max_runs unique run IDs by scanning run_start events
    seen_runs: list[str] = []
    for e in boundary_events:
        run_id = e.get("run")
        if e.get("kind") == "run_start" and run_id and run_id not in seen_runs:
            seen_runs.append(run_id)

    # Keep only recent runs
    recent_runs = set(seen_runs[-max_runs:])

    result = []
    for e in boundary_events:
        run_id = e.get("run")
        if run_id not in recent_runs:
            continue
        ts_str = e.get("ts", "")
        ts = _parse_ts(ts_str)
        result.append({
            "run": run_id,
            "slug": _extract_slug(e),
            "kind": e.get("kind"),
            "ts": ts,
            "ts_str": ts_str,
            "command": _event_command(e),
            "project_root": e.get("project_root"),
            "raw": e,
        })

    result.sort(key=lambda x: x["ts"])
    return result


def _detect_pairs(
    boundaries: list[dict],
    cmd_a: str,
    cmd_b: str,
    window_s: float,
) -> list[dict]:
    """
    Detect occurrences of cmd_a run_end followed by cmd_b run_start within
    window_s seconds, on the same slug.

    Returns list of evidence dicts:
      {
        "run_a": <run_id>,
        "run_b": <run_id>,
        "slug": <slug>,
        "ts_a_end": <str>,
        "ts_b_start": <str>,
        "gap_s": <float>,
        "project_root": <str_or_None>,
      }
    """
    # Build lookup: run_id → list of boundary entries
    run_map: dict[str, list[dict]] = {}
    for b in boundaries:
        run_map.setdefault(b["run"], []).append(b)

    # Find cmd_a run_end events (where command matches cmd_a)
    a_ends = [
        b for b in boundaries
        if b["kind"] == "run_end"
        and b["command"] is not None
        and b["command"].lower().lstrip("/") == cmd_a.lower().lstrip("/")
    ]

    # For each cmd_a end, look forward for cmd_b run_start within window and same slug
    pairs = []
    used_pairs: set[tuple[str, str]] = set()

    for a_end in a_ends:
        slug_a = a_end["slug"]
        ts_a = a_end["ts"]

        for b in boundaries:
            if b["kind"] != "run_start":
                continue
            if b["command"] is None:
                continue
            if b["command"].lower().lstrip("/") != cmd_b.lower().lstrip("/"):
                continue
            # Same slug
            if b["slug"] != slug_a:
                continue
            # Within window
            gap = b["ts"] - ts_a
            if gap < 0 or gap > window_s:
                continue
            # Deduplicate: each (run_a, run_b) pair counted only once
            pair_key = (a_end["run"], b["run"])
            if pair_key in used_pairs:
                continue
            used_pairs.add(pair_key)

            pairs.append({
                "run_a": a_end["run"],
                "run_b": b["run"],
                "slug": slug_a,
                "ts_a_end": a_end["ts_str"],
                "ts_b_start": b["ts_str"],
                "gap_s": round(gap, 1),
                "project_root": a_end.get("project_root") or b.get("project_root"),
            })

    return pairs


def _scope_recommendation(pairs: list[dict], current_project_root: str) -> str:
    """
    If pairs span multiple distinct project_roots → 'global'.
    If all pairs are in the same project_root as current → 'project'.
    Falls back to 'project' if project_root data is absent.
    """
    roots = {p.get("project_root") for p in pairs if p.get("project_root")}
    if len(roots) > 1:
        return "global"
    if not roots:
        return "project"
    only_root = next(iter(roots))
    if only_root != current_project_root:
        return "global"
    return "project"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Propose preference changes based on repeated command-pair patterns."
    )
    parser.add_argument(
        "--check",
        metavar="COMMAND_NAME",
        required=True,
        help="Name of the command that just finished (e.g. z-audit-plan).",
    )
    parser.add_argument(
        "--metrics",
        metavar="PATH",
        default=None,
        help="Override path to metrics.jsonl (default: z-harness/metrics.jsonl in repo root).",
    )
    args = parser.parse_args()

    command_name = args.check.lstrip("/")

    # Env configuration
    window_s = float(os.environ.get("Z_HARNESS_PROPOSE_WINDOW_S", "3600"))
    threshold = int(os.environ.get("Z_HARNESS_PROPOSE_THRESHOLD", "3"))
    max_runs = int(os.environ.get("Z_HARNESS_PROPOSE_MAX_RUNS", "30"))

    # Paths
    repo_root = _repo_root()
    metrics_path = Path(
        args.metrics
        or os.environ.get("Z_HARNESS_METRICS", "")
        or _resolved_metrics_path(repo_root)
    )
    project_root = str(repo_root)

    # Suppression check (per project, per question_id)
    suppression = _load_suppression(repo_root)

    # Load and parse events
    events = _load_events(metrics_path)
    boundaries = _collect_run_boundaries(events, max_runs)

    # Find matching watched patterns where cmd_a == the checked command
    for pattern in WATCHED_PATTERNS:
        if pattern["cmd_a"].lower() != command_name.lower():
            continue

        question_id = pattern["question_id"]
        proposed_value = pattern["proposed_value"]

        # Check suppression
        if _is_suppressed(suppression, question_id):
            return  # Suppressed; emit nothing

        cmd_a = pattern["cmd_a"]
        cmd_b = pattern["cmd_b"]

        pairs = _detect_pairs(boundaries, cmd_a, cmd_b, window_s)

        if len(pairs) < threshold:
            continue  # Not enough evidence; try next pattern

        scope = _scope_recommendation(pairs, project_root)

        proposal = {
            "question_id": question_id,
            "proposed_value": proposed_value,
            "evidence": pairs,
            "scope_recommendation": scope,
        }
        print(json.dumps(proposal))
        return  # Emit at most one proposal per invocation


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print(traceback.format_exc(), file=sys.stderr)
        sys.exit(0)
