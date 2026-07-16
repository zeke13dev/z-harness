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
    assert payload["sessions"] == [{
        "idle_precision": "unknown",
        "inferred_idle_ms": None,
        "quality_flags": [],
        "session_hash": telemetry.session_hash("flat-v1-session"),
        "source": "both",
        "token_count": 15,
        "tool_wait_ms": 250,
        "tool_wait_precision": "exact",
        "ttft_ms": 200,
        "ttft_precision": "exact",
        "turn_count": 1,
    }]


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
    assert payload["sessions"] == [{
        "idle_precision": "unknown",
        "inferred_idle_ms": None,
        "quality_flags": [],
        "session_hash": telemetry.session_hash("current-session"),
        "source": "both",
        "token_count": 15,
        "tool_wait_ms": 400,
        "tool_wait_precision": "exact",
        "ttft_ms": 200,
        "ttft_precision": "exact",
        "turn_count": 1,
    }]


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
    assert sessions[telemetry.session_hash("parent")]["token_count"] == 15
    assert sessions[telemetry.session_hash("child")]["token_count"] == 4
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
    assert child["token_count"] == 7  # never subtract the parent baseline
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
    assert session["token_count"] == 12
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

    assert session["token_count"] == 15
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
        "inferred_idle_ms", "idle_precision", "quality_flags",
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
    assert session == {
        "idle_precision": "inferred",
        "inferred_idle_ms": 1000,
        "quality_flags": [
            "malformed_row",
            "missing_first_token",
            "truncated_row",
            "truncation",
            "unknown_schema",
        ],
        "session_hash": telemetry.session_hash("cli"),
        "source": "both",
        "token_count": 15,
        "tool_wait_ms": 250,
        "tool_wait_precision": "exact",
        "ttft_ms": 200,
        "ttft_precision": "exact",
        "turn_count": 2,
    }
    assert payload["quality_flags"] == [
        "malformed_row",
        "truncated_row",
        "truncation",
        "unknown_schema",
    ]


@pytest.mark.parametrize(
    ("child_usage", "expected_tokens", "expected_flags"),
    [
        (
            [
                {"total_tokens": 10},
                {"total_tokens": 3},
                {"total_tokens": 5},
            ],
            12,
            {"counter_reset"},
        ),
        (
            [
                {"total_tokens": 10},
                {"total_tokens": -1},
                {"total_tokens": 20},
                {"total_tokens": 25},
            ],
            15,
            {"negative_token_counter", "counter_segment_baseline"},
        ),
        (
            [
                {"total_tokens": 10},
                {},
                {"total_tokens": 20},
                {"total_tokens": 25},
            ],
            15,
            {"unknown_token_counter", "counter_segment_baseline"},
        ),
        (
            [
                {"total_tokens": 10},
                {"total_tokens": "not-an-integer"},
                {"total_tokens": 20},
                {"total_tokens": 25},
            ],
            15,
            {"unknown_token_counter", "counter_segment_baseline"},
        ),
    ],
    ids=["reset", "negative", "missing", "non-integer"],
)
def test_standalone_cli_keeps_fork_counters_isolated_across_counter_transitions(
    tmp_path: Path,
    child_usage: list[dict[str, object]],
    expected_tokens: int,
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
    assert child["token_count"] == expected_tokens
    assert set(child["quality_flags"]) == expected_flags
