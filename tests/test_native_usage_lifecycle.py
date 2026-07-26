"""Cross-module lifecycle conformance tests for usage and admission accounting.

This integration test intentionally spans ``runtime.telemetry.native_usage``
and ``runtime.orchestration_ledger``: INTENT criterion #7 requires the same
privacy-safe lifecycle vocabulary to prove both accounting contracts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from runtime.orchestration_ledger import (
    AdmissionCeilingExceeded,
    DuplicateLiveWork,
    OrchestrationLedger,
    Reservation,
)
from runtime.telemetry.native_usage import (
    CONTRACT_VERSION,
    SOURCE_SEMANTICS_VERSION,
    reduce_usage_observations,
    validate_observation,
)


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "native_usage_lifecycle.json"
_ERROR_TYPES = {
    "AdmissionCeilingExceeded": AdmissionCeilingExceeded,
    "DuplicateLiveWork": DuplicateLiveWork,
}
_REQUIRED_LIFECYCLES = frozenset(
    {
        "normal_completion",
        "rejection_recovery",
        "halt_resume",
        "nested_forks",
        "counter_reset",
        "replay",
        "repeated_equal",
        "out_of_order",
        "missing_baseline",
        "ambiguous_baseline",
        "crash_resume",
        "n_plus_one_rejection",
        "non_deniable_settlement",
    }
)


def _fixture() -> dict[str, Any]:
    """Load the checked-in conformance suite, hard-failing on invalid JSON."""
    with _FIXTURE_PATH.open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _canonical_observation(item: Mapping[str, Any]) -> dict[str, Any]:
    """Expand one compact fixture frame into the canonical allowlisted record."""
    total = item["total_tokens"]
    return {
        "schema_version": CONTRACT_VERSION,
        "observation_id": item["id"],
        "host": "codex",
        "surface": "codex_app",
        "source": {
            "kind": "archive",
            "identity_hash": "aaaaaaaaaaaaaaaa",
            "semantics_version": SOURCE_SEMANTICS_VERSION,
        },
        "lineage": {
            "session_hash": item["session_hash"],
            "root_session_hash": item["root_hash"],
            "parent_session_hash": item["parent_hash"],
        },
        "segment": {
            "id": item["segment_id"],
            "baseline": item["baseline"],
            "counter_scope": item["counter_scope"],
        },
        "observed_at_ms": item["observed_at_ms"],
        "clock": {"kind": "wall", "source": "host", "skew_ms": None},
        "raw": {
            "input_tokens": total,
            "cached_input_tokens": 0 if total is not None else None,
            "output_tokens": 0 if total is not None else None,
            "reasoning_output_tokens": 0 if total is not None else None,
            "total_tokens": total,
        },
        "derived": {
            "uncached_input_tokens": total,
            "additive_total_tokens": total,
            "equation_version": SOURCE_SEMANTICS_VERSION,
        },
        "quality_flags": item["quality_flags"],
    }


def _reserve(
    ledger: OrchestrationLedger,
    operation: Mapping[str, Any],
    reservations: dict[str, Reservation],
) -> Reservation:
    """Execute one fixture reservation against the public ledger boundary."""
    predecessor_alias = operation.get("reentry_alias")
    predecessor = reservations.get(predecessor_alias) if predecessor_alias else None
    result = ledger.reserve(
        run_id="fixture-run",
        logical_work_id=operation["logical_work_id"],
        reservation_id=operation["reservation_id"],
        transition_id=operation["transition_id"],
        writer_id=operation["writer_id"],
        reentry_of=predecessor.reservation_id if predecessor else None,
    )
    reservations[operation["alias"]] = result
    return result


def _execute_operation(
    ledger: OrchestrationLedger,
    operation: Mapping[str, Any],
    reservations: dict[str, Reservation],
) -> None:
    """Apply one declarative lifecycle operation or its expected rejection."""
    action = operation["op"]
    if action == "expect_error":
        error_type = _ERROR_TYPES[operation["error"]]
        with pytest.raises(error_type):
            _execute_operation(ledger, operation["operation"], reservations)
        return
    if action == "reserve":
        _reserve(ledger, operation, reservations)
        return

    current = reservations[operation["alias"]]
    if action == "advance":
        reservations[operation["alias"]] = ledger.advance(
            reservation_id=current.reservation_id,
            transition_id=operation["transition_id"],
            writer_id=current.writer_id,
            writer_fence=current.writer_fence,
            to_state=operation["to_state"],
        )
        return
    if action == "transfer":
        reservations[operation["alias"]] = ledger.transfer_writer(
            reservation_id=current.reservation_id,
            transition_id=operation["transition_id"],
            writer_id=current.writer_id,
            writer_fence=current.writer_fence,
            new_writer_id=operation["new_writer_id"],
        )
        return
    raise AssertionError(f"unsupported fixture operation: {action}")


def _assert_no_forbidden_keys(value: Any, forbidden: frozenset[str]) -> None:
    """Recursively prove fixture scenario records contain no content fields."""
    if isinstance(value, dict):
        assert forbidden.isdisjoint(value)
        for child in value.values():
            _assert_no_forbidden_keys(child, forbidden)
    elif isinstance(value, list):
        for child in value:
            _assert_no_forbidden_keys(child, forbidden)


def test_fixture_covers_every_required_lifecycle_without_content_fields() -> None:
    """Criterion #7: one reusable suite covers every named lifecycle safely."""
    fixture = _fixture()
    assert fixture["schema_version"] == CONTRACT_VERSION
    cases = fixture["usage_cases"] + fixture["ledger_cases"]
    covered = {lifecycle for case in cases for lifecycle in case["lifecycle"]}
    assert _REQUIRED_LIFECYCLES <= covered

    privacy = fixture["privacy_contract"]
    forbidden = frozenset(privacy["forbidden_keys"])
    _assert_no_forbidden_keys(cases, forbidden)
    assert privacy["forbidden_value"] not in json.dumps(cases, sort_keys=True)

    for case in fixture["usage_cases"]:
        for compact in case["observations"]:
            canonical = _canonical_observation(compact)
            assert validate_observation(canonical) == canonical


