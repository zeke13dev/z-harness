"""Versioned privacy-safe native usage observations and reducers.

The public surface is deliberately small: :func:`reduce_usage_observations`
validates and reduces immutable allowlist-only observations,
:func:`reduce_intervals` preserves overlapping lifecycle timing, and
:func:`summarize_sources` adapts supported Codex rollout envelopes to the same
reducers.  Unknown provider semantics fail closed to an unknown segment rather
than turning cumulative or inherited values into additive usage (INTENT T003,
acceptance criteria #6, #8, and #9).

All helpers are deterministic and stdlib-only.  They do not persist state and
intentionally hard-fail on a caller-supplied canonical record that violates the
allowlist; raw rollout schema drift is instead represented by quality flags.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


CONTRACT_VERSION = 1
SOURCE_SEMANTICS_VERSION = "codex-rollout-v1"
_OBSERVATION_FIELDS = {
    "schema_version",
    "observation_id",
    "host",
    "surface",
    "source",
    "lineage",
    "segment",
    "observed_at_ms",
    "clock",
    "raw",
    "derived",
    "quality_flags",
}
_SOURCE_FIELDS = {"kind", "identity_hash", "semantics_version"}
_LINEAGE_FIELDS = {"session_hash", "root_session_hash", "parent_session_hash"}
_SEGMENT_FIELDS = {"id", "baseline", "counter_scope"}
_CLOCK_FIELDS = {"kind", "source", "skew_ms"}
_RAW_FIELDS = {
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
}
_DERIVED_FIELDS = {"uncached_input_tokens", "additive_total_tokens", "equation_version"}
_INTERVAL_FIELDS = {"kind", "start_ms", "end_ms", "clock_source"}
_BASELINES = {"zero", "previous", "missing", "ambiguous"}
_COUNTER_SCOPES = {"session_own", "inherited", "unknown"}
_INTERVAL_KINDS = {"active", "dispatch", "tool_wait", "idle", "pause"}
_HOSTS = {"codex", "claude"}
_SURFACES = {"codex_cli", "codex_app", "claude_cli", "native_rollout", "unknown"}
_SOURCE_KINDS = {"live", "archive"}
_CLOCK_KINDS = {"wall", "monotonic"}
_CLOCK_SOURCES = {"provider", "host"}
_QUALITY_FLAGS = {
    "counter_reset",
    "counter_segment_baseline",
    "malformed_row",
    "missing_first_token",
    "missing_session_meta",
    "negative_timing",
    "negative_token_counter",
    "out_of_order",
    "replay",
    "same_timestamp_ambiguity",
    "truncated_row",
    "truncation",
    "unknown_schema",
    "unknown_token_counter",
    "unmatched_tool_event",
    "unreadable_source",
}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_HASHED_IDENTIFIER = re.compile(r"^[0-9a-f]{16,64}$")


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def timestamp_ms(value: Any) -> int | None:
    """Return milliseconds for a numeric or timezone-aware ISO timestamp.

    Invalid values are a best-effort parse failure and return ``None``.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value * 1000) if abs(value) < 10_000_000_000 else int(value)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return int(parsed.timestamp() * 1000)
    return None


def session_hash(session_id: str) -> str:
    """Return a retention-bounded, non-raw session identifier."""
    return _hash_identifier(session_id)


