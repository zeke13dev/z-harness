#!/usr/bin/env python3
"""
estimate-tokens.py — LLM-free pre-run token-cost estimator + subagent cost model.

CLI:
  # Pre-run estimate (legacy positional form — backward-compatible):
  estimate-tokens.py <command> [--dispatch KEY=N ...] [--metrics PATH]
                     [--profiles PATH] [--tail-lines N] [--min-samples N]

  # Explicit estimate subcommand:
  estimate-tokens.py estimate <command> [--dispatch KEY=N ...] [...]

  # Explicit E2E forecast mode (plan cost + projected execute cost):
  estimate-tokens.py forecast <command> [--dispatch KEY=N ...] [...]
  estimate-tokens.py estimate <command> --e2e-forecast [--dispatch KEY=N ...] [...]

  # Per-host, per-subagent_type cost breakdown from logged subagent_call events:
  estimate-tokens.py subagent-costs [--metrics PATH] [--tail-lines N] [--json]

Estimate subcommand stdout: a single JSON envelope (see SPEC "Output envelope").
Forecast subcommand stdout: a single JSON object with plan, execute, and total forecast fields.
Subagent-costs stdout: human-readable table (default) or JSON (with --json).
Stderr: all diagnostics/warnings.
Exit 0 on any producible output; exit non-zero only if required arg is missing.

Estimate tiers:
  1. Static  — reads profile range from token-cost-profiles.json.
  2. Dispatch — adds Σ multipliers[key]*N. Profiles may declare
                 dispatch_defaults for fail-closed pre-gate estimates; explicit
                 --dispatch values replace the default for that key.
  3. Empirical — parent-run rollup from metrics.jsonl (bounded, race-safe,
                 completion-filtered).

Subagent-costs model (SOLID — pricing lives here, telemetry stays raw):
  Reads subagent_call events from metrics.jsonl; weights prompt_chars vs
  response_chars by per-model input/output rates; groups by host + subagent_type.
  Honest limitation: native Claude subagents expose chars, not token counts.
  provider_input_tokens/provider_output_tokens are used when present (external CLIs).
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
      1. $Z_HARNESS_BASE_DIR/metrics.jsonl if env set.
      2. Canonical external base via `bash scripts/plan-path.sh base_dir` (subprocess
         from repo root) — this is the repo-wide base that receives ALL events including
         subagent_call events after the Phase-D external-base flip.
      3. <repo>/z-harness/metrics.jsonl as legacy fallback if subprocess fails.
    """
    base_dir_env = os.environ.get("Z_HARNESS_BASE_DIR", "")
    if base_dir_env:
        candidate = Path(base_dir_env) / "metrics.jsonl"
        return candidate  # return even if absent — caller handles missing file

    # Resolve the repo-wide base via the canonical plan-path.sh helper.
    # This is the external base (e.g. ~/.local/state/z-harness/<repo-id>/) that
    # holds the single repo-wide metrics.jsonl after the Phase-D external-base flip.
    # There is NO per-plan metrics.jsonl; all events including subagent_call land here.
    repo = _repo_root()
    try:
        plan_path_script = repo / "scripts" / "plan-path.sh"
        result = subprocess.run(
            ["bash", str(plan_path_script), "base_dir"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(repo),
        )
        base_str = result.stdout.strip()
        if result.returncode == 0 and base_str:
            return Path(base_str) / "metrics.jsonl"
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError, ValueError):
        pass

    # Legacy fallback: in-repo z-harness/ path (pre-external-base layout).
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
# Subagent cost model — per-model input/output rates
#
# SOLID: pricing knowledge lives ONLY here (read-side cost model).
# Telemetry stays raw (prompt_chars / response_chars kept separate per D9).
#
# Rates are in USD per 1M tokens (industry standard).
# The chars→tokens conversion uses chars/4 (rough approximation for native
# Claude subagents where real token counts are unavailable).  This is labeled
# as a char-based estimate wherever it surfaces in output.
#
# When provider_input_tokens / provider_output_tokens are present in the event
# (external CLIs that print a usage line), those are used directly instead
# of the chars/4 approximation.
# ---------------------------------------------------------------------------

