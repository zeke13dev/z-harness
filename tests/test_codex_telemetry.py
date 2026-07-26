"""Focused privacy and accounting tests for scripts/codex-telemetry.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "codex-telemetry.py"
SPEC = importlib.util.spec_from_file_location("codex_telemetry", SCRIPT)
assert SPEC and SPEC.loader
telemetry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(telemetry)


def write_jsonl(path: Path, rows: list[object]) -> Path:
    path.write_text("\n".join(json.dumps(row) if not isinstance(row, str) else row for row in rows))
    return path


def representative_current_rollout(session_id: str, sentinel: str) -> list[object]:
    """Return a provenance-documented sanitized current rollout fixture.

    Derived from the key/type shapes and event relationships in representative
    live and archived local Codex rollouts inspected on 2026-07-16. Identifiers
    and all content are invented; no original payload value is retained.
    """
    return [
        {"timestamp": "2026-07-16T10:00:00Z", "type": "session_meta", "payload": {
            "id": session_id, "session_id": "sanitized-logical-session",
            "forked_from_id": "sanitized-parent", "cwd": sentinel,
        }},
        {"timestamp": "2026-07-16T10:00:01Z", "type": "event_msg", "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
            }}, "rate_limits": {"secret": sentinel},
        }},
        {"timestamp": "2026-07-16T10:00:02Z", "type": "event_msg", "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
            }},
        }},
        {"timestamp": "2026-07-16T10:00:03Z", "type": "event_msg", "payload": {
            "type": "task_started", "turn_id": "sanitized-turn",
            "started_at": "2026-07-16T10:00:03Z",
        }},
        {"timestamp": "2026-07-16T10:00:03.250Z", "type": "response_item", "payload": {
            "type": "function_call", "call_id": "sanitized-call", "name": sentinel,
            "arguments": sentinel,
        }},
        {"timestamp": "2026-07-16T10:00:03.500Z", "type": "response_item", "payload": {
            "type": "function_call_output", "call_id": "sanitized-call", "output": sentinel,
        }},
        {"timestamp": "2026-07-16T10:00:03.550Z", "type": "response_item", "payload": {
            "type": "custom_tool_call", "call_id": "sanitized-custom-call",
            "name": sentinel, "input": sentinel,
        }},
        {"timestamp": "2026-07-16T10:00:03.700Z", "type": "response_item", "payload": {
            "type": "custom_tool_call_output", "call_id": "sanitized-custom-call",
            "output": sentinel,
        }},
        {"timestamp": "2026-07-16T10:00:04Z", "type": "event_msg", "payload": {
            "type": "task_complete", "turn_id": "sanitized-turn",
            "completed_at": "2026-07-16T10:00:04Z", "duration_ms": 1000,
            "time_to_first_token_ms": 200, "last_agent_message": sentinel,
        }},
    ]


def representative_flat_v1_rollout(session_id: str) -> list[object]:
    """Return a provenance-documented sanitized flat-v1 rollout fixture.

    Derived by projecting the allowlisted metric-bearing event relationships
    from representative live and archived local Codex rollouts inspected on
    2026-07-16 into the supported flat-v1 envelope. Identifiers, timestamps,
    and counters are invented; no original rollout value is retained.
    """
    return [
        {
            "schema_version": 1,
            "session_id": session_id,
            "event": "usage",
            "timestamp": "2026-07-16T09:00:00Z",
            "total_tokens": 10,
        },
        {
            "schema_version": 1,
            "session_id": session_id,
            "event": "usage",
            "timestamp": "2026-07-16T09:00:01Z",
            "total_tokens": 15,
        },
        {
            "schema_version": 1,
            "session_id": session_id,
            "event": "turn_start",
            "timestamp": "2026-07-16T09:00:02Z",
            "turn_id": "sanitized-turn",
        },
        {
            "schema_version": 1,
            "session_id": session_id,
            "event": "first_token",
            "timestamp": "2026-07-16T09:00:02.200Z",
            "turn_id": "sanitized-turn",
        },
        {
            "schema_version": 1,
            "session_id": session_id,
            "event": "tool_start",
            "timestamp": "2026-07-16T09:00:02.250Z",
            "tool_call_id": "sanitized-call",
        },
        {
            "schema_version": 1,
            "session_id": session_id,
            "event": "tool_end",
            "timestamp": "2026-07-16T09:00:02.500Z",
            "tool_call_id": "sanitized-call",
        },
        {
            "schema_version": 1,
            "session_id": session_id,
            "event": "turn_end",
            "timestamp": "2026-07-16T09:00:03Z",
            "turn_id": "sanitized-turn",
        },
    ]


def test_flat_v1_live_archive_fixture_normalizes_end_to_end(tmp_path: Path) -> None:
    fixture = representative_flat_v1_rollout("flat-v1-session")
    live = write_jsonl(tmp_path / "live-flat-v1.jsonl", fixture)
    archive = write_jsonl(tmp_path / "archive-flat-v1.jsonl", fixture)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", f"live:{live}", "--source", f"archive:{archive}"],
        text=True,
        capture_output=True,
        check=True,
    )

    assert str(tmp_path) not in completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["quality_flags"] == []
    session = payload["sessions"][0]
    assert session["session_hash"] == telemetry.session_hash("flat-v1-session")
    assert session["source"] == "both"
    assert session["token_count"] == 15
    assert session["tool_wait_ms"] == 250
    assert session["ttft_ms"] == 200
    assert session["canonical_usage"]["completeness"] == "complete"
    assert session["canonical_timing"]["overlap_duration_ms"] == 250


def test_current_rollout_live_archive_fixture_normalizes_end_to_end(tmp_path: Path) -> None:
    sentinel = "PROMPT reasoning tool-output sk-secret /absolute/private/path"
    fixture = representative_current_rollout("current-session", sentinel)
    live = write_jsonl(tmp_path / "live-current.jsonl", fixture)
    archive = write_jsonl(tmp_path / "archive-current.jsonl", fixture)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", f"live:{live}", "--source", f"archive:{archive}"],
        text=True,
        capture_output=True,
        check=True,
    )

    assert sentinel not in completed.stdout
    assert str(tmp_path) not in completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["quality_flags"] == []
    session = payload["sessions"][0]
    assert session["session_hash"] == telemetry.session_hash("current-session")
    assert session["source"] == "both"
    assert session["token_count"] is None
    assert session["tool_wait_ms"] == 400
    assert session["ttft_ms"] == 200
    assert session["canonical_usage"]["known_subtotal_tokens"] == 5
    assert session["canonical_usage"]["unknown_reasons"] == ["ambiguous_inheritance"]
    assert session["canonical_timing"]["overlap_duration_ms"] == 400


def test_current_rollout_fork_counters_and_unknown_envelope_are_safe(tmp_path: Path) -> None:
    sentinel = "PROMPT reasoning tool-argument sk-secret /absolute/private/path"
    parent = representative_current_rollout("parent", sentinel)[:3]
    child = [
        {"timestamp": "2026-07-16T11:00:00Z", "type": "session_meta", "payload": {
            "id": "child", "forked_from_id": "parent", "base_instructions": sentinel,
        }},
        {"timestamp": "2026-07-16T11:00:01Z", "type": "event_msg", "payload": {
            "type": "token_count", "info": {"total_token_usage": {"total_tokens": 4}},
        }},
        {"timestamp": "2026-07-16T11:00:02Z", "type": "future_envelope", "payload": {
            "private": sentinel,
        }},
    ]
    source = write_jsonl(tmp_path / "fork-current.jsonl", parent + child)

    rendered = json.dumps(telemetry.summarize([("live", source)]))

    assert sentinel not in rendered
    sessions = {item["session_hash"]: item for item in json.loads(rendered)["sessions"]}
    assert sessions[telemetry.session_hash("parent")]["token_count"] is None
    assert sessions[telemetry.session_hash("child")]["token_count"] is None
    assert sessions[telemetry.session_hash("child")]["canonical_usage"]["completeness"] == "unknown"
    assert "unknown_schema" in sessions[telemetry.session_hash("child")]["quality_flags"]


def test_dedup_fork_segments_and_exact_timing(tmp_path: Path) -> None:
    live = write_jsonl(tmp_path / "live.jsonl", [
        {"session_id": "parent", "event": "usage", "timestamp": 1, "total_tokens": 10},
        {"session_id": "parent", "event": "usage", "timestamp": 2, "total_tokens": 15},
        {"session_id": "child", "parent_session_id": "parent", "event": "usage", "timestamp": 3, "total_tokens": 7},
        {"session_id": "child", "event": "turn_start", "timestamp": 4, "turn_id": "t"},
        {"session_id": "child", "event": "first_token", "timestamp": 4.25, "turn_id": "t"},
        {"session_id": "child", "event": "tool_start", "timestamp": 4.3, "tool_call_id": "x"},
        {"session_id": "child", "event": "tool_end", "timestamp": 4.5, "tool_call_id": "x"},
    ])
    archive = write_jsonl(tmp_path / "archive.jsonl", [
        {"session_id": "parent", "event": "usage", "timestamp": 2, "total_tokens": 15},
    ])
    result = telemetry.summarize([("live", live), ("archive", archive)])
    parent, child = sorted(result["sessions"], key=lambda item: item["token_count"] or 0, reverse=True)
    assert parent["token_count"] == 15 and parent["source"] == "both"
    assert child["token_count"] is None
    assert child["canonical_usage"]["unknown_reasons"] == ["ambiguous_inheritance"]
    assert child["ttft_ms"] == 250 and child["ttft_precision"] == "exact"
    assert child["tool_wait_ms"] == 200 and child["tool_wait_precision"] == "exact"


def test_resets_unknowns_and_malformed_rows_are_quality_flagged(tmp_path: Path) -> None:
    source = write_jsonl(tmp_path / "events.jsonl", [
        {"session_id": "s", "event": "usage", "timestamp": 1, "total_tokens": 10},
        {"session_id": "s", "event": "usage", "timestamp": 2, "total_tokens": 3},
        {"session_id": "s", "event": "usage", "timestamp": 3, "total_tokens": 5},
        {"session_id": "s", "event": "usage", "timestamp": 4, "total_tokens": -1},
        "{bad truncation",
        {"session_id": "s", "event": "mystery", "timestamp": 5},
    ])
    result = telemetry.summarize([("live", source)])
    session = result["sessions"][0]
    assert session["token_count"] is None
    assert {"counter_reset", "negative_token_counter", "malformed_row", "truncation", "unknown_schema"} <= set(session["quality_flags"])


@pytest.mark.parametrize(
    ("invalid_usage", "invalid_flag"),
    [
        ({}, "unknown_token_counter"),
        ({"total_tokens": "not-an-integer"}, "unknown_token_counter"),
        ({"total_tokens": -1}, "negative_token_counter"),
    ],
    ids=["missing", "non-integer", "negative"],
)
def test_invalid_counter_starts_a_non_accounted_segment_baseline(
    tmp_path: Path, invalid_usage: dict[str, object], invalid_flag: str
) -> None:
    source = write_jsonl(tmp_path / "events.jsonl", [
        {"session_id": "s", "event": "usage", "timestamp": 1, "total_tokens": 10},
        {"session_id": "s", "event": "usage", "timestamp": 2, **invalid_usage},
        {"session_id": "s", "event": "usage", "timestamp": 3, "total_tokens": 20},
        {"session_id": "s", "event": "usage", "timestamp": 4, "total_tokens": 25},
    ])

    session = telemetry.summarize([("live", source)])["sessions"][0]

    assert session["token_count"] is None
    assert {invalid_flag, "counter_segment_baseline"} <= set(session["quality_flags"])


def test_idle_precision_is_inferred_only_for_observed_turn_gaps(tmp_path: Path) -> None:
    source = write_jsonl(tmp_path / "events.jsonl", [
        {"session_id": "s", "event": "turn_start", "timestamp": 1, "turn_id": "one"},
        {"session_id": "s", "event": "turn_end", "timestamp": 2, "turn_id": "one"},
        {"session_id": "s", "event": "turn_start", "timestamp": 3, "turn_id": "two"},
        {"session_id": "s", "event": "turn_end", "timestamp": 4, "turn_id": "two"},
    ])

    session = telemetry.summarize([("live", source)])["sessions"][0]

    assert session["inferred_idle_ms"] == 1000
    assert session["idle_precision"] == "inferred"


def test_adapter_embeds_full_usage_and_reduces_overlapping_provider_intervals(
    tmp_path: Path,
) -> None:
    source = write_jsonl(tmp_path / "adapter.jsonl", [
        {"session_id": "root", "event": "usage", "timestamp": 1, "total_tokens": 10},
        {"session_id": "root", "event": "usage", "timestamp": 2, "total_tokens": 15},
        {"session_id": "root", "event": "turn_start", "timestamp": 10, "turn_id": "one"},
        {"session_id": "root", "event": "first_token", "timestamp": 10.1, "turn_id": "one"},
        {"session_id": "root", "event": "tool_start", "timestamp": 10.2, "tool_call_id": "tool"},
        {"session_id": "root", "event": "turn_start", "timestamp": 10.5, "turn_id": "two"},
        {"session_id": "root", "event": "first_token", "timestamp": 10.6, "turn_id": "two"},
        {"session_id": "root", "event": "tool_end", "timestamp": 10.8, "tool_call_id": "tool"},
        {"session_id": "root", "event": "turn_end", "timestamp": 11, "turn_id": "one"},
        {"session_id": "root", "event": "turn_end", "timestamp": 12, "turn_id": "two"},
    ])

    session = telemetry.summarize([("live", source)])["sessions"][0]

    usage = session["canonical_usage"]
    assert set(usage) == {
        "schema_version", "known_subtotal_tokens", "unknown_segment_count",
        "unknown_reasons", "completeness", "marginal_deltas", "quality_flags",
    }
    assert usage["known_subtotal_tokens"] == 15
    assert usage["unknown_segment_count"] == 0
    assert [item["marginal_tokens"] for item in usage["marginal_deltas"]] == [10, 5]

    timing = session["canonical_timing"]
    assert timing["run_elapsed_ms"] == 2000
    assert timing["labeled_duration_ms"] == {"active": 2500, "tool_wait": 600}
    assert timing["covered_duration_ms"] == 2000
    assert timing["overlap_duration_ms"] == 1100
    assert timing["derived_idle_ms"] == 0
    assert timing["clock_provenance"] == ["provider"]


def test_adapter_excludes_ambiguous_child_baseline_but_counts_later_delta(
    tmp_path: Path,
) -> None:
    source = write_jsonl(tmp_path / "child.jsonl", [
        {
            "session_id": "child", "parent_session_id": "root",
            "event": "usage", "timestamp": 1, "total_tokens": 10,
        },
        {
            "session_id": "child", "parent_session_id": "root",
            "event": "usage", "timestamp": 2, "total_tokens": 15,
        },
    ])

    session = telemetry.summarize([("live", source)])["sessions"][0]
    usage = session["canonical_usage"]

    assert session["token_count"] is None
    assert usage["known_subtotal_tokens"] == 5
    assert usage["unknown_segment_count"] == 1
    assert usage["unknown_reasons"] == ["ambiguous_inheritance"]
    assert usage["completeness"] == "partial"
    assert [item["marginal_tokens"] for item in usage["marginal_deltas"]] == [None, 5]


def test_output_is_fixed_allowlist_and_does_not_leak_sensitive_values(tmp_path: Path) -> None:
    sentinel = "PROMPT reasoning tool-output sk-secret /absolute/private/path"
    source = write_jsonl(tmp_path / "events.jsonl", [
        {"session_id": "safe", "event": "usage", "timestamp": 1, "total_tokens": 1, "prompt": sentinel},
        {"session_id": "safe", "event": "turn_start", "timestamp": 2, "turn_id": sentinel},
    ])
    rendered = json.dumps(telemetry.summarize([("archive", source)]))
    assert sentinel not in rendered and "events.jsonl" not in rendered
    payload = json.loads(rendered)
    assert set(payload) == {"schema_version", "sessions", "quality_flags"}
    assert set(payload["sessions"][0]) == {
        "session_hash", "source", "token_count", "turn_count", "ttft_ms",
        "ttft_precision", "tool_wait_ms", "tool_wait_precision",
        "inferred_idle_ms", "idle_precision", "canonical_usage",
        "canonical_timing", "quality_flags",
    }


def test_standalone_cli_reports_normalized_metrics_without_sensitive_values(
    tmp_path: Path,
) -> None:
    sentinel = "PROMPT reasoning tool-argument tool-output sk-secret /absolute/private/path"
    live = write_jsonl(tmp_path / "live.jsonl", [
        {"session_id": "cli", "event": "usage", "timestamp": 1, "total_tokens": 10},
        {"session_id": "cli", "event": "usage", "timestamp": 2, "total_tokens": 15},
        {"session_id": "cli", "event": "turn_start", "timestamp": 3, "turn_id": "one"},
        {"session_id": "cli", "event": "first_token", "timestamp": 3.2, "turn_id": "one"},
        {"session_id": "cli", "event": "tool_start", "timestamp": 3.25, "tool_call_id": "tool"},
        {"session_id": "cli", "event": "tool_end", "timestamp": 3.5, "tool_call_id": "tool"},
        {"session_id": "cli", "event": "turn_end", "timestamp": 4, "turn_id": "one"},
        {"session_id": "cli", "event": "turn_start", "timestamp": 5, "turn_id": "two"},
        # Unknown fields make this row schema drift; the value must never be retained.
        {"session_id": "cli", "event": "usage", "timestamp": 6, "total_tokens": 99, "prompt": sentinel},
    ])
    archive = write_jsonl(tmp_path / "archive.jsonl", [
        # Duplicate live usage proves live/archive deduplication in the CLI path.
        {"session_id": "cli", "event": "usage", "timestamp": 2, "total_tokens": 15},
        "{truncated",
    ])

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            f"live:{live}",
            "--source",
            f"archive:{archive}",
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    assert sentinel not in completed.stdout
    assert str(tmp_path) not in completed.stdout
    payload = json.loads(completed.stdout)
    session = payload["sessions"][0]
    assert session["session_hash"] == telemetry.session_hash("cli")
    assert session["source"] == "both"
    assert session["token_count"] == 15
    assert session["tool_wait_ms"] == 250
    assert session["ttft_ms"] == 200
    assert session["canonical_usage"]["known_subtotal_tokens"] == 15
    assert session["canonical_usage"]["completeness"] == "complete"
    assert session["canonical_timing"]["clock_provenance"] == ["provider"]
    assert set(session["quality_flags"]) == {
        "malformed_row",
        "missing_first_token",
        "truncated_row",
        "truncation",
        "unknown_schema",
    }
    assert payload["quality_flags"] == [
        "malformed_row",
        "truncated_row",
        "truncation",
        "unknown_schema",
    ]


@pytest.mark.parametrize(
    ("child_usage", "expected_flags"),
    [
        (
            [
                {"total_tokens": 10},
                {"total_tokens": 3},
                {"total_tokens": 5},
            ],
            {"counter_reset"},
        ),
        (
            [
                {"total_tokens": 10},
                {"total_tokens": -1},
                {"total_tokens": 20},
                {"total_tokens": 25},
            ],
            {"negative_token_counter", "counter_segment_baseline"},
        ),
        (
            [
                {"total_tokens": 10},
                {},
                {"total_tokens": 20},
                {"total_tokens": 25},
            ],
            {"unknown_token_counter", "counter_segment_baseline"},
        ),
        (
            [
                {"total_tokens": 10},
                {"total_tokens": "not-an-integer"},
                {"total_tokens": 20},
                {"total_tokens": 25},
            ],
            {"unknown_token_counter", "counter_segment_baseline"},
        ),
    ],
    ids=["reset", "negative", "missing", "non-integer"],
)
def test_standalone_cli_keeps_fork_counters_isolated_across_counter_transitions(
    tmp_path: Path,
    child_usage: list[dict[str, object]],
    expected_flags: set[str],
) -> None:
    sentinel = "PROMPT reasoning tool-output sk-secret /absolute/private/path"
    rows: list[object] = [
        {"session_id": "parent", "event": "usage", "timestamp": 1, "total_tokens": 100},
        {"session_id": "parent", "event": "usage", "timestamp": 2, "total_tokens": 110},
    ]
    rows.extend(
        {
            "session_id": "child",
            "parent_session_id": "parent",
            "event": "usage",
            "timestamp": timestamp,
            **usage,
        }
        for timestamp, usage in enumerate(child_usage, start=3)
    )
    rows.extend(
        [
            {
                "session_id": "child",
                "parent_session_id": "parent",
                "event": "turn_start",
                "timestamp": 10,
                "turn_id": sentinel,
            },
            {
                "session_id": "child",
                "parent_session_id": "parent",
                "event": "first_token",
                "timestamp": 10.1,
                "turn_id": sentinel,
            },
        ]
    )
    source = write_jsonl(tmp_path / "fork.jsonl", rows)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", f"live:{source}"],
        text=True,
        capture_output=True,
        check=True,
    )

    assert sentinel not in completed.stdout
    assert str(tmp_path) not in completed.stdout
    sessions = {
        session["session_hash"]: session
        for session in json.loads(completed.stdout)["sessions"]
    }
    parent = sessions[telemetry.session_hash("parent")]
    child = sessions[telemetry.session_hash("child")]
    assert parent["token_count"] == 110
    assert parent["quality_flags"] == []
    assert child["token_count"] is None
    assert set(child["quality_flags"]) == expected_flags
    assert child["canonical_usage"]["unknown_segment_count"] == 2
    assert "ambiguous_inheritance" in child["canonical_usage"]["unknown_reasons"]


def canonical_observation(
    observation_id: str,
    total: int | None,
    *,
    timestamp: int,
    session: str = "root",
    root: str = "root",
    parent: str | None = None,
    segment: str = "segment-0",
    baseline: str = "previous",
    scope: str = "session_own",
    input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    reasoning_output_tokens: int | None = None,
) -> dict[str, object]:
    """Build one explicit canonical fixture without content-bearing fields."""
    additive = input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else total
    uncached = input_tokens - cached_input_tokens if input_tokens is not None and cached_input_tokens is not None else None
    return {
        "schema_version": telemetry.VERSION,
        "observation_id": observation_id,
        "host": "codex",
        "surface": "codex_cli",
        "source": {
            "kind": "live",
            "identity_hash": telemetry.session_hash("source"),
            "semantics_version": "codex-rollout-v1",
        },
        "lineage": {
            "session_hash": telemetry.session_hash(session),
            "root_session_hash": telemetry.session_hash(root),
            "parent_session_hash": telemetry.session_hash(parent) if parent is not None else None,
        },
        "segment": {
            "id": segment,
            "baseline": baseline,
            "counter_scope": scope,
        },
        "observed_at_ms": timestamp,
        "clock": {"kind": "wall", "source": "provider", "skew_ms": None},
        "raw": {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_output_tokens": reasoning_output_tokens,
            "total_tokens": total,
        },
        "derived": {
            "uncached_input_tokens": uncached,
            "additive_total_tokens": additive,
            "equation_version": "codex-rollout-v1",
        },
        "quality_flags": [],
    }


def test_canonical_observation_preserves_provenance_and_rejects_content() -> None:
    observation = canonical_observation(
        "component-observation",
        15,
        timestamp=1,
        session="child-hash",
        root="root-hash",
        parent="parent-hash",
        baseline="zero",
        input_tokens=10,
        cached_input_tokens=4,
        output_tokens=5,
        reasoning_output_tokens=2,
    )

    validated = telemetry.validate_observation(observation)

    assert validated["lineage"] == {
        "session_hash": telemetry.session_hash("child-hash"),
        "root_session_hash": telemetry.session_hash("root-hash"),
        "parent_session_hash": telemetry.session_hash("parent-hash"),
    }
    assert validated["source"]["semantics_version"] == "codex-rollout-v1"
    assert validated["raw"] == {
        "input_tokens": 10,
        "cached_input_tokens": 4,
        "output_tokens": 5,
        "reasoning_output_tokens": 2,
        "total_tokens": 15,
    }
    assert validated["derived"] == {
        "uncached_input_tokens": 6,
        "additive_total_tokens": 15,
        "equation_version": "codex-rollout-v1",
    }

    content_bearing = dict(observation)
    content_bearing["prompt"] = "must never enter canonical telemetry"
    with pytest.raises(ValueError, match="allowlist"):
        telemetry.validate_observation(content_bearing)

    content_in_allowlisted_field = dict(observation)
    content_in_allowlisted_field["surface"] = "prompt contents / private/path"
    with pytest.raises(ValueError, match="surface"):
        telemetry.validate_observation(content_in_allowlisted_field)


@pytest.mark.parametrize(
    ("raw_changes", "derived_changes", "message"),
    [
        ({"cached_input_tokens": 11}, {"uncached_input_tokens": 0}, "cached input"),
        ({"reasoning_output_tokens": 6}, {}, "reasoning output"),
        ({"total_tokens": 16}, {}, "conservation"),
    ],
)
def test_component_equations_fail_closed_on_nonconservation(
    raw_changes: dict[str, int], derived_changes: dict[str, int], message: str
) -> None:
    observation = canonical_observation(
        "bad-components",
        15,
        timestamp=1,
        baseline="zero",
        input_tokens=10,
        cached_input_tokens=4,
        output_tokens=5,
        reasoning_output_tokens=2,
    )
    observation["raw"] = {**observation["raw"], **raw_changes}
    observation["derived"] = {**observation["derived"], **derived_changes}

    with pytest.raises(ValueError, match=message):
        telemetry.validate_observation(observation)


def test_reducer_is_replay_safe_and_deterministic_for_equal_and_out_of_order_frames() -> None:
    first = canonical_observation("first", 10, timestamp=1, baseline="zero")
    equal = canonical_observation("equal", 10, timestamp=2)
    last = canonical_observation("last", 15, timestamp=3)

    result = telemetry.reduce_usage_observations([last, first, equal, equal])

    assert result["known_subtotal_tokens"] == 15
    assert result["unknown_segment_count"] == 0
    assert result["completeness"] == "complete"
    assert {"out_of_order", "replay"} <= set(result["quality_flags"])
    deltas = {item["observation_id"]: item["marginal_tokens"] for item in result["marginal_deltas"]}
    assert deltas == {"first": 10, "equal": 0, "last": 5}


def test_reducer_marks_differing_same_timestamp_counters_ambiguous_regardless_of_order() -> None:
    baseline = canonical_observation("baseline", 5, timestamp=1, baseline="zero")
    larger = canonical_observation("a-larger", 20, timestamp=2)
    smaller = canonical_observation("z-smaller", 10, timestamp=2)
    later = canonical_observation("later", 25, timestamp=3)

    larger_first = telemetry.reduce_usage_observations(
        [baseline, larger, smaller, later]
    )
    smaller_first = telemetry.reduce_usage_observations(
        [baseline, smaller, larger, later]
    )

    assert larger_first == smaller_first
    assert larger_first["known_subtotal_tokens"] == 5
    assert larger_first["unknown_segment_count"] == 1
    assert larger_first["unknown_reasons"] == ["same_timestamp_ambiguity"]
    assert larger_first["completeness"] == "partial"
    assert "same_timestamp_ambiguity" in larger_first["quality_flags"]
    assert {
        item["observation_id"]: (item["marginal_tokens"], item["reason"])
        for item in larger_first["marginal_deltas"]
    } == {
        "baseline": (5, None),
        "a-larger": (None, "same_timestamp_ambiguity"),
        "z-smaller": (None, "same_timestamp_ambiguity"),
        "later": (None, "same_timestamp_ambiguity"),
    }


def test_reducer_marks_reset_missing_baseline_and_ambiguous_inheritance_unknown() -> None:
    observations = [
        canonical_observation("root-start", 10, timestamp=1, baseline="zero"),
        canonical_observation("root-reset", 3, timestamp=2),
        canonical_observation("root-after-reset", 5, timestamp=3),
        canonical_observation(
            "missing",
            7,
            timestamp=1,
            session="missing-session",
            root="missing-session",
            segment="missing-segment",
            baseline="missing",
        ),
        canonical_observation(
            "child",
            20,
            timestamp=1,
            session="child",
            root="root",
            parent="root",
            segment="child-segment",
            baseline="ambiguous",
            scope="inherited",
        ),
    ]

    result = telemetry.reduce_usage_observations(observations)

    assert result["known_subtotal_tokens"] == 12
    assert result["unknown_segment_count"] == 3
    assert result["unknown_reasons"] == [
        "ambiguous_inheritance",
        "counter_reset",
        "missing_baseline",
    ]
    assert result["completeness"] == "partial"


def test_interval_reducer_preserves_overlap_and_invalidates_idle_on_skew() -> None:
    intervals = [
        {"kind": "active", "start_ms": 0, "end_ms": 100, "clock_source": "provider"},
        {"kind": "dispatch", "start_ms": 20, "end_ms": 60, "clock_source": "provider"},
        {"kind": "tool_wait", "start_ms": 40, "end_ms": 80, "clock_source": "provider"},
    ]

    result = telemetry.reduce_intervals(intervals, run_start_ms=0, run_end_ms=120)

    assert result["run_elapsed_ms"] == 120
    assert result["labeled_duration_ms"] == {"active": 100, "dispatch": 40, "tool_wait": 40}
    assert result["covered_duration_ms"] == 100
    assert result["overlap_duration_ms"] == 80
    assert result["derived_idle_ms"] == 20
    assert result["clock_provenance"] == ["provider"]

    skewed = telemetry.reduce_intervals(
        [{"kind": "active", "start_ms": 90, "end_ms": 80, "clock_source": "provider"}],
        run_start_ms=0,
        run_end_ms=120,
    )
    assert skewed["derived_idle_ms"] is None
    assert skewed["quality_flags"] == ["clock_skew"]
