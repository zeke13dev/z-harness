#!/usr/bin/env python3
"""
context-budget.py — Analyze z-harness telemetry for context utilization insights.

Usage:
    python3 scripts/context-budget.py <archive_dir>
    python3 scripts/context-budget.py context-pressure <run_or_plan_dir> [--metrics PATH]
    python3 scripts/context-budget.py --help

Reads events.jsonl and filesystem artifacts from a run archive directory.
Produces either Markdown analysis or the parseable rough context-pressure JSON
contract used by checkpoint callers.

Handles: empty event log, missing archive, very large event logs gracefully.
"""

from __future__ import annotations

import argparse
import os
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

# Rough context-pressure contract. Host/editor values are exact token counts
# when supplied; otherwise z-harness computes a deterministic approximation.
DEFAULT_CONTEXT_WINDOW_TOKENS = 200_000
DEFAULT_CHECKPOINT_NOW_PERCENT = 85.0
DEFAULT_CHECKPOINT_SOON_PERCENT = 70.0
CHARS_PER_TOKEN = 4
CONTEXT_PRESSURE_SCHEMA_VERSION = "context_pressure.v1"


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n


def _read_env_tokens(
    env: dict[str, str],
    key: str,
    *,
    positive: bool,
) -> tuple[int | None, str | None]:
    raw = env.get(key)
    if raw is None or raw == "":
        return None, None
    n = _coerce_int(raw)
    if n is None:
        return None, f"{key} is not an integer and was ignored"
    if positive and n <= 0:
        return None, f"{key} must be > 0 and was ignored"
    if not positive and n < 0:
        return None, f"{key} must be >= 0 and was ignored"
    return n, None


def _event_token_estimate(event: dict) -> tuple[int, str]:
    """Return (tokens, source) for one telemetry event.

    Precedence is intentionally aligned with estimate-tokens.py:
      provider_total_tokens/total_tokens
      provider_input_tokens/provider_output_tokens per side
      subagent_input_tokens/subagent_output_tokens per side
      prompt_chars/4 + response_chars/4
      0
    """
    provider_total = _coerce_int(event.get("provider_total_tokens"))
    if provider_total is None:
        provider_total = _coerce_int(event.get("total_tokens"))
    if provider_total is not None and provider_total >= 0:
        return provider_total, "provider"

    provider_in = _coerce_int(event.get("provider_input_tokens"))
    provider_out = _coerce_int(event.get("provider_output_tokens"))
    subagent_in = _coerce_int(event.get("subagent_input_tokens"))
    subagent_out = _coerce_int(event.get("subagent_output_tokens"))
    prompt_chars = _coerce_int(event.get("prompt_chars"))
    response_chars = _coerce_int(event.get("response_chars"))

    provider_seen = (
        (provider_in is not None and provider_in >= 0)
        or (provider_out is not None and provider_out >= 0)
    )
    subagent_seen = (
        (subagent_in is not None and subagent_in >= 0)
        or (subagent_out is not None and subagent_out >= 0)
    )
    char_seen = (
        (prompt_chars is not None and prompt_chars >= 0)
        or (response_chars is not None and response_chars >= 0)
    )

    if provider_in is not None and provider_in >= 0:
        input_tokens = provider_in
    elif subagent_in is not None and subagent_in >= 0:
        input_tokens = subagent_in
    elif prompt_chars is not None and prompt_chars >= 0:
        input_tokens = prompt_chars // CHARS_PER_TOKEN
    else:
        input_tokens = 0

    if provider_out is not None and provider_out >= 0:
        output_tokens = provider_out
    elif subagent_out is not None and subagent_out >= 0:
        output_tokens = subagent_out
    elif response_chars is not None and response_chars >= 0:
        output_tokens = response_chars // CHARS_PER_TOKEN
    else:
        output_tokens = 0

    if provider_seen:
        source = "provider"
    elif subagent_seen:
        source = "subagent"
    elif char_seen:
        source = "chars"
    else:
        source = "none"

    return input_tokens + output_tokens, source