# Default rates: USD per 1M tokens.
# Format: {model_label: {"input": float, "output": float}}
# Output is typically ~5× input price (D9 rationale).
# Haiku/flash are cheap; Sonnet is mid; Opus is expensive.
_DEFAULT_MODEL_RATES: dict[str, dict[str, float]] = {
    # Claude family
    "haiku":        {"input": 0.25,   "output": 1.25},
    "sonnet":       {"input": 3.00,   "output": 15.00},
    "opus":         {"input": 15.00,  "output": 75.00},
    # Aliases / variant names
    "claude-haiku":  {"input": 0.25,  "output": 1.25},
    "claude-sonnet": {"input": 3.00,  "output": 15.00},
    "claude-opus":   {"input": 15.00, "output": 75.00},
    # OpenAI / Codex family
    "gpt-4o":       {"input": 2.50,   "output": 10.00},
    "gpt-4o-mini":  {"input": 0.15,   "output": 0.60},
    "gpt-4":        {"input": 30.00,  "output": 60.00},
    "gpt-3.5":      {"input": 0.50,   "output": 1.50},
    # Google / Gemini family
    "gemini":        {"input": 0.35,  "output": 1.05},
    "gemini-flash":  {"input": 0.075, "output": 0.30},
    "gemini-pro":    {"input": 1.25,  "output": 5.00},
    # DeepSeek
    "deepseek":      {"input": 0.14,  "output": 0.28},
    "deepseek-flash":{"input": 0.07,  "output": 0.14},
}

# Fallback rate when model label is unknown.
_FALLBACK_RATE: dict[str, float] = {"input": 3.00, "output": 15.00}

_CHARS_PER_TOKEN: float = 4.0


def _get_model_rates(model_label: str | None) -> dict[str, float]:
    """Return {input, output} USD/1M-token rates for a model label.

    Matching is case-insensitive; partial prefix match is attempted when exact
    match fails.  Falls back to _FALLBACK_RATE for unknown models.
    """
    if not model_label:
        return _FALLBACK_RATE

    # Exact match (case-insensitive)
    normalized = model_label.lower().strip()
    if normalized in _DEFAULT_MODEL_RATES:
        return _DEFAULT_MODEL_RATES[normalized]

    # Prefix match: find the longest key that is a prefix of the label.
    best_key = ""
    for key in _DEFAULT_MODEL_RATES:
        if normalized.startswith(key) and len(key) > len(best_key):
            best_key = key
    if best_key:
        return _DEFAULT_MODEL_RATES[best_key]

    return _FALLBACK_RATE


def _compute_event_cost(event: dict) -> dict:
    """Compute input/output token counts and estimated cost for a subagent_call event.

    Returns a dict with:
      input_tokens  — int (from provider_input_tokens if present, else prompt_chars/4)
      output_tokens — int (from provider_output_tokens if present, else response_chars/4)
      est_input_usd — float (input_tokens / 1e6 * input_rate)
      est_output_usd — float (output_tokens / 1e6 * output_rate)
      est_total_usd — float (est_input_usd + est_output_usd)
      token_source  — "provider" | "chars"  (label per SPEC honest-limitation requirement)
    """
    def _safe_int(v: object) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    model_label: str | None = event.get("subagent_model")
    rates = _get_model_rates(model_label)

    # Prefer real provider tokens when available (external CLIs that print usage).
    provider_in = _safe_int(event.get("provider_input_tokens"))
    provider_out = _safe_int(event.get("provider_output_tokens"))

    if provider_in is not None and provider_out is not None:
        input_tokens = provider_in
        output_tokens = provider_out
        token_source = "provider"
    else:
        # Fall back to chars/4 approximation (native Claude subagents).
        pc = _safe_int(event.get("prompt_chars"))
        rc = _safe_int(event.get("response_chars"))
        input_tokens = int((pc or 0) / _CHARS_PER_TOKEN)
        output_tokens = int((rc or 0) / _CHARS_PER_TOKEN)
        token_source = "chars"

    est_input_usd = (input_tokens / 1_000_000.0) * rates["input"]
    est_output_usd = (output_tokens / 1_000_000.0) * rates["output"]
    est_total_usd = est_input_usd + est_output_usd

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "est_input_usd": est_input_usd,
        "est_output_usd": est_output_usd,
        "est_total_usd": est_total_usd,
        "token_source": token_source,
    }


