#!/usr/bin/env python3
"""
render-cost-summary.py — Reads events.jsonl and renders a cost summary Markdown table.

Usage:
    python3 scripts/render-cost-summary.py <events.jsonl>
    python3 scripts/render-cost-summary.py -   # read from stdin

Outputs a Markdown table to stdout.  Warnings to stderr.

Data sources (priority order):
  1. subagent dispatch/return events for provider + model fields
  2. Falls back to "unknown" where provider/model metadata is absent

Handles:
  - Empty events file → "No telemetry data"
  - Zero LLM calls → "No LLM calls"
  - Incomplete event pairs → skip row + log warning
  - Very large runs → cap table at 20 rows, add footer
  - Missing provider or model → "unknown"
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# Approximate cost per 1M tokens (input / output). Estimates only.
_COST_PER_M = {
    ("deepseek", "v4-pro"):  (0.55, 2.19),
    ("deepseek", "v4-flash"): (0.14, 0.28),
    ("cursor", "sonnet"):    (3.00, 15.00),
    ("cursor", "haiku"):     (0.25, 1.25),
    ("cursor", "opus"):      (15.00, 75.00),
    ("google", "gemini-2.5-pro"): (1.25, 10.00),
    ("google", "gemini-2.5-flash"): (0.15, 0.60),
    ("openai", "codex"):     (3.00, 15.00),
}

MAX_ROWS = 20


def _lookup_cost(provider: str, model: str, tokens_in: int, tokens_out: int) -> str | None:
    """Return an estimated cost string like '$0.17', or None."""
    key = (provider.lower(), model.lower())
    rates = _COST_PER_M.get(key)
    if rates is None:
        return None
    cost_in = (tokens_in / 1_000_000) * rates[0]
    cost_out = (tokens_out / 1_000_000) * rates[1]
    total = cost_in + cost_out
    if total < 0.01:
        return "<$0.01"
    return f"${total:.2f}"


def _format_tokens(n: int) -> str:
    """Pretty-print token count."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def render(events_path: str) -> str:
    """Read events.jsonl and return a Markdown cost summary table string."""
    # Read events
    events = []
    try:
        if events_path == "-":
            for line in sys.stdin:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        else:
            p = Path(events_path)
            if not p.is_file():
                return "## Cost Summary\n\nNo telemetry data\n"
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: failed to read events.jsonl — {e}", file=sys.stderr)
        return "## Cost Summary\n\nNo telemetry data\n"

    if not events:
        return "## Cost Summary\n\nNo telemetry data\n"

    # Aggregate subagent dispatch/return pairs and consult_start/consult_done pairs
    # Key by (run_id, subagent_type) for dispatch/return; (run_id, provider) for consult
    dispatch_open: dict[tuple[str, str], dict] = {}
    consult_open: dict[tuple[str, str], dict] = {}
    rows: list[dict] = []
    warnings: list[str] = []

    for ev in events:
        kind = ev.get("kind", "")

        if kind == "subagent_dispatch":
            key = (ev.get("run_id", ""), ev.get("subagent_type", ""))
            dispatch_open[key] = ev
        elif kind == "subagent_return":
            key = (ev.get("run_id", ""), ev.get("subagent_type", ""))
            dispatch_ev = dispatch_open.pop(key, None)
            provider = ev.get("provider", "")
            model = ev.get("model", "")
            tokens_in = ev.get("tokens_in", 0)
            tokens_out = ev.get("tokens_out", 0)

            # If the return event lacks token data, try the dispatch event
            if not tokens_in and dispatch_ev:
                tokens_in = dispatch_ev.get("tokens_in", 0)
            if not tokens_out and dispatch_ev:
                tokens_out = dispatch_ev.get("tokens_out", 0)
            if not provider and dispatch_ev:
                provider = dispatch_ev.get("provider", "")
            if not model and dispatch_ev:
                model = dispatch_ev.get("model", "")

            provider = provider or "unknown"
            model = model or "unknown"

            rows.append({
                "provider": provider,
                "model": model,
                "tokens_in": tokens_in or 0,
                "tokens_out": tokens_out or 0,
            })

        elif kind == "consult_start":
            key = (ev.get("run_id", ""), ev.get("provider", ""))
            consult_open[key] = ev
        elif kind == "consult_done":
            provider = ev.get("provider", "")
            key = (ev.get("run_id", ""), provider)
            consult_ev = consult_open.pop(key, None)
            # consult_done events lack token metadata in current schema
            # — skip them entirely.  They are logged only for presence.
            pass

    # Warn on unclosed pairs
    for key in dispatch_open:
        warnings.append(f"skipped unclosed subagent dispatch: {key[1]} (run {key[0]})")

    # Aggregate by (provider, model)
    agg: dict[tuple[str, str], dict] = defaultdict(lambda: {"tokens_in": 0, "tokens_out": 0})
    for row in rows:
        key = (row["provider"], row["model"])
        agg[key]["tokens_in"] += row["tokens_in"]
        agg[key]["tokens_out"] += row["tokens_out"]

    # Emit warnings
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if not agg:
        return "## Cost Summary\n\nNo LLM calls\n"

    # Sort by total tokens descending
    sorted_agg = sorted(agg.items(), key=lambda x: x[1]["tokens_in"] + x[1]["tokens_out"], reverse=True)

    # Build table
    lines = ["## Cost Summary\n", "", "| Provider | Model | Tokens (in/out) | Est. Cost |", "|----------|-------|-----------------|-----------|"]
    capped = False
    count = 0

    for (provider, model), counts in sorted_agg:
        if count >= MAX_ROWS:
            capped = True
            break
        count += 1

        tokens_in = counts["tokens_in"]
        tokens_out = counts["tokens_out"]
        cost = _lookup_cost(provider, model, tokens_in, tokens_out)

        in_str = _format_tokens(tokens_in)
        out_str = _format_tokens(tokens_out)
        cost_str = cost if cost is not None else "unknown"

        lines.append(f"| {provider} | {model} | {in_str} / {out_str} | {cost_str} |")

    if capped:
        remaining = len(sorted_agg) - MAX_ROWS
        lines.append(f"| … | … | *…and {remaining} more* | |")

    lines.append("")
    lines.append("*Cost estimates only — token pricing changes over time.*")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: render-cost-summary.py <events.jsonl>", file=sys.stderr)
        return 1

    result = render(sys.argv[1])
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