def _path_key(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _event_key(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


def _iter_jsonl_events(path: Path, seen_events: set[str] | None = None) -> tuple[int, Counter, int]:
    tokens = 0
    source_mix: Counter = Counter()
    events_read = 0
    if not path.is_file():
        return tokens, source_mix, events_read
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict):
                    continue
                key = _event_key(ev)
                if seen_events is not None:
                    if key in seen_events:
                        continue
                    seen_events.add(key)
                events_read += 1
                event_tokens, source = _event_token_estimate(ev)
                tokens += event_tokens
                if source != "none":
                    source_mix[source] += 1
    except OSError:
        return 0, Counter(), 0
    return tokens, source_mix, events_read


def _context_pressure_telemetry_paths(root: Path, metrics_path: Path | None = None) -> list[Path]:
    """Return canonical telemetry inputs for a run dir, archive dir, or plan dir."""
    paths: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        key = _path_key(path)
        if key not in seen:
            seen.add(key)
            paths.append(path)

    add(root / "events.jsonl")
    add(root / "metrics.jsonl")

    archive_dir = root / "archive"
    if archive_dir.is_dir():
        for event_path in sorted(archive_dir.glob("*/events.jsonl")):
            add(event_path)

    if root.name == "archive" and root.is_dir():
        for event_path in sorted(root.glob("*/events.jsonl")):
            add(event_path)

    if metrics_path is not None:
        add(metrics_path)

    return paths


def _rough_context_components(run_dir: Path, metrics_path: Path | None = None) -> dict:
    telemetry_paths = _context_pressure_telemetry_paths(run_dir, metrics_path=metrics_path)

    telemetry_tokens = 0
    telemetry_events_read = 0
    telemetry_source_mix: Counter = Counter()
    seen_telemetry_paths: set[Path] = set()
    seen_events: set[str] = set()
    for path in telemetry_paths:
        seen_telemetry_paths.add(_path_key(path))
        tokens, source_mix, events_read = _iter_jsonl_events(path, seen_events=seen_events)
        telemetry_tokens += tokens
        telemetry_events_read += events_read
        telemetry_source_mix.update(source_mix)

    artifact_bytes = 0
    artifact_files = 0
    large_artifact_files = 0
    if run_dir.is_dir():
        telemetry_resolved = seen_telemetry_paths
        for fpath in sorted(run_dir.rglob("*")):
            if not fpath.is_file():
                continue
            if _path_key(fpath) in telemetry_resolved:
                continue
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            artifact_bytes += size
            artifact_files += 1
            if size > MAX_ARTIFACT_BYTES:
                large_artifact_files += 1

    artifact_tokens = artifact_bytes // CHARS_PER_TOKEN
    return {
        "telemetry_tokens": telemetry_tokens,
        "telemetry_events_read": telemetry_events_read,
        "telemetry_source_mix": dict(telemetry_source_mix),
        "artifact_bytes": artifact_bytes,
        "artifact_tokens": artifact_tokens,
        "artifact_files": artifact_files,
        "large_artifact_files": large_artifact_files,
        "estimated_tokens": telemetry_tokens + artifact_tokens,
    }


def _config_defaults() -> tuple[int, float, str]:
    """Return (context_window_tokens, pause_at_pct, window_source), falling back silently."""
    try:
        import config as harness_config  # type: ignore

        values, _sources = harness_config.load_config()
        raw_window = _coerce_int(values.get("runtime.context_window_tokens"))
        raw_pause = values.get("runtime.pause_at_pct")
        pause = float(raw_pause) if raw_pause is not None else DEFAULT_CHECKPOINT_NOW_PERCENT
        if raw_window is not None and raw_window > 0:
            return raw_window, pause, "config"
    except (Exception, SystemExit):
        pass
    return DEFAULT_CONTEXT_WINDOW_TOKENS, DEFAULT_CHECKPOINT_NOW_PERCENT, "default"


def estimate_context_pressure(
    run_dir: Path,
    *,
    env: dict[str, str] | None = None,
    metrics_path: Path | None = None,
    fallback_window_tokens: int | None = None,
    checkpoint_now_percent: float | None = None,
    checkpoint_soon_percent: float | None = None,
) -> dict:
    """Return the parseable rough context-pressure contract.

    Host/editor inputs are token counts:
      Z_HARNESS_CONTEXT_USED_TOKENS    — current used context tokens (>=0)
      Z_HARNESS_CONTEXT_WINDOW_TOKENS  — total context window tokens (>0)

    Host used tokens win for estimated_tokens. Host window tokens win for the
    denominator. Missing/invalid pieces fail open into the deterministic rough
    estimate and explicit fallback window rather than blocking the command.
    """
    env_map = dict(os.environ if env is None else env)
    config_window, config_pause, config_window_source = _config_defaults()
    window_fallback = fallback_window_tokens if fallback_window_tokens is not None else config_window
    if window_fallback <= 0:
        window_fallback = DEFAULT_CONTEXT_WINDOW_TOKENS

    now_threshold = checkpoint_now_percent if checkpoint_now_percent is not None else config_pause
    soon_threshold = (
        checkpoint_soon_percent
        if checkpoint_soon_percent is not None
        else min(DEFAULT_CHECKPOINT_SOON_PERCENT, max(0.0, now_threshold))
    )

    warnings: list[str] = []
    host_used, warning = _read_env_tokens(env_map, "Z_HARNESS_CONTEXT_USED_TOKENS", positive=False)
    if warning:
        warnings.append(warning)
    host_window, warning = _read_env_tokens(env_map, "Z_HARNESS_CONTEXT_WINDOW_TOKENS", positive=True)
    if warning:
        warnings.append(warning)

    components = _rough_context_components(run_dir, metrics_path=metrics_path)
    rough_tokens = int(components["estimated_tokens"])

    if host_used is not None:
        estimated_tokens = host_used
        used_source = "host_env"
        if host_window is None:
            warnings.append("Z_HARNESS_CONTEXT_USED_TOKENS supplied without Z_HARNESS_CONTEXT_WINDOW_TOKENS; using fallback window_tokens")
    else:
        estimated_tokens = rough_tokens
        used_source = "rough_estimate"
        if host_window is not None:
            warnings.append("Z_HARNESS_CONTEXT_WINDOW_TOKENS supplied without Z_HARNESS_CONTEXT_USED_TOKENS; using rough estimated_tokens")

    if host_window is not None:
        window_tokens = host_window
        window_source = "host_env"
    else:
        window_tokens = window_fallback
        window_source = config_window_source if fallback_window_tokens is None else "caller"

    percent_used = round((estimated_tokens / window_tokens) * 100.0, 2) if window_tokens > 0 else 0.0
    if percent_used >= now_threshold:
        recommendation = "checkpoint_now"
    elif percent_used >= soon_threshold:
        recommendation = "checkpoint_soon"
    else:
        recommendation = "continue"

    return {
        "schema_version": CONTEXT_PRESSURE_SCHEMA_VERSION,
        "estimated_tokens": int(estimated_tokens),
        "window_tokens": int(window_tokens),
        "percent_used": percent_used,
        "recommendation": recommendation,
        "thresholds": {
            "checkpoint_soon_percent": soon_threshold,
            "checkpoint_now_percent": now_threshold,
        },
        "sources": {
            "used": used_source,
            "window": window_source,
        },
        "inputs": {
            "host_used_tokens": host_used,
            "host_window_tokens": host_window,
        },
        "components": components,
        "warnings": warnings,
        "approximation_limits": (
            "Host/editor token counts are preferred when supplied. Otherwise this is a rough, "
            "deterministic estimate: provider token fields first, then subagent token fields, "
            "then prompt_chars/response_chars divided by 4, plus non-telemetry artifact bytes "
            "divided by 4. It is suitable for checkpoint pressure decisions, not billing or "
            "exact context accounting."
        ),
    }


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

    # --- 3. Rough context pressure ---
    pressure = estimate_context_pressure(run_dir)
    pressure_status = _status_icon(
        pressure["recommendation"] == "continue",
        warn=pressure["recommendation"] == "checkpoint_soon",
        critical=pressure["recommendation"] == "checkpoint_now",
    )
    lines.append(
        "| Context pressure | "
        f"{pressure['estimated_tokens']}/{pressure['window_tokens']} tokens "
        f"({pressure['percent_used']:.2f}%, {pressure['recommendation']}) | "
        f"{pressure_status} |"
    )
    for warning in pressure.get("warnings", []):
        warnings.append(f"Context pressure: {warning}")

    # --- 5. Subagent dispatch analysis ---
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

    # --- 6. Recommendations ---
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


def _context_pressure_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="context-budget.py context-pressure",
        description="Emit the parseable rough context-pressure contract as JSON.",
    )
    parser.add_argument("run_dir", help="Run archive, archive parent, or plan directory to inspect.")
    parser.add_argument("--metrics", metavar="PATH", default=None, help="Optional metrics.jsonl path.")
    parser.add_argument("--window-tokens", metavar="N", type=int, default=None, help="Fallback window token count.")
    parser.add_argument("--checkpoint-now-percent", metavar="PCT", type=float, default=None, help="checkpoint_now threshold.")
    parser.add_argument("--checkpoint-soon-percent", metavar="PCT", type=float, default=None, help="checkpoint_soon threshold.")
    args = parser.parse_args(argv)

    result = estimate_context_pressure(
        Path(args.run_dir).resolve(),
        metrics_path=Path(args.metrics).resolve() if args.metrics else None,
        fallback_window_tokens=args.window_tokens,
        checkpoint_now_percent=args.checkpoint_now_percent,
        checkpoint_soon_percent=args.checkpoint_soon_percent,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "context-pressure":
        return _context_pressure_main(sys.argv[2:])

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
