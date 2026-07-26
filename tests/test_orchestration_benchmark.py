"""Behavioral protocol tests for deterministic paired benchmark evidence."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest

from runtime.orchestration_benchmark import (
    BenchmarkValidationError,
    analyze_manifest,
    validate_manifest,
)


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "schemas"
    / "orchestration-benchmark.schema.json"
)
_NODES = ["plan", "implement", "review", "settle"]


def _quota(value: float | None = 75.0) -> dict:
    return {
        "availability": "observed" if value is not None else "unavailable",
        "source": "host_quota_ui",
        "unit": "percent_remaining" if value is not None else "unknown",
        "value": value,
    }


def _arm(host: str, *, turns: int, root_input: int, native_total: int) -> dict:
    return {
        "posture_key": host,
        "logical_dispatch_ids": list(_NODES),
        "logical_completions_verified": True,
        "metrics": {
            "supervisor_turns": turns,
            "root_input_tokens": root_input,
            "logical_nodes": len(_NODES),
        },
        "native_usage": {
            "known_subtotal": native_total,
            "unknown_segment_count": 0,
            "unknown_reasons": [],
            "completeness": "complete",
            "quality_flags": [],
            "quota_observation": _quota(),
        },
        "ceiling_observations": {
            "supervisor_turns": {
                "observed": turns,
                "enforced": True,
                "enforcer_id": "durable_boundary_v1",
            },
            "root_input_tokens": {
                "observed": root_input,
                "enforced": True,
                "enforcer_id": "durable_boundary_v1",
            },
            "native_total_tokens": {
                "observed": native_total,
                "enforced": True,
                "enforcer_id": "durable_boundary_v1",
            },
        },
    }


def _manifest(pair_count: int = 5) -> dict:
    pair_orders = []
    trials = []
    for index in range(pair_count):
        pair_id = f"pair-{index + 1}"
        order = "claude_first" if index % 2 == 0 else "codex_first"
        pair_orders.append({"pair_id": pair_id, "order": order})
        trials.append(
            {
                "pair_id": pair_id,
                "status": "complete",
                "order": order,
                "graph_id": "graph-v1",
                "schedule_id": "schedule-v1",
                "cache_state": "cold",
                "baseline_provenance": (
                    {
                        "kind": "safe_capture",
                        "evidence_id": f"baseline-{index + 1}",
                        "capture_fingerprint": f"{index + 1:016x}",
                    }
                    if index % 2 == 0
                    else {
                        "kind": "externally_hard_capped",
                        "evidence_id": f"baseline-{index + 1}",
                        "enforcer_id": "durable_boundary_v1",
                    }
                ),
                "claude": _arm("claude", turns=100, root_input=1_000, native_total=2_000),
                "codex": _arm("codex", turns=25, root_input=2_000, native_total=2_500),
            }
        )
    return {
        "schema_version": 1,
        "protocol_id": "paired-orchestration-v1",
        "postures": {
            "claude": {
                "host": "claude",
                "surface": "claude_cli",
                "runtime_version": "1.2.3",
                "build_fingerprint": "a" * 16,
                "command": "z-execute",
                "posture": "safe_baseline",
                "equivalence_key": "e" * 16,
            },
            "codex": {
                "host": "codex",
                "surface": "codex_cli",
                "runtime_version": "4.5.6",
                "build_fingerprint": "b" * 16,
                "command": "z-execute",
                "posture": "native_bounded",
                "equivalence_key": "e" * 16,
            },
        },
        "logical_graph": {
            "graph_id": "graph-v1",
            "logical_node_ids": list(_NODES),
            "edges": [
                {"from": "plan", "to": "implement"},
                {"from": "implement", "to": "review"},
                {"from": "review", "to": "settle"},
            ],
        },
        "terminal_schedule": {
            "schedule_id": "schedule-v1",
            "terminal_node_ids": list(_NODES),
        },
        "counterbalancing": {
            "method": "alternating_ab_ba",
            "pair_orders": pair_orders,
        },
        "cache_control": {"state": "cold", "preparation_id": "cold-cache-v1"},
        "rules": {
            "inclusion": "completed_pairs_only",
            "failed_trial": "exclude_pair_and_fail_evidence_gate",
            "weighting": "pooled_logical_nodes",
            "confidence": "paired_normal_95",
        },
        "hard_ceilings": {
            "supervisor_turns": 100,
            "root_input_tokens": 2_000,
            "native_total_tokens": 3_000,
        },
        "native_usage_rules": {
            "required_completeness": "complete",
            "maximum_unknown_segments": 0,
            "allowed_quality_flags": [],
            "quota_interpretation": "observation_only_no_billing_formula",
        },
        "trials": trials,
    }


def test_schema_is_valid_draft7_and_manifest_is_machine_validated() -> None:
    """Criterion #11: the frozen manifest is a real closed machine contract."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft7Validator.check_schema(schema)
    jsonschema.validate(instance=_manifest(), schema=schema)
    invalid = _manifest()
    invalid["unfrozen_extension"] = True
    with pytest.raises(BenchmarkValidationError, match="schema validation failed"):
        validate_manifest(invalid)


