#!/usr/bin/env python3
"""
scripts/amend-gate-decision.py — Map a workflow.audit_to_amend resolver envelope
to a single gate-decision token consumed by /z-audit-plan Phase 5 and
/z-review-all Phase 6.5.

Usage:
  echo '<resolver-json>' | python3 scripts/amend-gate-decision.py
  python3 scripts/amend-gate-decision.py '{"result":"ask","source":"none","default":"amend"}'

Input:
  The JSON resolver envelope produced by:
    python3 scripts/config.py resolve-question workflow.audit_to_amend
  Required fields: result, source, default (additional fields are ignored).

Output (stdout, single token, no trailing newline):
  auto_split   — proceed with automatic spec_gap / premise_failure split; no popup
  force_ask    — fall back to the 3-way interactive popup
  halt         — abort immediately; do not amend

Exit codes:
  0  Decision token printed
  1  Invalid / unreadable input JSON or missing required fields
"""

from __future__ import annotations

import json
import sys


# ── constants ──────────────────────────────────────────────────────────────────

# result values that we explicitly handle
_RESULT_HALT = "halt"
_RESULT_SKIP = "skip"

# source values that indicate an explicit user preference
_EXPLICIT_SOURCES = {"config", "memory"}

# result values from an explicit source that request interactive input
_ASK_RESULTS = {"ask", "prefill"}


# ── decision logic ─────────────────────────────────────────────────────────────

def decide(resolver: dict) -> str:
    """
    Map a resolver envelope to one of: auto_split | force_ask | halt.

    Evaluation order (earlier rules take precedence):

    1. result=="halt"
       User explicitly configured stop; abort immediately regardless of source.
       → halt

    2. result=="skip"
       User explicitly configured auto-amend; skip the popup.
       → auto_split

    3. source=="none"
       No preference stored anywhere (fresh user / no config).
       The NEW default is to proceed automatically.
       → auto_split

    4. source in {config, memory} AND result in {ask, prefill}
       User set an explicit preference that wants interactive input.
       Honour the stored preference and show the 3-way popup.
       → force_ask

    5. (unlisted combinations)
       Any other combination (e.g. source=="axiom", result=="proceed",
       source=="override", etc.) is treated as non-interactive and we
       proceed with the automatic split to avoid a spurious popup.
       → auto_split
    """
    result = resolver.get("result", "")
    source = resolver.get("source", "")

    # Rule 1: explicit halt wins over everything
    if result == _RESULT_HALT:
        return "halt"

    # Rule 2: explicit skip → no popup needed
    if result == _RESULT_SKIP:
        return "auto_split"

    # Rule 3: no preference stored → use the new default (auto-split)
    if source == "none":
        return "auto_split"

    # Rule 4: explicit preference that requests a user interaction
    if source in _EXPLICIT_SOURCES and result in _ASK_RESULTS:
        return "force_ask"

    # Rule 5: all other combinations → auto_split (safe default)
    return "auto_split"


# ── I/O ────────────────────────────────────────────────────────────────────────

def _load_resolver(raw: str) -> dict:
    """Parse resolver JSON and validate required fields are present."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[amend-gate-decision] invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print("[amend-gate-decision] input must be a JSON object", file=sys.stderr)
        sys.exit(1)
    for field in ("result", "source"):
        if field not in data:
            print(f"[amend-gate-decision] missing required field: {field!r}", file=sys.stderr)
            sys.exit(1)
    return data


def main() -> None:
    if len(sys.argv) == 2 and not sys.argv[1].startswith("-"):
        # Inline JSON argument (convenient for shell one-liners)
        raw = sys.argv[1]
    elif not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
    else:
        print("usage: amend-gate-decision.py '<resolver-json>'", file=sys.stderr)
        print("       echo '<resolver-json>' | amend-gate-decision.py", file=sys.stderr)
        sys.exit(1)

    resolver = _load_resolver(raw)
    token = decide(resolver)
    print(token, end="")


if __name__ == "__main__":
    main()
