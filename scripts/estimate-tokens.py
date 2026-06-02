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
  3. Empirical — (T004: stub, returns None) parent-run rollup from metrics.jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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
# T004: empirical tier (stub — returns None, no-op)
# ---------------------------------------------------------------------------

def _empirical_tier(
    command: str,
    metrics_path: Path,
    tail_lines: int,
    min_samples: int,
) -> dict | None:
    # T004: empirical tier — not implemented in this task.
    # When T004 implements this, it should return a dict:
    #   {"p50": int, "p90": int, "samples": int}
    # or None if insufficient data / file absent.
    return None


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

    # ------------------------------------------------------------------ Tier 3: Empirical (stub)
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