def test_exact_thresholds_pass_and_report_every_metric() -> None:
    """Criteria #10/#11: inclusive 75%, 60%, 1.5x, and 2x gates are explicit."""
    result = analyze_manifest(_manifest())
    assert result["passed"] is True
    assert result["admissible_pairs"] == 5
    assert result["aggregate"] == {
        "weighting": "pooled_logical_nodes",
        "logical_nodes": 20,
        "supervisor_turn_reduction": 0.75,
        "turns_per_logical_node": {
            "claude": 25.0,
            "codex": 6.25,
            "codex_to_claude_ratio": 0.25,
        },
        "root_input_per_logical_node": {
            "claude": 250.0,
            "codex": 500.0,
            "codex_to_claude_ratio": 2.0,
        },
    }
    assert len(result["per_trial"]) == 5
    assert all(entry["supervisor_turn_reduction"] == 0.75 for entry in result["per_trial"])
    assert all(all(entry["thresholds"].values()) for entry in result["per_trial"])
    assert result["per_trial"][0]["native_usage"]["codex"]["completeness"] == "complete"
    assert all(gate["passed"] for gate in result["thresholds"].values())
    distribution = result["distributions"]["supervisor_turn_reduction"]
    assert distribution["values"] == [0.75] * 5
    assert distribution["confidence"] == {
        "method": "paired_normal_95",
        "level": 0.95,
        "mean_lower": 0.75,
        "mean_upper": 0.75,
    }


def test_trial_below_sixty_percent_fails_even_if_aggregate_passes() -> None:
    """Criterion #10: pooled performance cannot hide one bad trial."""
    manifest = _manifest()
    weak = manifest["trials"][0]["codex"]
    weak["metrics"]["supervisor_turns"] = 41
    weak["ceiling_observations"]["supervisor_turns"]["observed"] = 41
    for trial in manifest["trials"][1:]:
        arm = trial["codex"]
        arm["metrics"]["supervisor_turns"] = 1
        arm["ceiling_observations"]["supervisor_turns"]["observed"] = 1
    result = analyze_manifest(manifest)
    assert result["aggregate"]["supervisor_turn_reduction"] > 0.75
    gate = result["thresholds"]["every_trial_supervisor_turn_reduction_at_least_60_percent"]
    assert gate == {"value": 0.59, "threshold": 0.6, "passed": False}
    assert result["passed"] is False


def test_sixty_percent_and_one_point_five_ratio_boundaries_are_inclusive() -> None:
    manifest = _manifest()
    trial = manifest["trials"][0]
    trial["codex"]["metrics"]["supervisor_turns"] = 40
    trial["codex"]["ceiling_observations"]["supervisor_turns"]["observed"] = 40
    result = analyze_manifest(manifest)
    trial_gate = result["per_trial"][0]["thresholds"]
    assert trial_gate["supervisor_turn_reduction_at_least_60_percent"] is True

    manifest = _manifest()
    manifest["hard_ceilings"]["supervisor_turns"] = 150
    for trial in manifest["trials"]:
        trial["codex"]["metrics"]["supervisor_turns"] = 150
        trial["codex"]["ceiling_observations"]["supervisor_turns"]["observed"] = 150
    result = analyze_manifest(manifest)
    ratio_gate = result["thresholds"]["aggregate_turns_per_logical_node_ratio_at_most_1_5"]
    assert ratio_gate == {"value": 1.5, "threshold": 1.5, "passed": True}


def test_failed_pair_is_reported_excluded_and_fails_evidence_gate() -> None:
    """Criterion #11: a frozen failed-trial rule cannot silently cherry-pick."""
    manifest = _manifest(6)
    failed = manifest["trials"][5]
    manifest["trials"][5] = {
        key: failed[key]
        for key in ("pair_id", "order", "graph_id", "schedule_id", "cache_state")
    }
    manifest["trials"][5].update({"status": "failed", "failure_code": "host_failure"})
    result = analyze_manifest(manifest)
    assert result["admissible_pairs"] == 5
    assert result["excluded_failed_pairs"] == ["pair-6"]
    assert result["hard_gates"]["no_failed_pairs"] is False
    assert result["passed"] is False


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda manifest: manifest["trials"][0]["claude"]["logical_dispatch_ids"].__setitem__(1, "plan"),
            "duplicate logical dispatches",
        ),
        (
            lambda manifest: manifest["trials"][0]["codex"]["native_usage"].update(
                {"completeness": "partial", "unknown_segment_count": 1, "unknown_reasons": ["missing_baseline"]}
            ),
            "incomplete or unknown",
        ),
        (
            lambda manifest: manifest["trials"][0]["codex"]["native_usage"]["quality_flags"].append("replay"),
            "disallowed quality flags",
        ),
        (
            lambda manifest: manifest["postures"]["codex"].update({"equivalence_key": "f" * 16}),
            "not equivalent",
        ),
        (
            lambda manifest: manifest["trials"][0].update({"graph_id": "other-graph"}),
            "different logical graph",
        ),
        (
            lambda manifest: manifest["counterbalancing"]["pair_orders"][1].update({"order": "claude_first"}),
            "alternate AB/BA",
        ),
        (
            lambda manifest: manifest["logical_graph"]["edges"].append({"from": "settle", "to": "plan"}),
            "acyclic",
        ),
    ],
)
def test_adversarial_protocol_evidence_fails_closed(mutate, message: str) -> None:
    manifest = _manifest()
    mutate(manifest)
    with pytest.raises(BenchmarkValidationError, match=message):
        analyze_manifest(manifest)