def _require_exact_fields(record: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unexpected = set(record) - allowed
    missing = allowed - set(record)
    if unexpected or missing:
        raise ValueError(f"{label} fields violate allowlist: missing={sorted(missing)}, unexpected={sorted(unexpected)}")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _token(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer or null")
    return value


def validate_observation(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy one canonical immutable observation.

    This is a hard-fail privacy boundary: unknown/content-bearing fields raise
    ``ValueError`` and are never retained or silently spread into telemetry.

    Args:
        record: Canonical observation mapping.

    Returns:
        A detached allowlisted copy.

    Raises:
        ValueError: If the schema, allowlist, or component semantics are invalid.
    """
    _require_exact_fields(record, _OBSERVATION_FIELDS, "observation")
    if record["schema_version"] != CONTRACT_VERSION:
        raise ValueError("unsupported native usage schema_version")
    for field in ("observation_id", "host", "surface"):
        if not isinstance(record[field], str) or not record[field]:
            raise ValueError(f"{field} must be a non-empty string")
    if not _SAFE_IDENTIFIER.fullmatch(record["observation_id"]):
        raise ValueError("observation_id must be a privacy-safe stable identifier")
    if record["host"] not in _HOSTS or record["surface"] not in _SURFACES:
        raise ValueError("unsupported host or surface")
    if isinstance(record["observed_at_ms"], bool) or not isinstance(record["observed_at_ms"], int):
        raise ValueError("observed_at_ms must be an integer")

    source = _require_mapping(record["source"], "source")
    lineage = _require_mapping(record["lineage"], "lineage")
    segment = _require_mapping(record["segment"], "segment")
    clock = _require_mapping(record["clock"], "clock")
    raw = _require_mapping(record["raw"], "raw")
    derived = _require_mapping(record["derived"], "derived")
    _require_exact_fields(source, _SOURCE_FIELDS, "source")
    _require_exact_fields(lineage, _LINEAGE_FIELDS, "lineage")
    _require_exact_fields(segment, _SEGMENT_FIELDS, "segment")
    _require_exact_fields(clock, _CLOCK_FIELDS, "clock")
    _require_exact_fields(raw, _RAW_FIELDS, "raw")
    _require_exact_fields(derived, _DERIVED_FIELDS, "derived")

    if source["kind"] not in _SOURCE_KINDS or source["semantics_version"] != SOURCE_SEMANTICS_VERSION:
        raise ValueError("unsupported source kind or semantics_version")
    if not isinstance(source["identity_hash"], str) or not _HASHED_IDENTIFIER.fullmatch(source["identity_hash"]):
        raise ValueError("source.identity_hash must be hashed")
    for field in ("session_hash", "root_session_hash"):
        value = lineage[field]
        if not isinstance(value, str) or not _HASHED_IDENTIFIER.fullmatch(value):
            raise ValueError(f"lineage.{field} must be hashed")
    parent_hash = lineage["parent_session_hash"]
    if parent_hash is not None and (not isinstance(parent_hash, str) or not _HASHED_IDENTIFIER.fullmatch(parent_hash)):
        raise ValueError("lineage.parent_session_hash must be hashed or null")
    if not isinstance(segment["id"], str) or not _SAFE_IDENTIFIER.fullmatch(segment["id"]):
        raise ValueError("segment.id must be a privacy-safe identifier")
    if clock["kind"] not in _CLOCK_KINDS or clock["source"] not in _CLOCK_SOURCES:
        raise ValueError("unsupported clock provenance")
    skew = clock["skew_ms"]
    if skew is not None and (isinstance(skew, bool) or not isinstance(skew, int)):
        raise ValueError("clock.skew_ms must be an integer or null")

    if segment["baseline"] not in _BASELINES or segment["counter_scope"] not in _COUNTER_SCOPES:
        raise ValueError("unsupported baseline or counter_scope")
    for field in _RAW_FIELDS:
        _token(raw[field], f"raw.{field}")
    for field in {"uncached_input_tokens", "additive_total_tokens"}:
        _token(derived[field], f"derived.{field}")
    if not isinstance(derived["equation_version"], str) or not derived["equation_version"]:
        raise ValueError("derived.equation_version must be a non-empty string")

    input_tokens = raw["input_tokens"]
    cached_tokens = raw["cached_input_tokens"]
    output_tokens = raw["output_tokens"]
    reasoning_tokens = raw["reasoning_output_tokens"]
    if cached_tokens is not None and (input_tokens is None or cached_tokens > input_tokens):
        raise ValueError("cached input must be a subset of input")
    if reasoning_tokens is not None and (output_tokens is None or reasoning_tokens > output_tokens):
        raise ValueError("reasoning output must be a subset of output")
    expected_uncached = None if input_tokens is None or cached_tokens is None else input_tokens - cached_tokens
    if derived["uncached_input_tokens"] != expected_uncached:
        raise ValueError("derived uncached input violates source equation")
    expected_additive = None if input_tokens is None or output_tokens is None else input_tokens + output_tokens
    if expected_additive is None:
        expected_additive = raw["total_tokens"]
    if derived["additive_total_tokens"] != expected_additive:
        raise ValueError("derived additive total violates source equation")
    if raw["total_tokens"] is not None and expected_additive is not None and raw["total_tokens"] != expected_additive:
        raise ValueError("raw total violates component conservation")

    flags = record["quality_flags"]
    if not isinstance(flags, list) or any(flag not in _QUALITY_FLAGS for flag in flags):
        raise ValueError("quality_flags violate allowlist")
    return {
        "schema_version": CONTRACT_VERSION,
        "observation_id": record["observation_id"],
        "host": record["host"],
        "surface": record["surface"],
        "source": dict(source),
        "lineage": dict(lineage),
        "segment": dict(segment),
        "observed_at_ms": record["observed_at_ms"],
        "clock": dict(clock),
        "raw": dict(raw),
        "derived": dict(derived),
        "quality_flags": sorted(set(flags)),
    }


def reduce_usage_observations(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reduce unique immutable observations into marginal, unknown-capable usage.

    Replay is removed by observation identity.  Input order is retained only to
    detect out-of-order delivery; arithmetic is ordered by source timestamp and
    identity, making replay and transport ordering deterministic.  Distinct
    cumulative values for one segment at the same timestamp have no knowable
    order, so that segment remains unknown instead of fabricating or hiding a
    counter reset through an arbitrary identity tie-break.

    Raises:
        ValueError: If any observation violates the canonical allowlist/schema.
    """
    validated = [validate_observation(item) for item in observations]
    flags: set[str] = set()
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    latest_by_stream: dict[tuple[str, str], int] = {}
    for item in validated:
        if item["observation_id"] in seen:
            flags.add("replay")
            continue
        seen.add(item["observation_id"])
        stream = (item["lineage"]["session_hash"], item["source"]["identity_hash"])
        prior_stamp = latest_by_stream.get(stream)
        if prior_stamp is not None and item["observed_at_ms"] < prior_stamp:
            flags.add("out_of_order")
        latest_by_stream[stream] = max(prior_stamp or item["observed_at_ms"], item["observed_at_ms"])
        unique.append(item)

    same_timestamp_totals: dict[tuple[str, str, str, int], set[int]] = defaultdict(set)
    for item in unique:
        total = item["derived"]["additive_total_tokens"]
        if total is not None:
            frame = (
                item["lineage"]["session_hash"],
                item["source"]["identity_hash"],
                item["segment"]["id"],
                item["observed_at_ms"],
            )
            same_timestamp_totals[frame].add(total)
    ambiguous_frames = {
        frame for frame, totals in same_timestamp_totals.items() if len(totals) > 1
    }
    if ambiguous_frames:
        flags.add("same_timestamp_ambiguity")

    unique.sort(key=lambda item: (
        item["lineage"]["session_hash"],
        item["source"]["identity_hash"],
        item["observed_at_ms"],
        item["observation_id"],
    ))
    previous: dict[tuple[str, str, str], int] = {}
    indeterminate: set[tuple[str, str, str]] = set()
    known_subtotal = 0
    unknown_keys: set[tuple[str, str, str]] = set()
    unknown_reasons: set[str] = set()
    deltas: list[dict[str, Any]] = []
    for item in unique:
        flags.update(item["quality_flags"])
        segment = item["segment"]
        key = (
            item["lineage"]["session_hash"],
            item["source"]["identity_hash"],
            segment["id"],
        )
        frame = (*key, item["observed_at_ms"])
        total = item["derived"]["additive_total_tokens"]
        reason: str | None = None
        delta: int | None = None
        prior = previous.get(key)
        if frame in ambiguous_frames:
            reason = "same_timestamp_ambiguity"
            indeterminate.add(key)
        elif key in indeterminate:
            reason = "same_timestamp_ambiguity"
        elif total is None:
            reason = "unknown_components"
        elif segment["counter_scope"] != "session_own":
            reason = "ambiguous_inheritance" if segment["counter_scope"] == "inherited" else "unknown_counter_scope"
        elif prior is not None:
            if total < prior:
                reason = "counter_reset"
            else:
                delta = total - prior
        elif segment["baseline"] == "zero":
            delta = total
        elif segment["baseline"] == "ambiguous":
            reason = "ambiguous_inheritance"
        else:
            reason = "missing_baseline"
        if total is not None and key not in indeterminate:
            previous[key] = total
        if delta is None:
            unknown_keys.add(key)
            if reason is not None:
                unknown_reasons.add(reason)
        else:
            known_subtotal += delta
        deltas.append({
            "observation_id": item["observation_id"],
            "segment_id": segment["id"],
            "marginal_tokens": delta,
            "reason": reason,
        })

    completeness = "complete"
    if unknown_keys:
        completeness = "partial" if known_subtotal else "unknown"
    return {
        "schema_version": CONTRACT_VERSION,
        "known_subtotal_tokens": known_subtotal,
        "unknown_segment_count": len(unknown_keys),
        "unknown_reasons": sorted(unknown_reasons),
        "completeness": completeness,
        "marginal_deltas": deltas,
        "quality_flags": sorted(flags),
    }


def reduce_intervals(
    intervals: Sequence[Mapping[str, Any]], *, run_start_ms: int, run_end_ms: int
) -> dict[str, Any]:
    """Reduce labeled possibly-overlapping intervals against run boundaries.

    Idle is derived only when all intervals share a comparable clock, no skew
    or invalid boundary is observed, and every interval lies within the run.

    Raises:
        ValueError: If an interval contains non-allowlisted fields or types.
    """
    if isinstance(run_start_ms, bool) or isinstance(run_end_ms, bool) or not isinstance(run_start_ms, int) or not isinstance(run_end_ms, int):
        raise ValueError("run boundaries must be integers")
    quality: set[str] = set()
    if run_end_ms < run_start_ms:
        quality.add("clock_skew")
    labeled: dict[str, int] = defaultdict(int)
    valid_ranges: list[tuple[int, int]] = []
    clocks: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for interval in intervals:
        _require_exact_fields(interval, _INTERVAL_FIELDS, "interval")
        kind = interval["kind"]
        start = interval["start_ms"]
        end = interval["end_ms"]
        clock_source = interval["clock_source"]
        if kind not in _INTERVAL_KINDS or not isinstance(clock_source, str) or not clock_source:
            raise ValueError("unsupported interval kind or clock_source")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("interval boundaries must be integers")
        clocks.add(clock_source)
        normalized.append(dict(interval))
        if end < start:
            quality.add("clock_skew")
            continue
        if start < run_start_ms or end > run_end_ms:
            quality.add("outside_run_boundary")
        labeled[kind] += end - start
        valid_ranges.append((max(start, run_start_ms), min(end, run_end_ms)))
    if len(clocks) > 1:
        quality.add("incomparable_clocks")

    merged: list[list[int]] = []
    for start, end in sorted(pair for pair in valid_ranges if pair[1] >= pair[0]):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    covered = sum(end - start for start, end in merged)
    elapsed = run_end_ms - run_start_ms if run_end_ms >= run_start_ms else None
    summed = sum(labeled.values())
    idle = None if quality or elapsed is None else elapsed - covered
    return {
        "schema_version": CONTRACT_VERSION,
        "run_elapsed_ms": elapsed,
        "intervals": normalized,
        "labeled_duration_ms": dict(sorted(labeled.items())),
        "covered_duration_ms": covered,
        "overlap_duration_ms": max(0, summed - covered),
        "derived_idle_ms": idle,
        "clock_provenance": sorted(clocks),
        "quality_flags": sorted(quality),
    }


# ── Codex rollout adapter ──────────────────────────────────────────────────────

_EVENT_FIELDS = {
    "usage": {
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    },
    "turn_start": {"turn_id"},
    "turn_end": {"turn_id"},
    "first_token": {"turn_id"},
    "tool_start": {"tool_call_id"},
    "tool_end": {"tool_call_id"},
}
_BASE_FIELDS = {"schema_version", "session_id", "parent_session_id", "event", "timestamp"}


def _read_rows(sources: list[tuple[str, Path]]) -> tuple[list[dict[str, Any]], set[str]]:
    rows: list[dict[str, Any]] = []
    flags: set[str] = set()
    for source, path in sources:
        current_session: str | None = None
        current_parent: str | None = None
        turn_starts: dict[tuple[str, str], int] = {}
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            flags.add("unreadable_source")
            continue
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                # Rollouts can end with a torn JSONL row after interruption.
                flags.update({"malformed_row", "truncation", "truncated_row"})
                continue
            if not isinstance(value, dict):
                flags.add("malformed_row")
                continue
            if "event" in value or "schema_version" in value:
                if value.get("schema_version", CONTRACT_VERSION) != CONTRACT_VERSION:
                    flags.add("unknown_schema")
                    continue
                event = value.get("event")
                allowed = _BASE_FIELDS | _EVENT_FIELDS.get(event, set())
                if event not in _EVENT_FIELDS or set(value) - allowed:
                    flags.add("unknown_schema")
                    continue
                session_id = value.get("session_id")
                stamp = timestamp_ms(value.get("timestamp"))
                if not isinstance(session_id, str) or not session_id or stamp is None:
                    flags.add("malformed_row")
                    continue
                parent = value.get("parent_session_id")
                row = {"source": source, "session_id": session_id, "event": event, "timestamp": stamp}
                if isinstance(parent, str) and parent:
                    row["parent_session_id"] = parent
                for field in _EVENT_FIELDS[event]:
                    if field in value:
                        row[field] = value[field]
                rows.append(row)
                continue

            outer_type = value.get("type")
            payload = value.get("payload")
            stamp = timestamp_ms(value.get("timestamp"))
            if not isinstance(outer_type, str) or not isinstance(payload, dict) or stamp is None:
                flags.add("unknown_schema")
                continue
            if outer_type == "session_meta":
                session_id = payload.get("id") or payload.get("session_id")
                if not isinstance(session_id, str) or not session_id:
                    flags.add("malformed_row")
                    current_session = None
                    current_parent = None
                else:
                    current_session = session_id
                    parent = payload.get("forked_from_id")
                    current_parent = parent if isinstance(parent, str) and parent else None
                continue
            if current_session is None:
                flags.add("missing_session_meta")
                continue

            def append(event: str, event_stamp: int, **fields: Any) -> None:
                row = {"source": source, "session_id": current_session, "event": event, "timestamp": event_stamp}
                if current_parent is not None:
                    row["parent_session_id"] = current_parent
                row.update(fields)
                rows.append(row)

            payload_type = payload.get("type")
            if outer_type == "event_msg" and payload_type == "token_count":
                info = payload.get("info")
                usage = info.get("total_token_usage") if isinstance(info, dict) else None
                components = {
                    field: usage.get(field)
                    for field in _EVENT_FIELDS["usage"]
                } if isinstance(usage, dict) else {"total_tokens": None}
                append("usage", stamp, **components)
            elif outer_type == "event_msg" and payload_type == "task_started":
                turn_id = payload.get("turn_id")
                started = timestamp_ms(payload.get("started_at")) or stamp
                append("turn_start", started, turn_id=turn_id)
                if isinstance(turn_id, str) and turn_id:
                    turn_starts[(current_session, turn_id)] = started
            elif outer_type == "event_msg" and payload_type in {"task_complete", "turn_aborted"}:
                turn_id = payload.get("turn_id")
                ended = timestamp_ms(payload.get("completed_at")) or stamp
                append("turn_end", ended, turn_id=turn_id)
                ttft = payload.get("time_to_first_token_ms")
                started = turn_starts.get((current_session, turn_id)) if isinstance(turn_id, str) else None
                if isinstance(ttft, (int, float)) and not isinstance(ttft, bool) and started is not None:
                    append("first_token", started + int(ttft), turn_id=turn_id)
            elif outer_type == "response_item" and payload_type in {"function_call", "custom_tool_call"}:
                append("tool_start", stamp, tool_call_id=payload.get("call_id"))
            elif outer_type == "response_item" and payload_type in {"function_call_output", "custom_tool_call_output"}:
                append("tool_end", stamp, tool_call_id=payload.get("call_id"))
            elif outer_type == "turn_context":
                continue
            else:
                flags.add("unknown_schema")
    return rows, flags


def _fingerprint(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(key) for key in (
        "session_id",
        "event",
        "timestamp",
        "turn_id",
        "tool_call_id",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    ))


def _usage_observation(
    row: dict[str, Any], *, root_id: str, segment_id: str, baseline: str, counter_scope: str
) -> dict[str, Any]:
    def component(field: str) -> int | None:
        value = row.get(field)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    input_tokens = component("input_tokens")
    cached_input_tokens = component("cached_input_tokens")
    output_tokens = component("output_tokens")
    reasoning_output_tokens = component("reasoning_output_tokens")
    total = component("total_tokens")
    additive_total = input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else total
    uncached_input = input_tokens - cached_input_tokens if input_tokens is not None and cached_input_tokens is not None else None
    session_id = row["session_id"]
    parent_id = row.get("parent_session_id")
    identity = "codex-rollout"
    marker = "|".join(str(item) for item in _fingerprint(row))
    return {
        "schema_version": CONTRACT_VERSION,
        "observation_id": _hash_identifier(marker),
        "host": "codex",
        "surface": "native_rollout",
        "source": {"kind": row["source"], "identity_hash": _hash_identifier(identity), "semantics_version": SOURCE_SEMANTICS_VERSION},
        "lineage": {
            "session_hash": session_hash(session_id),
            "root_session_hash": session_hash(root_id),
            "parent_session_hash": session_hash(parent_id) if isinstance(parent_id, str) else None,
        },
        "segment": {"id": segment_id, "baseline": baseline, "counter_scope": counter_scope},
        "observed_at_ms": row["timestamp"],
        "clock": {"kind": "wall", "source": "provider", "skew_ms": None},
        "raw": {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_output_tokens": reasoning_output_tokens,
            "total_tokens": total,
        },
        "derived": {
            "uncached_input_tokens": uncached_input,
            "additive_total_tokens": additive_total,
            "equation_version": SOURCE_SEMANTICS_VERSION,
        },
        "quality_flags": [],
    }


def _make_session(
    session_id: str,
    rows: list[dict[str, Any]],
    source_labels: set[str],
    inherited: set[str],
    root_id: str,
) -> dict[str, Any]:
    flags = set(inherited)
    original_stamps = [item["timestamp"] for item in rows if item["event"] == "usage"]
    if original_stamps != sorted(original_stamps):
        flags.add("out_of_order")
    rows.sort(key=lambda item: item["timestamp"])
    usage_observations: list[dict[str, Any]] = []
    segment_number = 0
    previous_valid: int | None = None
    after_invalid = False
    for row in rows:
        if row["event"] != "usage":
            continue
        raw = row.get("total_tokens")
        valid = isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0
        if not valid:
            flags.add("negative_token_counter" if isinstance(raw, int) and not isinstance(raw, bool) and raw < 0 else "unknown_token_counter")
            segment_number += 1
            previous_valid = None
            after_invalid = True
            continue
        if previous_valid is not None and raw < previous_valid:
            flags.add("counter_reset")
            segment_number += 1
            baseline = "missing"
        elif previous_valid is None and after_invalid:
            flags.add("counter_segment_baseline")
            baseline = "missing"
            after_invalid = False
        elif previous_valid is None and isinstance(row.get("parent_session_id"), str):
            # A child's first cumulative value may include inherited context.
            # Later observations can still contribute their session-own delta.
            baseline = "ambiguous"
        else:
            baseline = "zero" if previous_valid is None else "previous"
        scope = "inherited" if baseline == "ambiguous" else "session_own"
        usage_observations.append(_usage_observation(
            row,
            root_id=root_id,
            segment_id=f"segment-{segment_number}",
            baseline=baseline,
            counter_scope=scope,
        ))
        previous_valid = raw
    reduced = reduce_usage_observations(usage_observations)
    flags.update(reduced["quality_flags"])
    saw_usage = bool(usage_observations)

    turn_starts: dict[str, int] = {}
    turn_ends: dict[str, int] = {}
    first_tokens: dict[str, int] = {}
    tool_starts: dict[str, int] = {}
    intervals: list[dict[str, Any]] = []
    for row in rows:
        event = row["event"]
        if event in {"turn_start", "turn_end", "first_token"}:
            turn_id = row.get("turn_id")
            if not isinstance(turn_id, str) or not turn_id:
                flags.add("malformed_row")
                continue
            {"turn_start": turn_starts, "turn_end": turn_ends, "first_token": first_tokens}[event].setdefault(turn_id, row["timestamp"])
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
                started = tool_starts.pop(tool_id)
                if row["timestamp"] < started:
                    flags.add("negative_timing")
                intervals.append({
                    "kind": "tool_wait",
                    "start_ms": started,
                    "end_ms": row["timestamp"],
                    "clock_source": "provider",
                })
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
        ended = turn_ends.get(turn_id)
        if ended is not None:
            if ended < started:
                flags.add("negative_timing")
            intervals.append({
                "kind": "active",
                "start_ms": started,
                "end_ms": ended,
                "clock_source": "provider",
            })

    valid_active = [item for item in intervals if item["kind"] == "active" and item["end_ms"] >= item["start_ms"]]
    boundary_intervals = valid_active or [
        item for item in intervals if item["end_ms"] >= item["start_ms"]
    ]
    timing = None
    if boundary_intervals:
        run_start_ms = min(item["start_ms"] for item in boundary_intervals)
        run_end_ms = max(item["end_ms"] for item in boundary_intervals)
        timing = reduce_intervals(intervals, run_start_ms=run_start_ms, run_end_ms=run_end_ms)
        flags.update(timing["quality_flags"])

    token_total = reduced["known_subtotal_tokens"]
    token_count = token_total if saw_usage and reduced["completeness"] == "complete" else None
    labeled_duration = timing["labeled_duration_ms"] if timing is not None else {}
    idle_total = timing["derived_idle_ms"] if timing is not None else None
    return {
        "session_hash": session_hash(session_id),
        "source": "both" if source_labels == {"live", "archive"} else next(iter(source_labels)),
        "token_count": token_count,
        "turn_count": len(turn_starts) if turn_starts else None,
        "ttft_ms": ttft_total if saw_ttft else None,
        "ttft_precision": "exact" if saw_ttft else "unknown",
        "tool_wait_ms": labeled_duration.get("tool_wait"),
        "tool_wait_precision": "exact" if "tool_wait" in labeled_duration else "unknown",
        "inferred_idle_ms": idle_total,
        "idle_precision": "inferred" if idle_total is not None else "unknown",
        "canonical_usage": reduced,
        "canonical_timing": timing,
        "quality_flags": sorted(flags),
    }


def summarize_sources(sources: list[tuple[str, Path]]) -> dict[str, Any]:
    """Normalize Codex rollout sources through the canonical shared reducers.

    Source read/schema failures are best-effort and appear as quality flags;
    no path or unallowlisted value is returned.
    """
    rows, global_flags = _read_rows(sources)
    seen: set[tuple[Any, ...]] = set()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, set[str]] = defaultdict(set)
    parents: dict[str, str] = {}
    for row in rows:
        marker = _fingerprint(row)
        labels[row["session_id"]].add(row["source"])
        parent = row.get("parent_session_id")
        if isinstance(parent, str):
            parents[row["session_id"]] = parent
        if marker in seen:
            continue
        seen.add(marker)
        grouped[row["session_id"]].append(row)

    def root_for(session_id: str) -> str:
        visited = {session_id}
        current = session_id
        while current in parents and parents[current] not in visited:
            current = parents[current]
            visited.add(current)
        return current

    sessions = [
        _make_session(key, grouped[key], labels[key], global_flags, root_for(key))
        for key in sorted(grouped, key=session_hash)
    ]
    return {"schema_version": CONTRACT_VERSION, "sessions": sessions, "quality_flags": sorted(global_flags)}
