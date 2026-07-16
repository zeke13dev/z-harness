import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "intent-dispatch-preflight.py"
SPEC = importlib.util.spec_from_file_location("intent_dispatch_preflight", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def context(tmp_path):
    result = {}
    for name in ("frozen_intent", "graph", "ledger", "strategy", "dependency_context"):
        path = tmp_path / name
        path.write_text(name)
        result[name] = str(path)
    return result


def document(tmp_path, **overrides):
    value = {
        "run_id": "run-a",
        "tasks": [{"id": "T001", "paths": ["scripts/new-helper.py"], "complexity": "medium"}],
        "graph": {"nodes": [{"id": "T001", "dependencies": []}]},
        "ready_ids": ["T001"],
        "fanout": 3,
        "intent_context": context(tmp_path),
        "held_paths": [],
        "hard_exclusions": ["runtime/watchdog/", "skills/z-plan/SKILL.md", "skills/z-plan-split/SKILL.md"],
    }
    value.update(overrides)
    return value


def codes(result):
    return {entry["code"] for entry in result["errors"]}


def test_valid_bounded_disjoint_frontier(tmp_path):
    value = document(tmp_path)
    value["tasks"].append({"id": "T002", "paths": ["tests/new-helper.py"], "complexity": "low"})
    value["graph"] = {"nodes": [{"id": "T001", "dependencies": []}, {"id": "T002", "dependencies": []}]}
    value["ready_ids"] = ["T001", "T002"]
    result = MODULE.preflight(value)
    assert result["ok"] is True
    assert result["serial_only"] is False
    assert result["deferred_followups"] == [{"topic": "supervisor_integration", "status": "deferred", "reason": "Supervisor lifecycle integration is intentionally outside this read-only preflight."}]


def test_rejects_ids_dependencies_frontier_and_overlap(tmp_path):
    value = document(tmp_path, fanout=4, ready_ids=["T002", "T002"])
    value["tasks"] = [
        {"id": "broken", "paths": ["scripts/a.py"], "complexity": "low"},
        {"id": "T002", "paths": ["scripts/a.py"], "complexity": ""},
    ]
    value["graph"] = {"nodes": [{"id": "T002", "dependencies": ["T999"]}]}
    result = MODULE.preflight(value)
    assert {"INVALID_TASK_ID", "INVALID_FANOUT", "INVALID_READY_FRONTIER", "INVALID_DEPENDENCY"} <= codes(result)


def test_rejects_exclusions_held_paths_and_incomplete_context(tmp_path):
    value = document(tmp_path, intent_context={}, held_paths=[{"run_id": "run-b", "path": "runtime/watchdog/fanout.py"}])
    value["tasks"] = [{"id": "T001", "paths": ["runtime/watchdog/fanout.py"], "complexity": "medium"}]
    result = MODULE.preflight(value)
    assert "HARD_EXCLUSION" in codes(result)
    assert "HELD_PATH_COLLISION" in codes(result)
    assert "INCOMPLETE_INTENT_CONTEXT" in codes(result)


def test_atomic_requires_reason_and_serializes_without_proof(tmp_path):
    paths = [f"scripts/{name}.py" for name in ("a", "b", "c", "d")]
    value = document(tmp_path, tasks=[{"id": "T001", "paths": paths, "complexity": "high"}])
    assert "MISSING_ATOMIC_REASON" in codes(MODULE.preflight(value))
    value["tasks"][0]["atomic_reason"] = "The change updates one atomic on-disk contract."
    result = MODULE.preflight(value)
    assert result["ok"] is True
    assert result["serial_only"] is True
    value["tasks"][0]["disjointness_proven"] = True
    assert MODULE.preflight(value)["serial_only"] is False


def test_atomic_requires_literal_true_for_disjointness_proof(tmp_path):
    paths = [f"scripts/{name}.py" for name in ("a", "b", "c", "d")]
    value = document(tmp_path, tasks=[{
        "id": "T001",
        "paths": paths,
        "complexity": "high",
        "atomic_reason": "The change updates one atomic on-disk contract.",
    }])
    for proof in (1, "true", [], {}):
        value["tasks"][0]["disjointness_proven"] = proof
        assert MODULE.preflight(value)["serial_only"] is True


def test_rejects_non_task_ids_in_completed_ids(tmp_path):
    value = document(tmp_path)
    value["graph"] = {"dependencies": {"T001": []}, "completed_ids": ["done", "T1"]}
    result = MODULE.preflight(value)
    assert "INVALID_COMPLETED_IDS" in codes(result)


def test_ready_dependency_needs_completed_graph_node(tmp_path):
    value = document(tmp_path)
    value["tasks"].append({"id": "T002", "paths": ["scripts/b.py"], "complexity": "low"})
    value["graph"] = {"nodes": [{"id": "T001", "dependencies": []}, {"id": "T002", "dependencies": ["T001"]}]}
    value["ready_ids"] = ["T002"]
    assert "UNSATISFIED_DEPENDENCY" in codes(MODULE.preflight(value))
    value["graph"]["nodes"][0]["status"] = "completed"
    assert MODULE.preflight(value)["ok"] is True
