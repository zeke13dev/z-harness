from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PATH = Path(__file__).parent.parent / "scripts" / "validate-z-manager-plan.py"
SPEC = importlib.util.spec_from_file_location("z_manager_plan_validator", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def plan() -> dict:
    return {
        "goals": ["Implement the requested behavior"],
        "invariants": ["Keep changes inside the declared scope"],
        "allowed_paths": ["src", "tests"],
        "acceptance_commands": ["cargo test --all-targets"],
        "nodes": [
            {"id": "a", "goal": "Implement A", "dependencies": [], "allowed_paths": ["src/a.rs"], "acceptance": ["unit"]},
            {"id": "b", "goal": "Test B", "dependencies": ["a"], "allowed_paths": ["tests/b.rs"], "acceptance": ["integration"]},
        ],
    }


def test_valid_plan_returns_stable_topological_order() -> None:
    assert MODULE.validate(plan()) == {"valid": True, "topological_order": ["a", "b"], "node_count": 2}


@pytest.mark.parametrize("mutation", ["cycle", "scope", "thirteen", "unsafe"])
def test_invalid_plans_fail_closed(mutation: str) -> None:
    value = plan()
    if mutation == "cycle":
        value["nodes"][0]["dependencies"] = ["b"]
    elif mutation == "scope":
        value["nodes"][0]["allowed_paths"] = ["deploy/prod.sh"]
    elif mutation == "thirteen":
        value["nodes"] = [
            {"id": str(i), "goal": f"Node {i}", "dependencies": [], "allowed_paths": ["src"], "acceptance": ["ok"]}
            for i in range(13)
        ]
    else:
        value["acceptance_commands"] = ["git push origin main"]
    with pytest.raises(ValueError):
        MODULE.validate(value)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("goals", [], "goals"),
        ("invariants", [""], "invariants"),
        ("node_goal", "", "goal"),
        ("node_acceptance", [""], "acceptance"),
    ],
)
def test_incomplete_contract_fields_fail_closed(field: str, value: object, error: str) -> None:
    candidate = plan()
    if field == "node_goal":
        candidate["nodes"][0]["goal"] = value
    elif field == "node_acceptance":
        candidate["nodes"][0]["acceptance"] = value
    else:
        candidate[field] = value
    with pytest.raises(ValueError, match=error):
        MODULE.validate(candidate)


@pytest.mark.parametrize(
    "command",
    ["cargo publish", "git rebase main", "rm -rf build", "psql -c 'drop table users'"],
)
def test_additional_safety_boundaries_fail_closed(command: str) -> None:
    candidate = plan()
    candidate["acceptance_commands"] = [command]
    with pytest.raises(ValueError, match="safety boundary"):
        MODULE.validate(candidate)