def subagent_costs(
    metrics_path: Path,
    tail_lines: int = 5000,
) -> dict:
    """Compute per-host, per-subagent_type cost breakdown from metrics.jsonl.

    Returns a dict with shape:
      {
        "by_host": {
          "<host>": {
            "<subagent_type>": {
              "calls": int,
              "input_tokens": int,
              "output_tokens": int,
              "est_input_usd": float,
              "est_output_usd": float,
              "est_total_usd": float,
              "token_source_mix": {"provider": int, "chars": int},
            }
          }
        },
        "totals": {
          "calls": int,
          "input_tokens": int,
          "output_tokens": int,
          "est_input_usd": float,
          "est_output_usd": float,
          "est_total_usd": float,
        },
        "has_provider_tokens": bool,   # True if any event had real provider tokens
        "events_read": int,
        "subagent_call_events": int,
      }

    Returns an empty-result dict if metrics_path is absent or contains no
    subagent_call events.
    """
    empty: dict = {
        "by_host": {},
        "totals": {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "est_input_usd": 0.0,
            "est_output_usd": 0.0,
            "est_total_usd": 0.0,
        },
        "has_provider_tokens": False,
        "events_read": 0,
        "subagent_call_events": 0,
    }

    if not metrics_path.exists():
        return empty

    try:
        with open(metrics_path, encoding="utf-8", errors="replace") as fh:
            raw_lines = fh.readlines()
    except OSError as exc:
        print(
            f"estimate-tokens: error reading metrics file {metrics_path}: {exc}",
            file=sys.stderr,
        )
        return empty

    lines = raw_lines[-tail_lines:] if len(raw_lines) > tail_lines else raw_lines

    # Parse events
    events_read = 0
    by_host: dict[str, dict[str, dict]] = {}
    totals: dict[str, float | int] = {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "est_input_usd": 0.0,
        "est_output_usd": 0.0,
        "est_total_usd": 0.0,
    }
    has_provider_tokens = False
    subagent_call_count = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue

        events_read += 1

        if obj.get("kind") != "subagent_call":
            continue

        subagent_call_count += 1
        host: str = obj.get("host", "unknown") or "unknown"
        subagent_type: str = obj.get("subagent_type", "unknown") or "unknown"

        cost = _compute_event_cost(obj)

        if cost["token_source"] == "provider":
            has_provider_tokens = True

        # Accumulate into by_host[host][subagent_type]
        if host not in by_host:
            by_host[host] = {}
        if subagent_type not in by_host[host]:
            by_host[host][subagent_type] = {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "est_input_usd": 0.0,
                "est_output_usd": 0.0,
                "est_total_usd": 0.0,
                "token_source_mix": {"provider": 0, "chars": 0},
            }

        bucket = by_host[host][subagent_type]
        bucket["calls"] += 1
        bucket["input_tokens"] += cost["input_tokens"]
        bucket["output_tokens"] += cost["output_tokens"]
        bucket["est_input_usd"] += cost["est_input_usd"]
        bucket["est_output_usd"] += cost["est_output_usd"]
        bucket["est_total_usd"] += cost["est_total_usd"]
        bucket["token_source_mix"][cost["token_source"]] += 1

        # Accumulate totals
        totals["calls"] = int(totals["calls"]) + 1  # type: ignore[assignment]
        totals["input_tokens"] = int(totals["input_tokens"]) + cost["input_tokens"]  # type: ignore
        totals["output_tokens"] = int(totals["output_tokens"]) + cost["output_tokens"]  # type: ignore
        totals["est_input_usd"] = float(totals["est_input_usd"]) + cost["est_input_usd"]  # type: ignore
        totals["est_output_usd"] = float(totals["est_output_usd"]) + cost["est_output_usd"]  # type: ignore
        totals["est_total_usd"] = float(totals["est_total_usd"]) + cost["est_total_usd"]  # type: ignore

    return {
        "by_host": by_host,
        "totals": totals,
        "has_provider_tokens": has_provider_tokens,
        "events_read": events_read,
        "subagent_call_events": subagent_call_count,
    }


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

        # Normally completed with observable token data — include. A zero total
        # means the run had no token telemetry in the tail, not that it was free.
        if total_tokens <= 0:
            continue
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
# Dispatch contract helpers
# ---------------------------------------------------------------------------

def _coerce_nonnegative_count(value: object, *, key: str, source: str) -> int | None:
    """Return a non-negative dispatch count, warning and skipping invalid values."""
    try:
        count = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        print(
            f"estimate-tokens: non-integer dispatch count for '{key}' in {source} — ignored",
            file=sys.stderr,
        )
        return None
    if count < 0:
        print(
            f"estimate-tokens: negative dispatch count for '{key}' in {source} — ignored",
            file=sys.stderr,
        )
        return None
    return count


