#!/usr/bin/env python3
"""
Unit tests for scope-probe-calibrate.py.

Creates synthetic archive fixtures in a tmp directory and validates:
  - classify_ground_truth returns correct label for LIGHT/MEDIUM/HEAVY cases.
  - build_confusion_matrix correctly counts match/mismatch cells.
  - Tripwire detection fires correctly on an "all MEDIUM" ground-truth set.

Exit codes:
  0 — all assertions passed
  1 — one or more assertions failed
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
# The production script uses hyphens in its filename, which prevents a plain
# `import` statement. We load it via importlib instead.

import importlib.util as _ilu

_SCRIPTS_DIR = Path(__file__).parent.resolve()
_SPEC = _ilu.spec_from_file_location(
    "scope_probe_calibrate",
    str(_SCRIPTS_DIR / "scope-probe-calibrate.py"),
)
_MOD = _ilu.module_from_spec(_SPEC)  # type: ignore[arg-type]
_SPEC.loader.exec_module(_MOD)  # type: ignore[union-attr]

classify_ground_truth = _MOD.classify_ground_truth
build_confusion_matrix = _MOD.build_confusion_matrix
compute_percentages = _MOD.compute_percentages
print_tripwire_report = _MOD.print_tripwire_report
load_events = _MOD.load_events
discover_runs = _MOD.discover_runs
majority_vote = _MOD.majority_vote

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAILURES: list[str] = []


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


def _write_fixture(run_dir: Path, manifest: dict, events: list[dict]) -> None:
    """Write manifest.json and events.jsonl into run_dir."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    lines = "".join(json.dumps(e) + "\n" for e in events)
    (run_dir / "events.jsonl").write_text(lines, encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixture definitions
# ---------------------------------------------------------------------------

LIGHT_MANIFEST = {
    "tasks_total": 3,
    "tasks_complexity": {"low": 2, "medium": 1, "high": 0},
}
LIGHT_EVENTS: list[dict] = [
    {"type": "run_start", "task": "small refactor"},
    {"type": "task_complete", "id": "T001"},
]
# Expected: LIGHT (tasks_total <= 5, high == 0, no plan_route_decision)

MEDIUM_MANIFEST = {
    "tasks_total": 8,
    "tasks_complexity": {"low": 3, "medium": 5, "high": 0},
}
MEDIUM_EVENTS: list[dict] = [
    {"type": "run_start", "task": "medium migration"},
    {"type": "task_complete", "id": "T001"},
]
# Expected: MEDIUM (tasks_total > 5, not >= 16, no escalation)

HEAVY_MANIFEST = {
    "tasks_total": 5,
    "tasks_complexity": {"low": 3, "medium": 2, "high": 0},
}
HEAVY_EVENTS: list[dict] = [
    {"type": "run_start", "task": "big refactor with escalation"},
    {"type": "escalation_mid_flight", "ts": "2026-05-27T18:00:00Z", "payload": {}},
    {"type": "task_complete", "id": "T001"},
]
# Expected: HEAVY (has escalation_* event — overrides all LIGHT-compatible signals)


# ---------------------------------------------------------------------------
# Test: classify_ground_truth
# ---------------------------------------------------------------------------

def test_classify_ground_truth() -> None:
    print("\n--- test_classify_ground_truth ---")

    result = classify_ground_truth(LIGHT_MANIFEST, LIGHT_EVENTS)
    _assert(result == "LIGHT", f"LIGHT fixture → expected LIGHT, got {result}")

    result = classify_ground_truth(MEDIUM_MANIFEST, MEDIUM_EVENTS)
    _assert(result == "MEDIUM", f"MEDIUM fixture → expected MEDIUM, got {result}")

    result = classify_ground_truth(HEAVY_MANIFEST, HEAVY_EVENTS)
    _assert(result == "HEAVY", f"HEAVY fixture (escalation) → expected HEAVY, got {result}")

    # Edge: tasks_total >= 16 → HEAVY even without escalation
    big_manifest = {"tasks_total": 16, "tasks_complexity": {"low": 10, "medium": 6, "high": 0}}
    result = classify_ground_truth(big_manifest, [])
    _assert(result == "HEAVY", f"tasks_total=16 → expected HEAVY, got {result}")

    # Edge: tasks_total <= 5 but high > 0 → should be MEDIUM, not LIGHT
    high_complexity_manifest = {
        "tasks_total": 4,
        "tasks_complexity": {"low": 2, "medium": 1, "high": 1},
    }
    result = classify_ground_truth(high_complexity_manifest, [])
    _assert(
        result == "MEDIUM",
        f"high complexity count > 0 prevents LIGHT → expected MEDIUM, got {result}",
    )

    # Edge: tasks_total <= 5, high == 0, but has plan_route_decision → MEDIUM
    route_events: list[dict] = [{"type": "plan_route_decision"}]
    result = classify_ground_truth(LIGHT_MANIFEST, route_events)
    _assert(
        result == "MEDIUM",
        f"plan_route_decision prevents LIGHT → expected MEDIUM, got {result}",
    )

    # Edge: escalation event via 'kind' field also detected
    kind_events: list[dict] = [{"kind": "escalation_architect_bail"}]
    result = classify_ground_truth({"tasks_total": 3, "tasks_complexity": {"high": 0}}, kind_events)
    _assert(
        result == "HEAVY",
        f"escalation via 'kind' field → expected HEAVY, got {result}",
    )


# ---------------------------------------------------------------------------
# Test: build_confusion_matrix
# ---------------------------------------------------------------------------

def test_confusion_matrix() -> None:
    print("\n--- test_confusion_matrix ---")

    run_results = [
        {"classified_mode": "LIGHT",  "ground_truth_mode": "LIGHT",  "match": True},
        {"classified_mode": "MEDIUM", "ground_truth_mode": "MEDIUM", "match": True},
        {"classified_mode": "HEAVY",  "ground_truth_mode": "HEAVY",  "match": True},
        # One mismatch: probe said MEDIUM, truth was LIGHT
        {"classified_mode": "MEDIUM", "ground_truth_mode": "LIGHT",  "match": False},
    ]

    matrix = build_confusion_matrix(run_results)

    # Diagonal matches
    _assert(matrix["LIGHT"]["LIGHT"] == 1, "matrix[LIGHT][LIGHT] == 1")
    _assert(matrix["MEDIUM"]["MEDIUM"] == 1, "matrix[MEDIUM][MEDIUM] == 1")
    _assert(matrix["HEAVY"]["HEAVY"] == 1, "matrix[HEAVY][HEAVY] == 1")

    # Off-diagonal mismatch: classified MEDIUM, truth LIGHT
    _assert(matrix["MEDIUM"]["LIGHT"] == 1, "matrix[MEDIUM][LIGHT] == 1 (mismatch counted)")

    # All other off-diagonal cells are zero
    _assert(matrix["LIGHT"]["MEDIUM"] == 0, "matrix[LIGHT][MEDIUM] == 0")
    _assert(matrix["LIGHT"]["HEAVY"] == 0, "matrix[LIGHT][HEAVY] == 0")
    _assert(matrix["HEAVY"]["LIGHT"] == 0, "matrix[HEAVY][LIGHT] == 0")
    _assert(matrix["HEAVY"]["MEDIUM"] == 0, "matrix[HEAVY][MEDIUM] == 0")
    _assert(matrix["MEDIUM"]["HEAVY"] == 0, "matrix[MEDIUM][HEAVY] == 0")


# ---------------------------------------------------------------------------
# Test: tripwire fires on "all MEDIUM" ground truth
# ---------------------------------------------------------------------------

def test_tripwire_all_medium() -> None:
    print("\n--- test_tripwire_all_medium ---")

    # 10 runs all classified and ground-truthed as MEDIUM → pct_medium = 100%
    run_results = [
        {
            "classified_mode": "MEDIUM",
            "ground_truth_mode": "MEDIUM",
            "match": True,
            "slug": f"slug-{i}",
            "run_id": f"run-{i:04d}",
            "topic": "some topic",
        }
        for i in range(10)
    ]

    confusion_matrix = build_confusion_matrix(run_results)
    pcts = compute_percentages(run_results)

    _assert(pcts["pct_medium"] == 100.0, f"all-MEDIUM → pct_medium=100.0, got {pcts['pct_medium']}")
    _assert(pcts["pct_light"] == 0.0,   f"all-MEDIUM → pct_light=0.0, got {pcts['pct_light']}")
    _assert(pcts["pct_heavy"] == 0.0,   f"all-MEDIUM → pct_heavy=0.0, got {pcts['pct_heavy']}")

    # print_tripwire_report returns True when a tripwire fires
    fired = print_tripwire_report(run_results, confusion_matrix, pcts)
    _assert(fired, "tripwire should fire when pct_medium >= 70 and pct_heavy < 20")


# ---------------------------------------------------------------------------
# Test: tripwire does NOT fire on a well-distributed ground truth
# ---------------------------------------------------------------------------

def test_tripwire_no_fire() -> None:
    print("\n--- test_tripwire_no_fire ---")

    # 5 LIGHT, 3 MEDIUM, 2 HEAVY — pct_medium=30%, pct_heavy=20%
    run_results = (
        [{"classified_mode": "LIGHT",  "ground_truth_mode": "LIGHT",  "match": True,
          "slug": "s", "run_id": f"r-{i}", "topic": "t"} for i in range(5)]
        + [{"classified_mode": "MEDIUM", "ground_truth_mode": "MEDIUM", "match": True,
            "slug": "s", "run_id": f"r-{i+5}", "topic": "t"} for i in range(3)]
        + [{"classified_mode": "HEAVY",  "ground_truth_mode": "HEAVY",  "match": True,
            "slug": "s", "run_id": f"r-{i+8}", "topic": "t"} for i in range(2)]
    )

    confusion_matrix = build_confusion_matrix(run_results)
    pcts = compute_percentages(run_results)

    fired = print_tripwire_report(run_results, confusion_matrix, pcts)
    _assert(not fired, "tripwire should NOT fire on well-distributed set")


# ---------------------------------------------------------------------------
# Test: discover_runs + load_events with synthetic fixtures on disk
# ---------------------------------------------------------------------------

def test_discover_runs_from_fixtures() -> None:
    print("\n--- test_discover_runs_from_fixtures ---")

    with tempfile.TemporaryDirectory(prefix="t007-harness-") as tmp:
        root = Path(tmp)

        # Build a minimal archive structure:
        # root/
        #   slug-a/archive/run-0001/
        #   slug-b/archive/run-0002/
        #   slug-c/archive/run-0003/

        fixtures = [
            ("slug-a", "run-0001", LIGHT_MANIFEST,  LIGHT_EVENTS,  "LIGHT"),
            ("slug-b", "run-0002", MEDIUM_MANIFEST, MEDIUM_EVENTS, "MEDIUM"),
            ("slug-c", "run-0003", HEAVY_MANIFEST,  HEAVY_EVENTS,  "HEAVY"),
        ]

        for slug, run_id, manifest, events, expected_gt in fixtures:
            run_dir = root / slug / "archive" / run_id
            _write_fixture(run_dir, manifest, events)

        runs = discover_runs(root, n_runs=10)

        _assert(len(runs) == 3, f"discover_runs returns 3 runs, got {len(runs)}")

        # Build a quick lookup
        by_slug = {r["slug"]: r for r in runs}

        for slug, run_id, manifest, events, expected_gt in fixtures:
            run = by_slug.get(slug)
            _assert(run is not None, f"run for slug={slug} discovered")
            if run is None:
                continue
            gt = classify_ground_truth(run["manifest"], run["events"])
            _assert(
                gt == expected_gt,
                f"slug={slug}: classify_ground_truth={gt}, expected={expected_gt}",
            )


# ---------------------------------------------------------------------------
# Test: majority_vote
# ---------------------------------------------------------------------------

def test_majority_vote() -> None:
    print("\n--- test_majority_vote ---")

    _assert(majority_vote(["LIGHT", "LIGHT", "MEDIUM"]) == "LIGHT", "majority LIGHT wins")
    _assert(majority_vote(["HEAVY", "HEAVY", "MEDIUM"]) == "HEAVY", "majority HEAVY wins")
    _assert(majority_vote(["MEDIUM", "MEDIUM", "LIGHT"]) == "MEDIUM", "majority MEDIUM wins")
    # All same
    _assert(majority_vote(["LIGHT", "LIGHT", "LIGHT"]) == "LIGHT", "unanimous LIGHT")
    # Tie: LIGHT vs HEAVY (1 each) + 1 MEDIUM → MEDIUM tie-break
    _assert(majority_vote(["LIGHT", "HEAVY", "MEDIUM"]) == "MEDIUM", "3-way tie → MEDIUM")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== test-scope-probe-calibrate.py ===")

    test_classify_ground_truth()
    test_confusion_matrix()
    test_tripwire_all_medium()
    test_tripwire_no_fire()
    test_discover_runs_from_fixtures()
    test_majority_vote()

    print()
    if _FAILURES:
        print(f"RESULT: FAIL — {len(_FAILURES)} assertion(s) failed:")
        for f in _FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("RESULT: PASS — all assertions passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
