#!/usr/bin/env python3
"""Summarise documented Codex rollout v1 JSONL without exposing its contents.

This is deliberately a read-only, allowlist-only boundary.  It accepts
``--source live:path`` and ``--source archive:path`` inputs, but neither input
paths nor unrecognised record values can reach stdout.  The rollout format is
not a public API, so rows outside the small v1 envelope are reported only by a
stable quality flag.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

VERSION = 1
EVENT_FIELDS = {
    "usage": {"total_tokens"},
    "turn_start": {"turn_id"},
    "turn_end": {"turn_id"},
    "first_token": {"turn_id"},
    "tool_start": {"tool_call_id"},
    "tool_end": {"tool_call_id"},
}
BASE_FIELDS = {"schema_version", "session_id", "parent_session_id", "event", "timestamp"}


def timestamp_ms(value: Any) -> int | None:
    """Return a timestamp in milliseconds, accepting numeric and ISO values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # Rollout fixtures may use seconds or already-normalised milliseconds.
        return int(value * 1000) if abs(value) < 10_000_000_000 else int(value)
    if isinstance(value, str):
        try:
            text = value.replace("Z", "+00:00")
            parsed = dt.datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return None
            return int(parsed.timestamp() * 1000)
        except ValueError:
            return None
    return None


def session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def parse_source(spec: str) -> tuple[str, Path]:
    try:
        source, raw_path = spec.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("source must be live:<jsonl-path> or archive:<jsonl-path>") from exc
    if source not in {"live", "archive"} or not raw_path:
        raise argparse.ArgumentTypeError("source must be live:<jsonl-path> or archive:<jsonl-path>")
    return source, Path(raw_path)


def read_rows(sources: list[tuple[str, Path]]) -> tuple[list[dict[str, Any]], set[str]]:
    rows: list[dict[str, Any]] = []
    flags: set[str] = set()
    for source, path in sources:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            flags.add("unreadable_source")
            continue
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                flags.update({"malformed_row", "truncation", "truncated_row"})
                continue
            if not isinstance(value, dict):
                flags.add("malformed_row")
                continue
            if value.get("schema_version", VERSION) != VERSION:
                flags.add("unknown_schema")
                continue
            event = value.get("event")
            allowed = BASE_FIELDS | EVENT_FIELDS.get(event, set())
            if event not in EVENT_FIELDS or set(value) - allowed:
                flags.add("unknown_schema")
                continue
            session_id = value.get("session_id")
            stamp = timestamp_ms(value.get("timestamp"))
            if not isinstance(session_id, str) or not session_id or stamp is None:
                flags.add("malformed_row")
                continue
            # Keep only recognised values, so unknown values are never retained.
            row = {"source": source, "session_id": session_id, "event": event, "timestamp": stamp}
            for field in EVENT_FIELDS[event]:
                if field in value:
                    row[field] = value[field]
            rows.append(row)
    return rows, flags


def fingerprint(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(key) for key in ("session_id", "event", "timestamp", "turn_id", "tool_call_id", "total_tokens"))