@pytest.mark.parametrize("metric", ["supervisor_turns", "root_input_tokens", "native_total_tokens"])
def test_any_hard_ceiling_breach_is_rejected(metric: str) -> None:
    """Criterion #10: analysis never turns a ceiling breach into a score."""
    manifest = _manifest()
    limit = manifest["hard_ceilings"][metric]
    arm = manifest["trials"][0]["codex"]
    if metric == "supervisor_turns":
        arm["metrics"]["supervisor_turns"] = limit + 1
    elif metric == "root_input_tokens":
        arm["metrics"]["root_input_tokens"] = limit + 1
    else:
        arm["native_usage"]["known_subtotal"] = limit + 1
    arm["ceiling_observations"][metric]["observed"] = limit + 1
    with pytest.raises(BenchmarkValidationError, match=f"breached hard ceiling {metric}"):
        analyze_manifest(manifest)


def test_ceiling_observation_cannot_disagree_with_measured_metric() -> None:
    manifest = _manifest()
    manifest["trials"][0]["codex"]["ceiling_observations"]["supervisor_turns"]["observed"] = 24
    with pytest.raises(BenchmarkValidationError, match="ceiling observation conflicts"):
        analyze_manifest(manifest)


def test_unsafe_baseline_kind_is_not_representable() -> None:
    """Criterion #10: unsafe historical orchestration cannot enter analysis."""
    manifest = _manifest()
    manifest["trials"][0]["baseline_provenance"]["kind"] = "live_unsafe"
    with pytest.raises(BenchmarkValidationError, match="schema validation failed"):
        analyze_manifest(manifest)


def test_fewer_than_five_completed_pairs_is_valid_but_nonpassing() -> None:
    manifest = _manifest()
    failed = manifest["trials"][4]
    manifest["trials"][4] = {
        key: failed[key]
        for key in ("pair_id", "order", "graph_id", "schedule_id", "cache_state")
    }
    manifest["trials"][4].update({"status": "failed", "failure_code": "host_failure"})
    result = analyze_manifest(manifest)
    assert result["admissible_pairs"] == 4
    assert result["hard_gates"]["minimum_five_complete_pairs"] is False
    assert result["passed"] is False


def test_terminal_verified_ceiling_is_valid_but_fails_hard_gate() -> None:
    manifest = _manifest()
    manifest["trials"][0]["codex"]["ceiling_observations"]["root_input_tokens"][
        "enforced"
    ] = False
    result = analyze_manifest(manifest)
    assert result["hard_gates"]["all_hard_ceilings_enforced"] is False
    assert result["passed"] is False


def test_unverified_logical_completion_is_valid_but_fails_hard_gate() -> None:
    manifest = _manifest()
    manifest["trials"][0]["codex"]["logical_completions_verified"] = False
    result = analyze_manifest(manifest)
    assert result["hard_gates"]["all_logical_completions_verified"] is False
    assert result["passed"] is False


def test_quota_and_metric_unknowns_fail_closed() -> None:
    manifest = _manifest()
    quota = manifest["trials"][0]["claude"]["native_usage"]["quota_observation"]
    quota.update({"availability": "unavailable", "value": 25.0})
    with pytest.raises(BenchmarkValidationError, match="quota availability and value conflict"):
        analyze_manifest(manifest)

    manifest = _manifest()
    manifest["trials"][0]["claude"]["metrics"]["root_input_tokens"] = 0
    manifest["trials"][0]["claude"]["ceiling_observations"]["root_input_tokens"]["observed"] = 0
    with pytest.raises(BenchmarkValidationError, match="undefined zero denominator"):
        analyze_manifest(manifest)


def test_analysis_is_deterministic_and_does_not_mutate_manifest() -> None:
    manifest = _manifest()
    original = deepcopy(manifest)
    first = analyze_manifest(manifest)
    second = analyze_manifest(manifest)
    assert first == second
    assert manifest == original
