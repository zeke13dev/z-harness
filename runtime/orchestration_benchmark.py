"""Deterministic, fail-closed paired orchestration benchmark analysis.

The version-one manifest freezes the equivalent host postures, logical graph,
terminal schedule, counterbalancing, cache state, evidence inclusion, hard
ceilings, native-usage quality, quota observations, and aggregation rules for
INTENT criteria #10 and #11.  This module only validates captured evidence and
computes results; it has deliberately no execution or trial-synthesis surface,
so an unsafe historical posture cannot be launched from benchmark analysis.

Import validates the bundled Draft 7 schema.  Analysis is deterministic and
side-effect free.  Invalid, incomplete, unknown, duplicate, or ceiling-breaching
evidence raises :class:`BenchmarkValidationError` before a result is produced.
"""

from __future__ import annotations

from fractions import Fraction
import json
import math
from pathlib import Path
import statistics
from typing import Any

import jsonschema


SCHEMA_VERSION = 1
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "schemas"
    / "orchestration-benchmark.schema.json"
)
_THRESHOLDS = {
    "aggregate_supervisor_turn_reduction": Fraction(3, 4),
    "minimum_trial_supervisor_turn_reduction": Fraction(3, 5),
    "turns_per_logical_node_ratio": Fraction(3, 2),
    "root_input_per_logical_node_ratio": Fraction(2, 1),
}


class BenchmarkValidationError(ValueError):
    """Raised when benchmark evidence cannot safely support analysis."""


def _load_schema() -> dict[str, Any]:
    """Load and meta-validate the bundled benchmark schema.

    Returns:
        The parsed Draft 7 schema.

    Raises:
        OSError: If the bundled schema cannot be read.
        json.JSONDecodeError: If the bundled schema is not JSON.
        jsonschema.SchemaError: If the bundled schema is not valid Draft 7.
    """
    with _SCHEMA_PATH.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    jsonschema.Draft7Validator.check_schema(schema)
    return schema


