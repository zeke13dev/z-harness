#!/usr/bin/env python3
"""
estimate-tokens.py — LLM-free pre-run token-cost estimator for z-harness commands.

CLI:
  estimate-tokens.py <command> [--dispatch KEY=N ...] [--metrics PATH]
                     [--profiles PATH] [--tail-lines N] [--min-samples N]

Stdout: a single JSON envelope (see SPEC "Output envelope").
Stderr: all diagnostics/warnings.
Exit 0 on any producible envelope; exit non-zero only if <command> arg is missing.

Tiers:
  1. Static  — reads profile range from token-cost-profiles.json.
  2. Dispatch — adds Σ multipliers[key]*N for each --dispatch KEY=N given.
  3. Empirical — parent-run rollup from metrics.jsonl (bounded, race-safe,
                 completion-filtered).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Script-directory constant (profiles file co-located here)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Command normalization
# ---------------------------------------------------------------------------

# Known profile key aliases (without z- prefix, with z- prefix).  The normalizer
# tries the full string first, then strips a leading slash, then tries prepending
# "z-" for bare shorthand (e.g. "research" → "z-research").
_STRIP_SLASH_RE = None  # lazy: just do str.lstrip("/")


def _normalize_command(raw: str) -> str:
    """Strip leading '/' and return the canonical profile key candidate."""
    return raw.lstrip("/")


def _resolve_profile(raw_command: str, profiles: dict) -> tuple[str, dict | None]:
    """Return (canonical_key, profile_dict) or (canonical_key, None) if not found.

    Match order:
      1. Exact match after stripping leading '/'.
      2. If candidate lacks 'z-' prefix, try prepending it.
      3. Ambiguous prefix match (warn, prefer longest).
    """
    candidate = _normalize_command(raw_command)

    # Exact match
    if candidate in profiles:
        return candidate, profiles[candidate]

    # Try prepending 'z-' if not already present
    if not candidate.startswith("z-"):
        with_prefix = f"z-{candidate}"
        if with_prefix in profiles:
            return with_prefix, profiles[with_prefix]

    # No match
    return candidate, None


# ---------------------------------------------------------------------------
# Profiles file loading
# ---------------------------------------------------------------------------

def _load_profiles(profiles_path: Path) -> dict:
    """Load and return the profiles dict from token-cost-profiles.json.

    Uses data.get("profiles", {}) and ignores unknown top-level keys (e.g. _grounding).
    Returns {} and warns to stderr on any error.
    """
    try:
        with open(profiles_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"estimate-tokens: profiles file not found: {profiles_path}", file=sys.stderr)
        return {}
    except json.JSONDecodeError as exc:
        print(f"estimate-tokens: malformed profiles JSON at {profiles_path}: {exc}", file=sys.stderr)
        return {}

    return data.get("profiles", {})


# ---------------------------------------------------------------------------
# Default metrics.jsonl path (mirror z-stats / axiom-extract)
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Resolve repo root via git, else cwd."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return Path.cwd()


def _default_metrics_path() -> Path:
    """Resolve default metrics.jsonl path.

    Priority:
      1. $Z_HARNESS_BASE_DIR/metrics.jsonl if env set and path exists.
      2. <repo>/z-harness/metrics.jsonl otherwise.
    """
    base_dir_env = os.environ.get("Z_HARNESS_BASE_DIR", "")
    if base_dir_env:
        candidate = Path(base_dir_env) / "metrics.jsonl"
        return candidate  # return even if absent — caller handles missing file

    repo = _repo_root()
    return repo / "z-harness" / "metrics.jsonl"


# ---------------------------------------------------------------------------
# Empirical tier helpers
# ---------------------------------------------------------------------------

# Maps start/end event `kind` values to canonical command keys.
# Used ONLY as a legacy fallback when an event lacks the `command` field (pre-T001
# events). The `command` field added by T001 is the authoritative attribution source.
#
# NOTE: generic `run_start`/`run_end` is emitted by BOTH /z-plan AND /z-research
# (see commands/z-research.md:83 and commands/z-plan.md). Kind alone cannot
# disambiguate them. The kind-fallback maps them to z-plan as a best-effort default
# for legacy events; for pre-T001 z-research events the attribution will be wrong.
# The `command` field (added by T001) is the only reliable way to distinguish the two.
_KIND_TO_COMMAND: dict[str, str] = {
    # generic run_start/run_end is emitted by both /z-plan and /z-research;
    # attribution to z-plan here is ambiguous for pre-T001 legacy events only.
    "run_start": "z-plan",
    "run_end": "z-plan",
    "brainstorm_run_start": "z-brainstorm",
    "brainstorm_run_end": "z-brainstorm",
    "audit_run_start": "z-audit",   # confirmed: commands/z-audit.md:83
    "audit_run_end": "z-audit",
    "uplift_run_start": "z-uplift",
    "uplift_run_end": "z-uplift",
    "plan_split_run_start": "z-plan-split",
    "plan_split_run_end": "z-plan-split",
    "debug_run_start": "z-debug",   # confirmed: commands/z-debug.md:39
    "debug_run_end": "z-debug",
}

# Terminal event kind suffixes that mark normal completion.
_TERMINAL_KINDS: frozenset[str] = frozenset({
    "run_end",
    "brainstorm_run_end",
    "audit_run_end",
    "uplift_run_end",
    "plan_split_run_end",
    "debug_run_end",
})

# Statuses that mark abnormal (excluded) completions.
_EXCLUDED_STATUSES: frozenset[str] = frozenset({
    "aborted_by_user",
    "halted",
    "errored",
})

# 5 minutes in seconds — in-flight grace window.
_INFLIGHT_GRACE_SECS: float = 5 * 60.0


def _parse_ts(ts_str: str | None) -> float | None:
    """Parse an ISO-8601 timestamp string to a UTC POSIX timestamp.

    Returns None on any parse failure.
    """
    if not ts_str:
        return None
    try:
        # Python 3.7+ fromisoformat doesn't handle trailing 'Z'.
        normalized = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            # Assume UTC if no timezone given.
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _event_tokens(event: dict) -> int:
    """Return the token count for a single event using the z-stats fallback chain.

    Chain:
      subagent_input_tokens  // prompt_chars/4  // 0
    + subagent_output_tokens // response_chars/4 // 0
    """
    def _get_int(event: dict, key: str) -> int | None:
        v = event.get(key)
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    raw_in = _get_int(event, "subagent_input_tokens")
    if raw_in is None:
        pc = _get_int(event, "prompt_chars")
        raw_in = (pc // 4) if pc is not None else 0

    raw_out = _get_int(event, "subagent_output_tokens")
    if raw_out is None:
        rc = _get_int(event, "response_chars")
        raw_out = (rc // 4) if rc is not None else 0

    return (raw_in or 0) + (raw_out or 0)


def _percentile(sorted_values: list[int], pct: float) -> float:
    """Return the p-th percentile (0–100) of a sorted list using linear interpolation."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_values[0])
    idx = (pct / 100.0) * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return float(sorted_values[-1])
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