def _dispatch_defaults(profile: dict, multipliers: dict[str, int], command: str) -> dict[str, int]:
    """Return validated profile-declared default dispatch counts.

    Defaults are used for commands such as /z-plan where the pre-run gate happens
    before some fan-out is known. They must be conservative; explicit dispatch
    values replace the default for that key.
    """
    raw_defaults = profile.get("dispatch_defaults", {})
    if not isinstance(raw_defaults, dict):
        print(
            f"estimate-tokens: dispatch_defaults for '{command}' is not an object — ignored",
            file=sys.stderr,
        )
        return {}

    defaults: dict[str, int] = {}
    for key, raw_count in raw_defaults.items():
        if key not in multipliers:
            print(
                f"estimate-tokens: default dispatch key '{key}' for command "
                f"'{command}' has no multiplier — ignored",
                file=sys.stderr,
            )
            continue
        count = _coerce_nonnegative_count(raw_count, key=key, source=f"profile '{command}'")
        if count is not None:
            defaults[key] = count
    return defaults


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
    used_dispatch_counts: dict[str, int] = {}
    defaulted_dispatch_keys: list[str] = []

    # Profile defaults let a gate fail closed when /z-plan has not yet learned
    # all shape drivers. Explicit values replace the default for that key.
    applied_dispatch_counts = _dispatch_defaults(profile, multipliers, canonical_key)
    explicit_dispatch_counts: dict[str, int] = {}

    if dispatch_pairs:
        for key, count in dispatch_pairs:
            if key in multipliers:
                safe_count = _coerce_nonnegative_count(count, key=key, source="--dispatch")
                if safe_count is None:
                    continue
                explicit_dispatch_counts[key] = explicit_dispatch_counts.get(key, 0) + safe_count
            else:
                print(
                    f"estimate-tokens: unknown dispatch key '{key}' for command "
                    f"'{canonical_key}' — ignored",
                    file=sys.stderr,
                )

    for key, count in explicit_dispatch_counts.items():
        applied_dispatch_counts[key] = count

    for key, count in applied_dispatch_counts.items():
        if count <= 0:
            continue
        multiplier = int(multipliers[key])
        dispatch_add += multiplier * count
        used_dispatch_keys.append(key)
        used_dispatch_counts[key] = count
        if key not in explicit_dispatch_counts:
            defaulted_dispatch_keys.append(key)

    if used_dispatch_keys:
        breakdown.append(
            {
                "tier": "dispatch",
                "add": dispatch_add,
                "keys": used_dispatch_keys,
                "counts": used_dispatch_counts,
                "defaults": defaulted_dispatch_keys,
            }
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
# E2E forecast — explicit plan + execute forecast surface
# ---------------------------------------------------------------------------

_CONFIDENCE_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def _weaker_confidence(left: str, right: str) -> str:
    """Return the less certain confidence label, preserving known low/medium/high labels."""
    left_rank = _CONFIDENCE_RANK.get(left, 0)
    right_rank = _CONFIDENCE_RANK.get(right, 0)
    return left if left_rank <= right_rank else right


def _uncertainty_for(confidence: str, *, source: str) -> str:
    """Return a stable machine-readable uncertainty label for forecast consumers."""
    if confidence == "high":
        return "narrow_empirical"
    if confidence == "medium":
        return "moderate_composite"
    if source == "missing_profile":
        return "unknown_no_profile"
    return "wide_static_fallback"


def _component_from_estimate(
    envelope: dict,
    *,
    component: str,
    semantics: str,
    source: str,
    user_facing_wording: str,
) -> dict:
    """Adapt an existing estimate envelope into an E2E forecast component."""
    confidence = str(envelope.get("confidence", "low"))
    return {
        "component": component,
        "semantics": semantics,
        "source": source,
        "command": envelope.get("command"),
        "estimated_tokens": int(envelope.get("estimated_tokens") or 0),
        "range_low": int(envelope.get("range_low") or 0),
        "range_high": int(envelope.get("range_high") or 0),
        "confidence": confidence,
        "uncertainty": _uncertainty_for(confidence, source=source),
        "basis": envelope.get("basis", "unknown"),
        "breakdown": envelope.get("breakdown", []),
        "user_facing_wording": user_facing_wording,
    }


def _coerce_forecast_range(raw_range: object, *, command: str) -> tuple[int, int]:
    """Return a non-negative (low, high) range from profile forecast config."""
    if (
        isinstance(raw_range, list)
        and len(raw_range) == 2
    ):
        try:
            low = max(0, int(raw_range[0]))
            high = max(0, int(raw_range[1]))
            if high < low:
                high = low
            return low, high
        except (TypeError, ValueError):
            pass
    print(
        f"estimate-tokens: malformed e2e_forecast.execute_forecast.range "
        f"for '{command}' — using [0, 0]",
        file=sys.stderr,
    )
    return 0, 0


def _static_execute_forecast_component(command: str, config: dict) -> dict:
    """Build a static fallback execute component from profile e2e_forecast config."""
    low, high = _coerce_forecast_range(config.get("range", [0, 0]), command=command)
    try:
        estimated = int(config.get("estimated_tokens", low))
    except (TypeError, ValueError):
        estimated = low
    estimated = min(max(low, estimated), high) if high else max(low, estimated)
    confidence = str(config.get("confidence", "low"))
    basis = str(config.get("basis", "static e2e execute forecast profile"))
    uncertainty = str(config.get("uncertainty", _uncertainty_for(confidence, source="static_forecast")))
    wording = str(config.get(
        "user_facing_wording",
        "Execute forecast is approximate, not exact, and not a hard cap.",
    ))
    return {
        "component": "execute_forecast",
        "semantics": "forecast_execute_after_plan",
        "source": "static_forecast_profile",
        "command": config.get("command", "z-execute"),
        "estimated_tokens": estimated,
        "range_low": low,
        "range_high": high,
        "confidence": confidence,
        "uncertainty": uncertainty,
        "basis": basis,
        "breakdown": [{"tier": "static_forecast", "low": low, "high": high}],
        "user_facing_wording": wording,
    }


def forecast_e2e(
    raw_command: str,
    dispatch_pairs: list[tuple[str, int]],
    profiles_path: Path,
    metrics_path: Path,
    tail_lines: int,
    min_samples: int,
) -> dict:
    """Compute an explicit E2E forecast: cost-to-plan plus forecast execute cost."""
    plan_envelope = estimate(
        raw_command=raw_command,
        dispatch_pairs=dispatch_pairs,
        profiles_path=profiles_path,
        metrics_path=metrics_path,
        tail_lines=tail_lines,
        min_samples=min_samples,
    )

    profiles = _load_profiles(profiles_path)
    canonical_key, profile = _resolve_profile(raw_command, profiles)
    forecast_config = profile.get("e2e_forecast", {}) if isinstance(profile, dict) else {}
    if not isinstance(forecast_config, dict):
        forecast_config = {}

    execute_config = forecast_config.get("execute_forecast", {})
    if not isinstance(execute_config, dict):
        execute_config = {}

    plan_component = _component_from_estimate(
        plan_envelope,
        component="plan",
        semantics="cost_to_plan_only",
        source="estimate_envelope",
        user_facing_wording="Plan component is the estimated cost to produce the plan only.",
    )

    execute_command = execute_config.get("command")
    execute_profile_exists = False
    if isinstance(execute_command, str) and execute_command:
        _, execute_profile = _resolve_profile(execute_command, profiles)
        execute_profile_exists = execute_profile is not None

    if execute_profile_exists:
        execute_envelope = estimate(
            raw_command=str(execute_command),
            dispatch_pairs=[],
            profiles_path=profiles_path,
            metrics_path=metrics_path,
            tail_lines=tail_lines,
            min_samples=min_samples,
        )
        execute_component = _component_from_estimate(
            execute_envelope,
            component="execute_forecast",
            semantics="forecast_execute_after_plan",
            source="estimate_profile",
            user_facing_wording=str(execute_config.get(
                "user_facing_wording",
                "Execute forecast is approximate, not exact, and not a hard cap.",
            )),
        )
    else:
        execute_component = _static_execute_forecast_component(canonical_key, execute_config)

    total_confidence = _weaker_confidence(
        str(plan_component["confidence"]),
        str(execute_component["confidence"]),
    )
    total_estimated = int(plan_component["estimated_tokens"]) + int(execute_component["estimated_tokens"])
    total_low = int(plan_component["range_low"]) + int(execute_component["range_low"])
    total_high = int(plan_component["range_high"]) + int(execute_component["range_high"])
    total_basis = f"{plan_component['basis']} + {execute_component['basis']}"

    return {
        "schema_version": "e2e_forecast.v1",
        "mode": "e2e_forecast",
        "command": plan_component["command"],
        "estimated_tokens": total_estimated,
        "range_low": total_low,
        "range_high": total_high,
        "gate": plan_envelope.get("gate"),
        "plan_estimate_envelope": plan_envelope,
        "range_semantics": (
            "Component range_low/range_high values are token ranges for that component. "
            "total_forecast ranges are the sum of component lows/highs; "
            "total_forecast.estimated_tokens is the sum of component point estimates."
        ),
        "confidence": total_confidence,
        "uncertainty": _uncertainty_for(total_confidence, source="total_forecast"),
        "basis": total_basis,
        "user_facing_wording": (
            "Approximate E2E forecast: plan_component is cost-to-plan only; "
            "execute_forecast_component is projected post-plan execution cost. "
            "This is not exact and is not a hard cap."
        ),
        "plan_component": plan_component,
        "execute_forecast_component": execute_component,
        "total_forecast": {
            "semantics": "forecast_plan_plus_execute",
            "estimated_tokens": total_estimated,
            "range_low": total_low,
            "range_high": total_high,
            "confidence": total_confidence,
            "uncertainty": _uncertainty_for(total_confidence, source="total_forecast"),
            "basis": total_basis,
        },
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
        if n < 0:
            print(
                f"estimate-tokens: negative count in --dispatch '{val}' — ignored",
                file=sys.stderr,
            )
            continue
        result.append((key, n))
    return result


def _build_estimate_parser(subparsers: argparse.Action) -> None:  # type: ignore[type-arg]
    """Add the 'estimate' subcommand (default mode — pre-run token estimate)."""
    ep = subparsers.add_parser(
        "estimate",
        help="Pre-run token estimate for a command (default subcommand).",
        description="LLM-free pre-run token-cost estimate for a z-harness command.",
    )
    ep.add_argument(
        "command",
        help="Command to estimate (e.g. z-research, /z-research, research).",
    )
    ep.add_argument(
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
    ep.add_argument(
        "--metrics",
        metavar="PATH",
        default=None,
        help=(
            "Path to metrics.jsonl. "
            "Default: $Z_HARNESS_BASE_DIR/metrics.jsonl or <repo>/z-harness/metrics.jsonl."
        ),
    )
    ep.add_argument(
        "--profiles",
        metavar="PATH",
        default=None,
        help=(
            "Path to token-cost-profiles.json. "
            "Default: scripts/token-cost-profiles.json relative to this script."
        ),
    )
    ep.add_argument(
        "--tail-lines",
        metavar="N",
        type=int,
        default=int(os.environ.get("Z_HARNESS_COST_TAIL_LINES", "2000")),
        help="Max lines to read from metrics.jsonl tail (default 2000).",
    )
    ep.add_argument(
        "--min-samples",
        metavar="N",
        type=int,
        default=int(os.environ.get("Z_HARNESS_COST_MIN_SAMPLES", "3")),
        help="Minimum historical samples for empirical tier to fire (default 3).",
    )
    ep.add_argument(
        "--e2e-forecast",
        action="store_true",
        default=False,
        help=(
            "Output the explicit E2E forecast schema instead of the legacy estimate envelope. "
            "Default estimate output remains backward-compatible when this flag is absent."
        ),
    )



def _build_forecast_parser(subparsers: argparse.Action) -> None:  # type: ignore[type-arg]
    """Add the 'forecast' subcommand (E2E plan + execute forecast)."""
    fp = subparsers.add_parser(
        "forecast",
        help="E2E forecast for a command: cost-to-plan plus projected execute cost.",
        description=(
            "LLM-free E2E token forecast for a z-harness command. "
            "Outputs explicit plan_component, execute_forecast_component, and total_forecast fields."
        ),
    )
    fp.add_argument(
        "command",
        help="Command to forecast (e.g. z-plan, /z-plan, plan).",
    )
    fp.add_argument(
        "--dispatch",
        metavar="KEY=N",
        nargs="+",
        action="append",
        default=[],
        help=(
            "Dispatch multiplier for the plan component: KEY=N [KEY=N ...]. Repeatable. "
            "Adds multipliers[KEY]*N tokens per entry."
        ),
    )
    fp.add_argument(
        "--metrics",
        metavar="PATH",
        default=None,
        help=(
            "Path to metrics.jsonl. "
            "Default: $Z_HARNESS_BASE_DIR/metrics.jsonl or <repo>/z-harness/metrics.jsonl."
        ),
    )
    fp.add_argument(
        "--profiles",
        metavar="PATH",
        default=None,
        help=(
            "Path to token-cost-profiles.json. "
            "Default: scripts/token-cost-profiles.json relative to this script."
        ),
    )
    fp.add_argument(
        "--tail-lines",
        metavar="N",
        type=int,
        default=int(os.environ.get("Z_HARNESS_COST_TAIL_LINES", "2000")),
        help="Max lines to read from metrics.jsonl tail (default 2000).",
    )
    fp.add_argument(
        "--min-samples",
        metavar="N",
        type=int,
        default=int(os.environ.get("Z_HARNESS_COST_MIN_SAMPLES", "3")),
        help="Minimum historical samples for empirical tier to fire (default 3).",
    )

def _build_subagent_costs_parser(subparsers: argparse.Action) -> None:  # type: ignore[type-arg]
    """Add the 'subagent-costs' subcommand (per-host, per-type cost breakdown)."""
    sp = subparsers.add_parser(
        "subagent-costs",
        help=(
            "Per-host, per-subagent_type cost breakdown from logged subagent_call events. "
            "Weights prompt_chars vs response_chars by per-model input/output rates."
        ),
        description=(
            "Read subagent_call events from metrics.jsonl and compute per-host, "
            "per-subagent_type cost estimates using separated input/output rate weighting.\n\n"
            "HONEST LIMITATION: native Claude Agent() subagents do not expose real token "
            "counts to the orchestrator — only dispatch-prompt size and returned-text size "
            "are observable. prompt_chars/response_chars are exact character counts; "
            "real provider_*_tokens appear only for external CLIs that print a usage line. "
            "Estimates labeled 'chars' are char-based approximations (chars/4 → tokens)."
        ),
    )
    sp.add_argument(
        "--metrics",
        metavar="PATH",
        default=None,
        help=(
            "Path to metrics.jsonl. "
            "Default: $Z_HARNESS_BASE_DIR/metrics.jsonl or <repo>/z-harness/metrics.jsonl."
        ),
    )
    sp.add_argument(
        "--tail-lines",
        metavar="N",
        type=int,
        default=int(os.environ.get("Z_HARNESS_COST_TAIL_LINES", "5000")),
        help="Max lines to read from metrics.jsonl tail (default 5000).",
    )
    sp.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output raw JSON instead of the human-readable table.",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser.

    Supports three modes:
      1. Legacy positional mode: estimate-tokens.py <command> [opts]
         (positional arg that doesn't match a subcommand — treated as 'estimate <command>')
      2. Subcommand mode: estimate-tokens.py estimate <command> [opts]
                          estimate-tokens.py forecast <command> [opts]
                          estimate-tokens.py subagent-costs [opts]
    """
    parser = argparse.ArgumentParser(
        prog="estimate-tokens.py",
        description=(
            "LLM-free pre-run token-cost estimator and E2E forecaster for z-harness commands. "
            "Also provides per-host, per-subagent_type cost breakdown via 'subagent-costs'."
        ),
    )
    subparsers = parser.add_subparsers(dest="subcommand")
    _build_estimate_parser(subparsers)
    _build_forecast_parser(subparsers)
    _build_subagent_costs_parser(subparsers)
    # Legacy positional (backwards-compat): first arg is command name, not a subcommand
    parser.add_argument(
        "--metrics",
        metavar="PATH",
        default=None,
        help="Path to metrics.jsonl (used when no subcommand is given).",
    )
    parser.add_argument(
        "--profiles",
        metavar="PATH",
        default=None,
        help="Path to token-cost-profiles.json (used when no subcommand is given).",
    )
    parser.add_argument(
        "--dispatch",
        metavar="KEY=N",
        nargs="+",
        action="append",
        default=[],
        help="Dispatch multiplier (used when no subcommand is given).",
    )
    parser.add_argument(
        "--tail-lines",
        metavar="N",
        type=int,
        default=int(os.environ.get("Z_HARNESS_COST_TAIL_LINES", "2000")),
        help="Max lines to read (used when no subcommand is given).",
    )
    parser.add_argument(
        "--min-samples",
        metavar="N",
        type=int,
        default=int(os.environ.get("Z_HARNESS_COST_MIN_SAMPLES", "3")),
        help="Minimum historical samples (used when no subcommand is given).",
    )
    parser.add_argument(
        "--e2e-forecast",
        action="store_true",
        default=False,
        help="Output E2E forecast schema (used when no subcommand is given).",
    )
    return parser


def _format_subagent_costs_table(result: dict) -> str:
    """Format the subagent_costs result as a human-readable table for z-stats.

    Returns a multi-line string with per-host, per-subagent_type cost breakdown,
    with honest-limitation labeling where provider tokens are absent.
    """
    lines: list[str] = []

    if result["subagent_call_events"] == 0:
        lines.append("Subagent cost breakdown: (no subagent_call events in metrics)")
        return "\n".join(lines)

    has_provider = result["has_provider_tokens"]
    token_note = (
        "(real tokens)"
        if has_provider
        else "(char-based estimate: chars/4 → tokens; no native-Claude token counts available)"
    )

    lines.append(f"Subagent cost breakdown {token_note}")
    lines.append(
        f"  Events: {result['subagent_call_events']} subagent_call "
        f"(of {result['events_read']} total read)"
    )
    lines.append("")

    by_host = result["by_host"]
    for host in sorted(by_host.keys()):
        lines.append(f"  Host: {host}")
        type_data = by_host[host]
        for stype in sorted(type_data.keys()):
            bucket = type_data[stype]
            src_mix = bucket["token_source_mix"]
            src_label = ""
            if src_mix.get("provider", 0) > 0 and src_mix.get("chars", 0) > 0:
                src_label = " [mixed: provider+chars]"
            elif src_mix.get("provider", 0) > 0:
                src_label = " [real tokens]"
            else:
                src_label = " [char-est]"

            lines.append(
                f"    {stype:<22} calls={bucket['calls']:<4} "
                f"in={bucket['input_tokens']:>8} out={bucket['output_tokens']:>8} tok  "
                f"est=${bucket['est_total_usd']:.4f}"
                f"{src_label}"
            )
        lines.append("")

    totals = result["totals"]
    lines.append(
        f"  TOTAL                     calls={totals['calls']:<4} "
        f"in={totals['input_tokens']:>8} out={totals['output_tokens']:>8} tok  "
        f"est=${totals['est_total_usd']:.4f}"
    )
    lines.append(
        f"    (input: ${totals['est_input_usd']:.4f}  "
        f"output: ${totals['est_output_usd']:.4f})"
    )

    return "\n".join(lines)


def main() -> None:
    parser = _build_parser()

    # Legacy positional mode: first arg is not a recognized subcommand and
    # does not start with '--'.  Treat it as 'estimate <command>'.
    # This preserves backward-compatibility with callers that do:
    #   estimate-tokens.py z-research [--dispatch ...]
    if (
        len(sys.argv) >= 2
        and not sys.argv[1].startswith("--")
        and sys.argv[1] not in ("estimate", "forecast", "subagent-costs")
    ):
        # Inject 'estimate' subcommand for legacy callers.
        sys.argv.insert(1, "estimate")

    if len(sys.argv) < 2:
        parser.print_usage(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    if args.subcommand == "subagent-costs":
        metrics_path = (
            Path(args.metrics)
            if args.metrics
            else _default_metrics_path()
        )
        result = subagent_costs(metrics_path, tail_lines=args.tail_lines)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(_format_subagent_costs_table(result))
        return


    if args.subcommand == "forecast":
        command = getattr(args, "command", None)
        if command is None:
            parser.print_usage(sys.stderr)
            sys.exit(1)

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
        flat_dispatch: list[str] = [item for sublist in args.dispatch for item in sublist]
        dispatch_pairs = _parse_dispatch(flat_dispatch)
        envelope = forecast_e2e(
            raw_command=command,
            dispatch_pairs=dispatch_pairs,
            profiles_path=profiles_path,
            metrics_path=metrics_path,
            tail_lines=getattr(args, "tail_lines", 2000),
            min_samples=getattr(args, "min_samples", 3),
        )
        print(json.dumps(envelope, indent=2))
        return
    # Default: 'estimate' subcommand (or legacy positional mode).
    if args.subcommand not in ("estimate", None):
        parser.print_usage(sys.stderr)
        sys.exit(1)

    # For the estimate subcommand, prefer the subcommand-specific args; fall
    # back to top-level args for legacy positional callers.
    command = getattr(args, "command", None)
    if command is None:
        parser.print_usage(sys.stderr)
        sys.exit(1)

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

    tail_lines = getattr(args, "tail_lines", 2000)
    min_samples = getattr(args, "min_samples", 3)

    if getattr(args, "e2e_forecast", False):
        envelope = forecast_e2e(
            raw_command=command,
            dispatch_pairs=dispatch_pairs,
            profiles_path=profiles_path,
            metrics_path=metrics_path,
            tail_lines=tail_lines,
            min_samples=min_samples,
        )
    else:
        envelope = estimate(
            raw_command=command,
            dispatch_pairs=dispatch_pairs,
            profiles_path=profiles_path,
            metrics_path=metrics_path,
            tail_lines=tail_lines,
            min_samples=min_samples,
        )

    # Stdout is pure JSON — one object, no trailing noise.
    print(json.dumps(envelope, indent=2))


if __name__ == "__main__":
    main()