_SCHEMA = _load_schema()


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Validate structural and cross-field benchmark invariants.

    Args:
        manifest: Candidate version-one benchmark manifest.

    Returns:
        None.

    Raises:
        BenchmarkValidationError: If any evidence is invalid, unsafe,
            incomplete, unknown, duplicated, or not protocol-equivalent.
    """
    try:
        jsonschema.validate(instance=manifest, schema=_SCHEMA)
    except jsonschema.ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "manifest"
        raise BenchmarkValidationError(f"schema validation failed at {location}: {exc.message}") from exc

    postures = manifest["postures"]
    if postures["claude"]["host"] != "claude" or postures["codex"]["host"] != "codex":
        raise BenchmarkValidationError("posture keys must bind to their named hosts")
    for field in ("command", "equivalence_key"):
        if postures["claude"][field] != postures["codex"][field]:
            raise BenchmarkValidationError(f"host postures are not equivalent: {field} differs")

    graph = manifest["logical_graph"]
    node_ids = tuple(graph["logical_node_ids"])
    node_set = set(node_ids)
    edges = [(edge["from"], edge["to"]) for edge in graph["edges"]]
    if any(source not in node_set or target not in node_set or source == target for source, target in edges):
        raise BenchmarkValidationError("logical graph contains an invalid edge")
    _require_acyclic(node_ids, edges)
    if set(manifest["terminal_schedule"]["terminal_node_ids"]) != node_set:
        raise BenchmarkValidationError("terminal schedule must contain every logical node exactly once")

    trials = manifest["trials"]
    pair_ids = [trial["pair_id"] for trial in trials]
    if len(pair_ids) != len(set(pair_ids)):
        raise BenchmarkValidationError("pair IDs must be unique")
    order_rows = manifest["counterbalancing"]["pair_orders"]
    order_ids = [row["pair_id"] for row in order_rows]
    if len(order_ids) != len(set(order_ids)) or set(order_ids) != set(pair_ids):
        raise BenchmarkValidationError("counterbalancing must map every pair exactly once")
    order_by_pair = {row["pair_id"]: row["order"] for row in order_rows}
    expected_orders = ["claude_first" if index % 2 == 0 else "codex_first" for index in range(len(order_rows))]
    if [row["order"] for row in order_rows] != expected_orders:
        raise BenchmarkValidationError("pair order must alternate AB/BA from claude_first")

    for trial in trials:
        if trial["order"] != order_by_pair[trial["pair_id"]]:
            raise BenchmarkValidationError(f"pair {trial['pair_id']} order conflicts with counterbalancing")
        if trial["graph_id"] != graph["graph_id"]:
            raise BenchmarkValidationError(f"pair {trial['pair_id']} uses a different logical graph")
        if trial["schedule_id"] != manifest["terminal_schedule"]["schedule_id"]:
            raise BenchmarkValidationError(f"pair {trial['pair_id']} uses a different terminal schedule")
        if trial["cache_state"] != manifest["cache_control"]["state"]:
            raise BenchmarkValidationError(f"pair {trial['pair_id']} uses a different cache state")
        if trial["status"] == "failed":
            continue
        for host in ("claude", "codex"):
            _validate_arm(manifest, trial["pair_id"], host, trial[host], node_set)


def _require_acyclic(nodes: tuple[str, ...], edges: list[tuple[str, str]]) -> None:
    """Reject cycles in the frozen logical graph.

    Args:
        nodes: Frozen logical node identities.
        edges: Directed graph edges.

    Raises:
        BenchmarkValidationError: If the graph contains a cycle.
    """
    incoming = {node: 0 for node in nodes}
    outgoing = {node: [] for node in nodes}
    for source, target in edges:
        incoming[target] += 1
        outgoing[source].append(target)
    ready = [node for node in nodes if incoming[node] == 0]
    visited = 0
    while ready:
        source = ready.pop()
        visited += 1
        for target in outgoing[source]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if visited != len(nodes):
        raise BenchmarkValidationError("logical graph must be acyclic")


def _validate_arm(
    manifest: dict[str, Any],
    pair_id: str,
    host: str,
    arm: dict[str, Any],
    node_set: set[str],
) -> None:
    """Validate one completed host arm against frozen protocol controls.

    Args:
        manifest: Complete benchmark manifest.
        pair_id: Pair identity used in diagnostics.
        host: Expected posture key.
        arm: Completed host-arm evidence.
        node_set: Frozen logical graph node identities.

    Raises:
        BenchmarkValidationError: If the arm is not admissible evidence.
    """
    if arm["posture_key"] != host:
        raise BenchmarkValidationError(f"pair {pair_id} {host} arm uses the wrong posture")
    dispatches = arm["logical_dispatch_ids"]
    if len(dispatches) != len(set(dispatches)):
        raise BenchmarkValidationError(f"pair {pair_id} {host} contains duplicate logical dispatches")
    if set(dispatches) != node_set:
        raise BenchmarkValidationError(f"pair {pair_id} {host} dispatch set differs from the logical graph")
    metrics = arm["metrics"]
    if metrics["logical_nodes"] != len(node_set):
        raise BenchmarkValidationError(f"pair {pair_id} {host} logical-node count is inconsistent")
    if metrics["supervisor_turns"] == 0 or metrics["root_input_tokens"] == 0:
        raise BenchmarkValidationError(f"pair {pair_id} {host} has an undefined zero denominator metric")

    usage = arm["native_usage"]
    rules = manifest["native_usage_rules"]
    if (
        usage["completeness"] != rules["required_completeness"]
        or usage["unknown_segment_count"] != rules["maximum_unknown_segments"]
        or usage["unknown_reasons"]
    ):
        raise BenchmarkValidationError(f"pair {pair_id} {host} native usage is incomplete or unknown")
    unexpected_flags = set(usage["quality_flags"]) - set(rules["allowed_quality_flags"])
    if unexpected_flags:
        raise BenchmarkValidationError(
            f"pair {pair_id} {host} has disallowed quality flags: {sorted(unexpected_flags)}"
        )
    quota = usage["quota_observation"]
    if (quota["availability"] == "observed") != (quota["value"] is not None):
        raise BenchmarkValidationError(f"pair {pair_id} {host} quota availability and value conflict")

    observed_values = {
        "supervisor_turns": metrics["supervisor_turns"],
        "root_input_tokens": metrics["root_input_tokens"],
        "native_total_tokens": usage["known_subtotal"],
    }
    for metric, observed in observed_values.items():
        ceiling = arm["ceiling_observations"][metric]
        if ceiling["observed"] != observed:
            raise BenchmarkValidationError(
                f"pair {pair_id} {host} {metric} ceiling observation conflicts with evidence"
            )
        if observed > manifest["hard_ceilings"][metric]:
            raise BenchmarkValidationError(f"pair {pair_id} {host} breached hard ceiling {metric}")


def _as_float(value: Fraction) -> float:
    return float(value.numerator / value.denominator)


def _distribution(values: list[Fraction]) -> dict[str, Any]:
    """Return deterministic distribution and normal 95% mean confidence output."""
    floats = [_as_float(value) for value in values]
    mean = statistics.fmean(floats)
    sample_stdev = statistics.stdev(floats) if len(floats) > 1 else 0.0
    margin = 1.96 * sample_stdev / math.sqrt(len(floats))
    return {
        "values": floats,
        "minimum": min(floats),
        "median": statistics.median(floats),
        "mean": mean,
        "maximum": max(floats),
        "sample_stdev": sample_stdev,
        "confidence": {
            "method": "paired_normal_95",
            "level": 0.95,
            "mean_lower": mean - margin,
            "mean_upper": mean + margin,
        },
    }


def analyze_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate and deterministically analyze a frozen paired manifest.

    Args:
        manifest: Captured paired benchmark evidence.

    Returns:
        Per-trial and pooled metrics, distributions, confidence intervals, four
        explicit threshold results, hard-gate status, and overall pass/fail.

    Raises:
        BenchmarkValidationError: If no safe analysis can be produced.
    """
    validate_manifest(manifest)
    completed = [trial for trial in manifest["trials"] if trial["status"] == "complete"]
    failed = [trial for trial in manifest["trials"] if trial["status"] == "failed"]
    reductions: list[Fraction] = []
    turns_ratios: list[Fraction] = []
    root_input_ratios: list[Fraction] = []
    per_trial: list[dict[str, Any]] = []
    claude_turns = codex_turns = claude_input = codex_input = logical_nodes = 0

    for trial in completed:
        claude = trial["claude"]["metrics"]
        codex = trial["codex"]["metrics"]
        reduction = Fraction(claude["supervisor_turns"] - codex["supervisor_turns"], claude["supervisor_turns"])
        turns_ratio = Fraction(codex["supervisor_turns"], claude["supervisor_turns"])
        root_ratio = Fraction(codex["root_input_tokens"], claude["root_input_tokens"])
        reductions.append(reduction)
        turns_ratios.append(turns_ratio)
        root_input_ratios.append(root_ratio)
        nodes = claude["logical_nodes"]
        claude_turns += claude["supervisor_turns"]
        codex_turns += codex["supervisor_turns"]
        claude_input += claude["root_input_tokens"]
        codex_input += codex["root_input_tokens"]
        logical_nodes += nodes
        per_trial.append(
            {
                "pair_id": trial["pair_id"],
                "order": trial["order"],
                "supervisor_turn_reduction": _as_float(reduction),
                "turns_per_logical_node": {
                    "claude": claude["supervisor_turns"] / nodes,
                    "codex": codex["supervisor_turns"] / nodes,
                    "codex_to_claude_ratio": _as_float(turns_ratio),
                },
                "root_input_per_logical_node": {
                    "claude": claude["root_input_tokens"] / nodes,
                    "codex": codex["root_input_tokens"] / nodes,
                    "codex_to_claude_ratio": _as_float(root_ratio),
                },
                "baseline_provenance": dict(trial["baseline_provenance"]),
                "native_usage": {
                    "claude": dict(trial["claude"]["native_usage"]),
                    "codex": dict(trial["codex"]["native_usage"]),
                },
                "thresholds": {
                    "supervisor_turn_reduction_at_least_60_percent": reduction
                    >= _THRESHOLDS["minimum_trial_supervisor_turn_reduction"],
                    "turns_per_logical_node_ratio_at_most_1_5": turns_ratio
                    <= _THRESHOLDS["turns_per_logical_node_ratio"],
                    "root_input_per_logical_node_ratio_at_most_2": root_ratio
                    <= _THRESHOLDS["root_input_per_logical_node_ratio"],
                },
            }
        )

    has_completed = bool(completed)
    aggregate_reduction = (
        Fraction(claude_turns - codex_turns, claude_turns) if has_completed else None
    )
    aggregate_turn_ratio = Fraction(codex_turns, claude_turns) if has_completed else None
    aggregate_input_ratio = Fraction(codex_input, claude_input) if has_completed else None
    threshold_results = {
        "aggregate_supervisor_turn_reduction_at_least_75_percent": {
            "value": _as_float(aggregate_reduction) if aggregate_reduction is not None else None,
            "threshold": 0.75,
            "passed": aggregate_reduction is not None
            and aggregate_reduction >= _THRESHOLDS["aggregate_supervisor_turn_reduction"],
        },
        "every_trial_supervisor_turn_reduction_at_least_60_percent": {
            "value": _as_float(min(reductions)) if reductions else None,
            "threshold": 0.60,
            "passed": bool(reductions)
            and min(reductions) >= _THRESHOLDS["minimum_trial_supervisor_turn_reduction"],
        },
        "aggregate_turns_per_logical_node_ratio_at_most_1_5": {
            "value": _as_float(aggregate_turn_ratio) if aggregate_turn_ratio is not None else None,
            "threshold": 1.5,
            "passed": aggregate_turn_ratio is not None
            and aggregate_turn_ratio <= _THRESHOLDS["turns_per_logical_node_ratio"],
        },
        "aggregate_root_input_per_logical_node_ratio_at_most_2": {
            "value": _as_float(aggregate_input_ratio) if aggregate_input_ratio is not None else None,
            "threshold": 2.0,
            "passed": aggregate_input_ratio is not None
            and aggregate_input_ratio <= _THRESHOLDS["root_input_per_logical_node_ratio"],
        },
    }
    all_ceilings_enforced = all(
        observation["enforced"]
        for trial in completed
        for host in ("claude", "codex")
        for observation in trial[host]["ceiling_observations"].values()
    )
    all_completions_verified = all(
        trial[host]["logical_completions_verified"]
        for trial in completed
        for host in ("claude", "codex")
    )
    hard_gates = {
        "minimum_five_complete_pairs": len(completed) >= 5,
        "zero_duplicate_logical_dispatches": True,
        "all_logical_completions_verified": bool(completed) and all_completions_verified,
        "all_hard_ceilings_enforced": bool(completed) and all_ceilings_enforced,
        "native_usage_complete": True,
        "no_failed_pairs": not failed,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": manifest["protocol_id"],
        "admissible_pairs": len(completed),
        "excluded_failed_pairs": [trial["pair_id"] for trial in failed],
        "per_trial": per_trial,
        "aggregate": {
            "weighting": "pooled_logical_nodes",
            "logical_nodes": logical_nodes,
            "supervisor_turn_reduction": (
                _as_float(aggregate_reduction) if aggregate_reduction is not None else None
            ),
            "turns_per_logical_node": {
                "claude": claude_turns / logical_nodes if logical_nodes else None,
                "codex": codex_turns / logical_nodes if logical_nodes else None,
                "codex_to_claude_ratio": (
                    _as_float(aggregate_turn_ratio) if aggregate_turn_ratio is not None else None
                ),
            },
            "root_input_per_logical_node": {
                "claude": claude_input / logical_nodes if logical_nodes else None,
                "codex": codex_input / logical_nodes if logical_nodes else None,
                "codex_to_claude_ratio": (
                    _as_float(aggregate_input_ratio) if aggregate_input_ratio is not None else None
                ),
            },
        },
        "distributions": {
            "supervisor_turn_reduction": _distribution(reductions) if reductions else None,
            "turns_per_logical_node_ratio": _distribution(turns_ratios) if turns_ratios else None,
            "root_input_per_logical_node_ratio": (
                _distribution(root_input_ratios) if root_input_ratios else None
            ),
        },
        "thresholds": threshold_results,
        "hard_gates": hard_gates,
        "passed": all(hard_gates.values()) and all(result["passed"] for result in threshold_results.values()),
    }