@pytest.mark.parametrize(
    "case",
    _fixture()["usage_cases"],
    ids=lambda case: case["id"],
)
def test_usage_lifecycle_preserves_unique_marginals_and_unknowns(
    case: Mapping[str, Any],
) -> None:
    """Criterion #7: replay never double-counts and uncertainty stays visible."""
    observations = [_canonical_observation(item) for item in case["observations"]]
    result = reduce_usage_observations(observations)
    expected = case["expected"]

    assert result["known_subtotal_tokens"] == expected["known_subtotal_tokens"]
    assert result["unknown_segment_count"] == expected["unknown_segment_count"]
    assert result["unknown_reasons"] == expected["unknown_reasons"]
    assert result["completeness"] == expected["completeness"]
    assert [
        delta["marginal_tokens"] for delta in result["marginal_deltas"]
    ] == expected["marginal_tokens"]
    assert result["quality_flags"] == expected["quality_flags"]


@pytest.mark.parametrize(
    "case",
    _fixture()["ledger_cases"],
    ids=lambda case: case["id"],
)
def test_ledger_lifecycle_preserves_logical_identity_and_settlement(
    tmp_path: Path,
    case: Mapping[str, Any],
) -> None:
    """Criterion #7: rejection, recovery, replay, and restart settle durably."""
    database = tmp_path / f"{case['id']}.sqlite3"
    ledger = OrchestrationLedger(database)
    ledger.configure_run("fixture-run", case["ceiling"])
    reservations: dict[str, Reservation] = {}

    for operation in case["operations"]:
        if operation["op"] == "reopen":
            ledger = OrchestrationLedger(database)
        else:
            _execute_operation(ledger, operation, reservations)

    expected = case["expected"]
    assert ledger.run_usage("fixture-run") == (
        expected["admissions_used"],
        case["ceiling"],
    )
    assert len({item.logical_work_id for item in reservations.values()}) == expected[
        "logical_work_count"
    ]
    assert len({item.reservation_id for item in reservations.values()}) == expected[
        "admissions_used"
    ]
    for alias in expected["settled_aliases"]:
        durable = OrchestrationLedger(database).get_reservation(
            reservations[alias].reservation_id
        )
        assert durable.state == "settled"