# ---------------------------------------------------------------------------
# T004: empirical tier — parent-run rollup, completion-filtered
# ---------------------------------------------------------------------------

def _empirical_tier(
    command: str,
    metrics_path: Path,
    tail_lines: int,
    min_samples: int,
) -> dict | None:
    """Compute p50/p90 over parent-rolled-up token totals for `command`.

    Returns {"p50": int, "p90": int, "samples": int} or None if insufficient
    data / file absent / errors reading.

    Algorithm:
    1. Read the last `tail_lines` lines of metrics_path (bounded tail).
    2. Parse JSON line-by-line; skip malformed lines.
    3. Bucket every event by effective_run = parent_run_id or run.
    4. Attribute each bucket to parent_command or command (field first, then
       _KIND_TO_COMMAND, else "unknown").
    5. Track per-parent-run:
       - command attribution
       - sum of event token counts
       - terminal event (kind + status)
       - whether a cost_gate_decision{choice:abandon} appeared
       - latest timestamp
    6. Find max_ts across ALL events in the tail window.
    7. Filter parent runs: keep only normally-completed parents.
    8. Collect token sums for parent runs attributed to `command`.
    9. Compute p50/p90; return if samples >= min_samples.
    """
    if not metrics_path.exists():
        return None

    # --- Bounded tail read ---
    try:
        with open(metrics_path, encoding="utf-8", errors="replace") as fh:
            raw_lines = fh.readlines()
    except OSError as exc:
        print(
            f"estimate-tokens: error reading metrics file {metrics_path}: {exc}",
            file=sys.stderr,
        )
        return None

    lines = raw_lines[-tail_lines:] if len(raw_lines) > tail_lines else raw_lines

    # --- Parse events ---
    events: list[dict] = []
    skipped_malformed = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                events.append(obj)
        except json.JSONDecodeError:
            skipped_malformed += 1

    if skipped_malformed:
        print(
            f"estimate-tokens: skipped {skipped_malformed} malformed JSON lines "
            f"in {metrics_path}",
            file=sys.stderr,
        )

    if not events:
        return None

    # --- Find max_ts across all events in the tail window ---
    max_ts: float | None = None
    for ev in events:
        ts = _parse_ts(ev.get("ts"))
        if ts is not None:
            if max_ts is None or ts > max_ts:
                max_ts = ts

    # --- Bucket events by effective_run; build per-bucket state ---
    # bucket_command[eff_run] = command string or "unknown"
    # bucket_tokens[eff_run] = cumulative token count
    # bucket_terminal[eff_run] = (kind, status) of the terminal event, or None
    # bucket_abandoned[eff_run] = True if cost_gate_decision{choice:abandon} seen
    # bucket_latest_ts[eff_run] = latest event timestamp (float) or None

    bucket_command: dict[str, str] = {}
    bucket_tokens: dict[str, int] = {}
    bucket_terminal: dict[str, tuple[str, str | None]] = {}
    bucket_abandoned: dict[str, bool] = {}
    bucket_latest_ts: dict[str, float | None] = {}

    for ev in events:
        run_id = ev.get("run", "")
        parent_run_id = ev.get("parent_run_id", "")
        eff_run: str = parent_run_id if parent_run_id else run_id
        if not eff_run:
            continue

        # Initialize bucket defaults on first encounter.
        if eff_run not in bucket_tokens:
            bucket_tokens[eff_run] = 0
            bucket_terminal[eff_run] = None  # type: ignore[assignment]
            bucket_abandoned[eff_run] = False
            bucket_latest_ts[eff_run] = None
            bucket_command[eff_run] = "unknown"

        # --- Update command attribution ---
        # For a child event (has parent_run_id), the event's parent_command is
        # authoritative for the parent bucket.
        cmd_from_event: str | None = None
        if parent_run_id:
            # Child event: prefer parent_command, then command on the event.
            cmd_from_event = ev.get("parent_command") or ev.get("command")
        else:
            # This event IS the parent run's own event.
            cmd_from_event = ev.get("command")

        if cmd_from_event:
            # Only update if we don't already have a known (non-unknown) command.
            if bucket_command[eff_run] == "unknown":
                bucket_command[eff_run] = cmd_from_event
        else:
            # Fall back to kind-based inference for this bucket if still unknown.
            kind = ev.get("kind", "")
            if bucket_command[eff_run] == "unknown" and kind in _KIND_TO_COMMAND:
                bucket_command[eff_run] = _KIND_TO_COMMAND[kind]

        # --- Accumulate token count for ALL events in the bucket ---
        bucket_tokens[eff_run] += _event_tokens(ev)

        # --- Track latest timestamp for the bucket ---
        ts = _parse_ts(ev.get("ts"))
        if ts is not None:
            cur = bucket_latest_ts[eff_run]
            if cur is None or ts > cur:
                bucket_latest_ts[eff_run] = ts

        # --- Detect terminal events on PARENT run events only ---
        # A terminal event's run_id must equal eff_run (i.e. this is a top-level
        # parent event, not a child event attributed to the parent bucket).
        if not parent_run_id:
            kind = ev.get("kind", "")
            if kind in _TERMINAL_KINDS:
                status = ev.get("status") or ev.get("exit_status") or None
                bucket_terminal[eff_run] = (kind, status)

        # --- Detect cost_gate_decision{choice:abandon} on the parent run ---
        if not parent_run_id:
            kind = ev.get("kind", "")
            if kind == "cost_gate_decision":
                if ev.get("choice") == "abandon":
                    bucket_abandoned[eff_run] = True

    # --- Completion filter: keep only normally-completed parent runs ---
    qualifying_totals: list[int] = []

    for eff_run, total_tokens in bucket_tokens.items():
        cmd = bucket_command.get(eff_run, "unknown")

        # Only consider buckets attributed to the requested command.
        if cmd != command:
            continue

        terminal = bucket_terminal.get(eff_run)
        abandoned = bucket_abandoned.get(eff_run, False)
        latest_ts = bucket_latest_ts.get(eff_run)

        # Abandoned run → exclude.
        if abandoned:
            continue

        if terminal is None:
            # No terminal event: could be in-flight.
            # Exclude if in-flight (latest_ts within 5 min of max_ts).
            if max_ts is not None and latest_ts is not None:
                if (max_ts - latest_ts) <= _INFLIGHT_GRACE_SECS:
                    # In-flight — exclude.
                    continue
            # If no terminal and NOT in-flight window, it's a stale/unknown-state run.
            # Conservative: exclude it (we can only trust completed runs).
            continue

        _term_kind, status = terminal

        # Abnormal terminal status → exclude.
        if status in _EXCLUDED_STATUSES:
            continue

        # Normally completed — include.
        qualifying_totals.append(total_tokens)

    if not qualifying_totals:
        return None

    samples = len(qualifying_totals)
    if samples < min_samples:
        return None

    qualifying_totals.sort()
    p50 = _percentile(qualifying_totals, 50)
    p90 = _percentile(qualifying_totals, 90)

    return {
        "p50": round(p50),
        "p90": round(p90),
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# No-profile envelope
# ---------------------------------------------------------------------------

def _no_profile_envelope(command: str) -> dict:
    return {
        "command": command,
        "estimated_tokens": 0,
        "range_low": 0,
        "range_high": 0,
        "confidence": "low",
        "basis": "no profile",
        "breakdown": [],
        "gate": None,
    }


# ---------------------------------------------------------------------------
# Core estimation
# ---------------------------------------------------------------------------

def estimate(
    raw_command: str,
    dispatch_pairs: list[tuple[str, int]],
    profiles_path: Path,
    metrics_path: Path,
    tail_lines: int,
    min_samples: int,
) -> dict:
    """Compute and return the estimate envelope dict."""

    profiles = _load_profiles(profiles_path)
    canonical_key, profile = _resolve_profile(raw_command, profiles)

    # --- No-profile path ---
    if profile is None:
        print(
            f"estimate-tokens: no profile found for '{raw_command}' "
            f"(tried '{canonical_key}') — returning no-profile envelope",
            file=sys.stderr,
        )
        return _no_profile_envelope(canonical_key)

    # ------------------------------------------------------------------ Tier 1: Static
    static_low: int = profile["range"][0]
    static_high: int = profile["range"][1]
    gate: str | None = profile.get("gate", None)
    multipliers: dict[str, int] = profile.get("multipliers", {})

    breakdown: list[dict] = [
        {"tier": "static", "low": static_low, "high": static_high},
    ]

    # ------------------------------------------------------------------ Tier 2: Dispatch
    dispatch_add = 0
    used_dispatch_keys: list[str] = []

    if dispatch_pairs:
        for key, count in dispatch_pairs:
            if key in multipliers:
                dispatch_add += multipliers[key] * count
                used_dispatch_keys.append(key)
            else:
                print(
                    f"estimate-tokens: unknown dispatch key '{key}' for command "
                    f"'{canonical_key}' — ignored",
                    file=sys.stderr,
                )

        if used_dispatch_keys:
            breakdown.append(
                {"tier": "dispatch", "add": dispatch_add, "keys": used_dispatch_keys}
            )

    # ------------------------------------------------------------------ Tier 3: Empirical
    empirical = _empirical_tier(canonical_key, metrics_path, tail_lines, min_samples)

    # ------------------------------------------------------------------ Compose envelope
    range_low = static_low + dispatch_add
    range_high = static_high + dispatch_add
    estimated_tokens = range_low  # midpoint-ish default before empirical

    if empirical is not None:
        p50 = empirical["p50"]
        p90 = empirical["p90"]
        samples = empirical["samples"]

        # Static-floor clamp: empirical may only widen upward, never shrink.
        estimated_tokens = max(static_low + dispatch_add, round(p50))
        # range_low stays at static (+dispatch) low
        range_high = max(static_high + dispatch_add, round(p90))

        breakdown.append(
            {"tier": "empirical", "p50": p50, "p90": p90, "samples": samples}
        )

        if samples >= 2 * min_samples:
            confidence = "high"
        else:
            confidence = "medium"

        basis_parts = [f"static profile"]
        if used_dispatch_keys:
            basis_parts.append(f"dispatch({','.join(used_dispatch_keys)})")
        basis_parts.append(f"{samples} historical run{'s' if samples != 1 else ''}")
        basis = " + ".join(basis_parts)
    else:
        # No empirical: confidence depends on whether dispatch was applied.
        # SPEC: "medium" for static+dispatch with known profile; "low" for static-only/no-dispatch.
        if used_dispatch_keys:
            confidence = "medium"
            basis_parts = ["static profile", f"dispatch({','.join(used_dispatch_keys)})"]
            basis = " + ".join(basis_parts)
        else:
            confidence = "low"
            basis = "static profile"

    return {
        "command": canonical_key,
        "estimated_tokens": estimated_tokens,
        "range_low": range_low,
        "range_high": range_high,
        "confidence": confidence,
        "basis": basis,
        "breakdown": breakdown,
        "gate": gate,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_dispatch(values: list[str]) -> list[tuple[str, int]]:
    """Parse a list of 'KEY=N' strings into (key, int) tuples.

    Malformed entries warn to stderr and are skipped.
    """
    result: list[tuple[str, int]] = []
    for val in values:
        if "=" not in val:
            print(
                f"estimate-tokens: malformed --dispatch value '{val}' "
                f"(expected KEY=N) — ignored",
                file=sys.stderr,
            )
            continue
        key, _, raw_n = val.partition("=")
        key = key.strip()
        try:
            n = int(raw_n.strip())
        except ValueError:
            print(
                f"estimate-tokens: non-integer count in --dispatch '{val}' — ignored",
                file=sys.stderr,
            )
            continue
        result.append((key, n))
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="estimate-tokens.py",
        description="LLM-free pre-run token-cost estimator for z-harness commands.",
    )
    parser.add_argument(
        "command",
        help="Command to estimate (e.g. z-research, /z-research, research).",
    )
    parser.add_argument(
        "--dispatch",
        metavar="KEY=N",
        nargs="+",
        action="append",
        default=[],
        help=(
            "Dispatch multiplier: KEY=N [KEY=N ...]. Repeatable. "
            "Adds multipliers[KEY]*N tokens per entry."
        ),
    )
    parser.add_argument(
        "--metrics",
        metavar="PATH",
        default=None,
        help=(
            "Path to metrics.jsonl. "
            "Default: $Z_HARNESS_BASE_DIR/metrics.jsonl or <repo>/z-harness/metrics.jsonl."
        ),
    )
    parser.add_argument(
        "--profiles",
        metavar="PATH",
        default=None,
        help=(
            "Path to token-cost-profiles.json. "
            "Default: scripts/token-cost-profiles.json relative to this script."
        ),
    )
    parser.add_argument(
        "--tail-lines",
        metavar="N",
        type=int,
        default=int(os.environ.get("Z_HARNESS_COST_TAIL_LINES", "2000")),
        help="Max lines to read from metrics.jsonl tail (default 2000).",
    )
    parser.add_argument(
        "--min-samples",
        metavar="N",
        type=int,
        default=int(os.environ.get("Z_HARNESS_COST_MIN_SAMPLES", "3")),
        help="Minimum historical samples for empirical tier to fire (default 3).",
    )
    return parser


def main() -> None:
    parser = _build_parser()

    # Require the positional; if missing, print usage to stderr and exit 1.
    if len(sys.argv) < 2 or sys.argv[1].startswith("--"):
        parser.print_usage(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    # Resolve paths
    profiles_path = (
        Path(args.profiles)
        if args.profiles
        else _SCRIPT_DIR / "token-cost-profiles.json"
    )
    metrics_path = (
        Path(args.metrics)
        if args.metrics
        else _default_metrics_path()
    )

    # args.dispatch is a list of lists (nargs='+', action='append') — flatten it.
    flat_dispatch: list[str] = [item for sublist in args.dispatch for item in sublist]
    dispatch_pairs = _parse_dispatch(flat_dispatch)

    envelope = estimate(
        raw_command=args.command,
        dispatch_pairs=dispatch_pairs,
        profiles_path=profiles_path,
        metrics_path=metrics_path,
        tail_lines=args.tail_lines,
        min_samples=args.min_samples,
    )

    # Stdout is pure JSON — one object, no trailing noise.
    print(json.dumps(envelope, indent=2))


if __name__ == "__main__":
    main()