def make_session(session_id: str, rows: list[dict[str, Any]], source_labels: set[str], inherited: set[str]) -> dict[str, Any]:
    flags = set(inherited)
    rows.sort(key=lambda item: item["timestamp"])
    token_total = 0
    previous_usage: int | None = None
    needs_segment_baseline = False
    saw_usage = False
    turn_starts: dict[str, int] = {}
    turn_ends: dict[str, int] = {}
    first_tokens: dict[str, int] = {}
    tool_starts: dict[str, int] = {}
    tool_wait_total = 0
    saw_tool_wait = False

    for row in rows:
        event = row["event"]
        if event == "usage":
            raw = row.get("total_tokens")
            if isinstance(raw, bool) or not isinstance(raw, int):
                flags.add("unknown_token_counter")
                previous_usage = None
                needs_segment_baseline = True
            elif raw < 0:
                flags.add("negative_token_counter")
                previous_usage = None
                needs_segment_baseline = True
            elif previous_usage is None:
                # This is a session-local baseline.  In particular it is not
                # compared with a parent session's cumulative counter.
                # A valid counter after an invalid/missing value begins a new
                # segment; it is not safe to treat its full cumulative value
                # as newly consumed tokens.  Only a later monotonic delta is
                # accounted for.
                if needs_segment_baseline:
                    flags.add("counter_segment_baseline")
                    needs_segment_baseline = False
                else:
                    token_total += raw
                previous_usage = raw
                saw_usage = True
            elif raw < previous_usage:
                flags.add("counter_reset")
                previous_usage = raw
            else:
                token_total += raw - previous_usage
                previous_usage = raw
                saw_usage = True
        elif event in {"turn_start", "turn_end", "first_token"}:
            turn_id = row.get("turn_id")
            if not isinstance(turn_id, str) or not turn_id:
                flags.add("malformed_row")
                continue
            target = {"turn_start": turn_starts, "turn_end": turn_ends, "first_token": first_tokens}[event]
            target.setdefault(turn_id, row["timestamp"])
        elif event in {"tool_start", "tool_end"}:
            tool_id = row.get("tool_call_id")
            if not isinstance(tool_id, str) or not tool_id:
                flags.add("malformed_row")
                continue
            if event == "tool_start":
                tool_starts.setdefault(tool_id, row["timestamp"])
            elif tool_id not in tool_starts:
                flags.add("unmatched_tool_event")
            else:
                wait = row["timestamp"] - tool_starts.pop(tool_id)
                if wait < 0:
                    flags.add("negative_timing")
                else:
                    tool_wait_total += wait
                    saw_tool_wait = True
    if tool_starts:
        flags.add("unmatched_tool_event")

    ttft_total = 0
    saw_ttft = False
    for turn_id, started in turn_starts.items():
        first = first_tokens.get(turn_id)
        if first is None:
            flags.add("missing_first_token")
        elif first < started:
            flags.add("negative_timing")
        else:
            ttft_total += first - started
            saw_ttft = True

    # A completed turn is its explicit end when present; otherwise a first
    # token is the only observed completion boundary and is intentionally not
    # used to fabricate idle time.
    completed = sorted(turn_ends.values())
    started = sorted(turn_starts.values())
    idle_total = 0
    saw_idle = False
    for end, next_start in zip(completed, started[1:]):
        if next_start > end:
            idle_total += next_start - end
            saw_idle = True

    return {
        "session_hash": session_hash(session_id),
        "source": "both" if source_labels == {"live", "archive"} else next(iter(source_labels)),
        "token_count": token_total if saw_usage else None,
        "turn_count": len(turn_starts) if turn_starts else None,
        "ttft_ms": ttft_total if saw_ttft else None,
        "ttft_precision": "exact" if saw_ttft else "unknown",
        "tool_wait_ms": tool_wait_total if saw_tool_wait else None,
        "tool_wait_precision": "exact" if saw_tool_wait else "unknown",
        "inferred_idle_ms": idle_total if saw_idle else None,
        "idle_precision": "inferred" if saw_idle else "unknown",
        "quality_flags": sorted(flags),
    }


def summarize(sources: list[tuple[str, Path]]) -> dict[str, Any]:
    rows, global_flags = read_rows(sources)
    seen: set[tuple[Any, ...]] = set()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        marker = fingerprint(row)
        # Source provenance applies even where the archive duplicate is dropped
        # from accounting, otherwise a live/archive overlap looks live-only.
        labels[row["session_id"]].add(row["source"])
        if marker in seen:
            continue
        seen.add(marker)
        grouped[row["session_id"]].append(row)
    sessions = [make_session(key, grouped[key], labels[key], global_flags) for key in sorted(grouped, key=session_hash)]
    return {"schema_version": VERSION, "sessions": sessions, "quality_flags": sorted(global_flags)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=parse_source, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.source), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
