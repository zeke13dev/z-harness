from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "log-execute-efficiency-event.py"
SKILL = ROOT / "skills" / "z-execute" / "SKILL.md"
PREFLIGHT = ROOT / "scripts" / "intent-dispatch-preflight.py"
TASK_ID = "T007"
FINDING_ID = "T007-F0123456789abcdef"

EXPECTED_PREFLIGHT_REJECTION_CODES = {
    "DUPLICATE_ARTIFACT_ID",
    "DUPLICATE_GRAPH_ID",
    "DUPLICATE_TASK_ID",
    "FRONTIER_REQUIRES_SERIAL",
    "HARD_EXCLUSION",
    "HELD_PATH_COLLISION",
    "INCOMPLETE_INTENT_CONTEXT",
    "INVALID_ARTIFACT_ENTRY",
    "INVALID_ARTIFACT_ID",
    "INVALID_COMPLETED_IDS",
    "INVALID_DEPENDENCIES",
    "INVALID_DEPENDENCY",
    "INVALID_FANOUT",
    "INVALID_GRAPH",
    "INVALID_GRAPH_ID",
    "INVALID_GRAPH_NODE",
    "INVALID_GRAPH_NODES",
    "INVALID_HARD_EXCLUSIONS",
    "INVALID_HELD_PATH",
    "INVALID_HELD_PATHS",
    "INVALID_INPUT",
    "INVALID_JSON",
    "INVALID_READY_FRONTIER",
    "INVALID_READY_IDS",
    "INVALID_READY_TASK",
    "INVALID_RUN_ID",
    "INVALID_TASK",
    "INVALID_TASK_ID",
    "INVALID_TASKS",
    "MISSING_ATOMIC_REASON",
    "MISSING_COMPLEXITY",
    "TASK_GRAPH_MISMATCH",
    "UNREADABLE_INTENT_CONTEXT",
    "UNSAFE_PATH_OVERLAP",
    "UNSATISFIED_DEPENDENCY",
    "UNUSABLE_PATHS",
}

GENERATION_PREFLIGHT_REJECTION_CODES = {
    "DUPLICATE_ARTIFACT_ID",
    "HARD_EXCLUSION",
    "INVALID_ARTIFACT_ENTRY",
    "INVALID_ARTIFACT_ID",
    "INVALID_GRAPH",
    "INVALID_GRAPH_NODES",
    "INVALID_HARD_EXCLUSIONS",
    "INVALID_TASKS",
    "UNUSABLE_PATHS",
}

SELECTED_BATCH_PREFLIGHT_REJECTION_CODES = {
    "DUPLICATE_GRAPH_ID",
    "DUPLICATE_TASK_ID",
    "FRONTIER_REQUIRES_SERIAL",
    "HARD_EXCLUSION",
    "HELD_PATH_COLLISION",
    "INCOMPLETE_INTENT_CONTEXT",
    "INVALID_COMPLETED_IDS",
    "INVALID_DEPENDENCIES",
    "INVALID_DEPENDENCY",
    "INVALID_FANOUT",
    "INVALID_GRAPH",
    "INVALID_GRAPH_ID",
    "INVALID_GRAPH_NODE",
    "INVALID_HARD_EXCLUSIONS",
    "INVALID_HELD_PATH",
    "INVALID_HELD_PATHS",
    "INVALID_READY_FRONTIER",
    "INVALID_READY_IDS",
    "INVALID_READY_TASK",
    "INVALID_RUN_ID",
    "INVALID_TASK",
    "INVALID_TASK_ID",
    "INVALID_TASKS",
    "MISSING_ATOMIC_REASON",
    "MISSING_COMPLEXITY",
    "TASK_GRAPH_MISMATCH",
    "UNREADABLE_INTENT_CONTEXT",
    "UNSAFE_PATH_OVERLAP",
    "UNSATISFIED_DEPENDENCY",
    "UNUSABLE_PATHS",
}


def _normalize(kind: str, payload: dict[str, object]) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(HELPER), kind, json.dumps(payload)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _reject(kind: str, payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [sys.executable, str(HELPER), kind, json.dumps(payload)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    return completed


def _preflight(document: object | str) -> set[str]:
    completed = subprocess.run(
        [sys.executable, str(PREFLIGHT)],
        input=document if isinstance(document, str) else json.dumps(document),
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 1
    return {error["code"] for error in json.loads(completed.stdout)["errors"]}


def _selected_document(tmp_path: Path) -> dict[str, object]:
    context: dict[str, str] = {}
    for name in ("frozen_intent", "graph", "ledger", "strategy", "dependency_context"):
        path = tmp_path / name
        path.write_text("fixture\n", encoding="utf-8")
        context[name] = str(path)
    return {
        "run_id": "run-a",
        "tasks": [{"id": "T001", "paths": ["scripts/a.py"], "complexity": "low"}],
        "graph": {"nodes": [{"id": "T001", "dependencies": [], "status": "ready"}]},
        "intent_context": context,
        "fanout": 1,
        "ready_ids": ["T001"],
        "hard_exclusions": [],
        "held_paths": [],
    }


def _actual_preflight_reason_codes_by_mode(tmp_path: Path) -> dict[str, set[str]]:
    """Execute both preflight modes through every current rejection branch."""
    common_codes = _preflight("{")
    common_codes.update(_preflight([]))
    generation_codes: set[str] = set()
    generation_codes.update(
        _preflight(
            {
                "validation_scope": "generated_artifact",
                "hard_exclusions": ["/invalid"],
                "tasks": "invalid",
                "graph": {"nodes": "invalid"},
            }
        )
    )
    generation_codes.update(
        _preflight(
            {
                "validation_scope": "generated_artifact",
                "hard_exclusions": [],
                "tasks": [],
                "graph": "invalid",
            }
        )
    )
    generation_codes.update(
        _preflight(
            {
                "validation_scope": "generated_artifact",
                "hard_exclusions": ["runtime/watchdog"],
                "tasks": [
                    None,
                    {"id": "bad", "paths": []},
                    {"id": "T001", "paths": []},
                    {"id": "T001", "paths": []},
                    {"id": "T002", "paths": "invalid"},
                    {"id": "T003", "paths": ["../invalid"]},
                    {"id": "T004", "paths": ["runtime/watchdog/worker.py"]},
                ],
                "graph": {"nodes": []},
            }
        )
    )

    selected_codes: set[str] = set()
    valid = _selected_document(tmp_path)
    selected_codes.update(
        _preflight(
            {
                "run_id": "",
                "tasks": "invalid",
                "graph": [],
                "intent_context": None,
                "fanout": 0,
                "ready_ids": [1],
                "hard_exclusions": "invalid",
                "held_paths": "invalid",
            }
        )
    )
    selected_codes.update(
        _preflight(
            {
                **valid,
                "tasks": [],
                "graph": {
                    "nodes": [
                        None,
                        {"id": "bad"},
                        {"id": "T001", "dependencies": []},
                        {"id": "T001", "dependencies": []},
                        {"id": "T002", "dependencies": "invalid"},
                    ]
                },
            }
        )
    )
    selected_codes.update(
        _preflight(
            {
                **valid,
                "graph": {"dependencies": {"T001": []}, "completed_ids": ["bad"]},
            }
        )
    )
    selected_codes.update(
        _preflight(
            {
                **valid,
                "intent_context": {
                    key: str(tmp_path / "missing" / key)
                    for key in valid["intent_context"]
                },
            }
        )
    )
    selected_codes.update(
        _preflight(
            {
                **valid,
                "tasks": [
                    None,
                    {"id": "bad"},
                    {"id": "T001", "paths": ["scripts/a.py"], "complexity": "low"},
                    {"id": "T001", "paths": ["scripts/a.py"], "complexity": "low"},
                    {"id": "T002", "paths": [], "complexity": "invalid"},
                    {
                        "id": "T003",
                        "paths": ["a/1", "a/2", "a/3", "a/4"],
                        "complexity": "medium",
                    },
                    {
                        "id": "T004",
                        "paths": ["runtime/watchdog/worker.py"],
                        "complexity": "high",
                    },
                ],
                "graph": {
                    "nodes": [
                        {"id": "T001", "dependencies": ["T999"]},
                        {"id": "T002", "dependencies": []},
                        {"id": "T003", "dependencies": []},
                        {"id": "T004", "dependencies": []},
                        {"id": "T005", "dependencies": []},
                    ]
                },
                "ready_ids": ["T999"],
                "hard_exclusions": ["runtime/watchdog"],
                "held_paths": [None],
            }
        )
    )
    selected_codes.update(_preflight({**valid, "ready_ids": ["T001", "T001"]}))
    selected_codes.update(
        _preflight(
            {
                **valid,
                "tasks": [
                    {"id": "T001", "paths": ["scripts/a.py"], "complexity": "low"},
                    {
                        "id": "T002",
                        "paths": ["scripts/a.py/child", "b/2", "b/3", "b/4"],
                        "complexity": "high",
                        "atomic_reason": "one atomic change",
                        "disjointness_proven": False,
                    },
                    {"id": "T003", "paths": ["scripts/c.py"], "complexity": "low"},
                ],
                "graph": {
                    "nodes": [
                        {"id": "T001", "dependencies": [], "status": "ready"},
                        {"id": "T002", "dependencies": ["T003"], "status": "ready"},
                        {"id": "T003", "dependencies": [], "status": "ready"},
                    ]
                },
                "fanout": 2,
                "ready_ids": ["T001", "T002"],
                "held_paths": [
                    {"run_id": "peer-run", "path": "scripts/a.py"},
                    {"run_id": 7, "path": "invalid"},
                ],
            }
        )
    )
    return {
        "common": common_codes,
        "generation": generation_codes,
        "selected_batch": selected_codes,
    }


def _execute_preflight_telemetry_seam(
    tmp_path: Path,
    *,
    marker: str,
    result_variable: str,
    codes: set[str],
) -> list[dict[str, object]]:
    text = SKILL.read_text(encoding="utf-8")
    seam = text.split(f"# {marker}-BEGIN", 1)[1].split(f"# {marker}-END", 1)[0]
    result_path = tmp_path / f"{marker.lower()}.json"
    capture_path = tmp_path / f"{marker.lower()}.jsonl"
    result_path.write_text(
        json.dumps({"ok": False, "errors": [{"code": code} for code in sorted(codes)]}),
        encoding="utf-8",
    )
    script = f"""
log_execute_efficiency_event() {{
  python3 "$HELPER_PATH" "$1" "$2" >> "$CAPTURE_PATH"
}}
{result_variable}="$RESULT_PATH"
{seam}
"""
    subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HELPER_PATH": str(HELPER),
            "CAPTURE_PATH": str(capture_path),
            "RESULT_PATH": str(result_path),
        },
    )
    return [json.loads(line) for line in capture_path.read_text(encoding="utf-8").splitlines()]


def test_events_aggregate_normalized_execute_efficiency_outcomes() -> None:
    events = [
        _normalize(
            "surgical_eligibility",
            {
                "task_id": TASK_ID,
                "outcome": "eligible",
                "reason": "eligible",
                "finding_count": 2,
                "path_count": 1,
            },
        ),
        _normalize(
            "surgical_result",
            {"task_id": TASK_ID, "outcome": "success", "reason": "none", "attempt_count": 1},
        ),
        _normalize(
            "surgical_result",
            {
                "task_id": TASK_ID,
                "outcome": "fallback",
                "reason": "post_review_failed",
                "attempt_count": 1,
            },
        ),
        _normalize(
            "finding_transition",
            {
                "task_id": TASK_ID,
                "finding_id": FINDING_ID,
                "outcome": "resolved",
                "count": 1,
            },
        ),
        _normalize(
            "finding_transition",
            {
                "task_id": TASK_ID,
                "finding_id": FINDING_ID,
                "outcome": "still_open",
                "count": 1,
            },
        ),
        _normalize(
            "finding_transition",
            {"task_id": TASK_ID, "finding_id": FINDING_ID, "outcome": "new", "count": 1},
        ),
        _normalize(
            "preflight_rejection",
            {
                "task_id": TASK_ID,
                "outcome": "rejected",
                "reason": "held_path_collision",
                "count": 1,
            },
        ),
        _normalize(
            "subagent_dispatch",
            {"task_id": TASK_ID, "role": "implementer", "count": 1},
        ),
    ]

    outcomes = Counter((event["event_kind"], event.get("outcome")) for event in events)
    reasons = Counter((event["event_kind"], event.get("reason")) for event in events)
    dispatches = Counter(
        event.get("role")
        for event in events
        if event["event_kind"] == "subagent_dispatch"
    )

    assert outcomes[("surgical_eligibility", "eligible")] == 1
    assert outcomes[("surgical_result", "success")] == 1
    assert outcomes[("surgical_result", "fallback")] == 1
    assert outcomes[("finding_transition", "resolved")] == 1
    assert outcomes[("finding_transition", "still_open")] == 1
    assert outcomes[("finding_transition", "new")] == 1
    assert reasons[("preflight_rejection", "held_path_collision")] == 1
    assert dispatches["implementer"] == 1


def test_helper_fails_closed_on_sensitive_or_unbounded_values() -> None:
    sentinels = [
        "sentinel prompt",
        "reviewer prose",
        '{"tool_output":"sentinel"}',
        "sk-live-secret",
        "/Users/private/project/file.py",
    ]
    valid = {"task_id": TASK_ID, "role": "reviewer", "count": 1}
    for field, sentinel in zip(
        ["prompt", "reviewer_text", "tool_payload", "secret", "path"], sentinels, strict=True
    ):
        completed = _reject("subagent_dispatch", {**valid, field: sentinel})
        assert sentinel not in completed.stderr
    _reject("subagent_dispatch", {**valid, "role": "/Users/private/reviewer"})
    _reject("subagent_dispatch", {**valid, "count": -1})
    _reject("unknown_event", valid)


def test_all_normalized_outputs_use_only_schema_fields_and_identifiers() -> None:
    event = _normalize(
        "finding_transition",
        {"task_id": TASK_ID, "finding_id": FINDING_ID, "outcome": "new", "count": 1},
    )
    assert set(event) == {"event_kind", "task_id", "finding_id", "outcome", "count"}
    serialized = json.dumps(event)
    assert "/" not in serialized
    assert "prompt" not in serialized
    assert "reviewer" not in serialized
    assert "tool" not in serialized
    assert "secret" not in serialized


def test_every_executable_preflight_rejection_has_a_normalized_reason(
    tmp_path: Path,
) -> None:
    codes_by_mode = _actual_preflight_reason_codes_by_mode(tmp_path)
    assert codes_by_mode["common"] == {"INVALID_INPUT", "INVALID_JSON"}
    assert codes_by_mode["generation"] == GENERATION_PREFLIGHT_REJECTION_CODES
    assert codes_by_mode["selected_batch"] == SELECTED_BATCH_PREFLIGHT_REJECTION_CODES
    codes = set().union(*codes_by_mode.values())
    assert len(EXPECTED_PREFLIGHT_REJECTION_CODES) == 36
    assert codes == EXPECTED_PREFLIGHT_REJECTION_CODES
    for code in codes:
        event = _normalize(
            "preflight_rejection",
            {"outcome": "rejected", "reason": code.lower(), "count": 1},
        )
        assert event["reason"] == code.lower()


def test_generation_preflight_failure_seam_emits_normalized_rejections(
    tmp_path: Path,
) -> None:
    events = _execute_preflight_telemetry_seam(
        tmp_path,
        marker="GENERATION-PREFLIGHT-REJECTION-TELEMETRY",
        result_variable="INTENT_GENERATION_EXCLUSION_RESULT",
        codes=GENERATION_PREFLIGHT_REJECTION_CODES,
    )
    assert {event["reason"] for event in events} == {
        code.lower() for code in GENERATION_PREFLIGHT_REJECTION_CODES
    }
    assert "invalid_graph_nodes" in {event["reason"] for event in events}
    assert all(event["event_kind"] == "preflight_rejection" for event in events)
    assert all(event["outcome"] == "rejected" for event in events)
    assert all(event["count"] == 1 for event in events)


def test_selected_batch_preflight_failure_seam_emits_normalized_rejections(
    tmp_path: Path,
) -> None:
    events = _execute_preflight_telemetry_seam(
        tmp_path,
        marker="SELECTED-BATCH-PREFLIGHT-REJECTION-TELEMETRY",
        result_variable="INTENT_PREFLIGHT_RESULT",
        codes=SELECTED_BATCH_PREFLIGHT_REJECTION_CODES,
    )
    assert {event["reason"] for event in events} == {
        code.lower() for code in SELECTED_BATCH_PREFLIGHT_REJECTION_CODES
    }
    assert all(event["event_kind"] == "preflight_rejection" for event in events)
    assert all(event["outcome"] == "rejected" for event in events)
    assert all(event["count"] == 1 for event in events)


def test_both_preflight_failure_seams_remain_in_control_flow() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert text.index("intent_generation_exclusion_failed") < text.index(
        "# GENERATION-PREFLIGHT-REJECTION-TELEMETRY-BEGIN"
    ) < text.index("generated INTENT artifact violates hard exclusions")
    assert text.index("intent_dispatch_preflight_failed") < text.index(
        "# SELECTED-BATCH-PREFLIGHT-REJECTION-TELEMETRY-BEGIN"
    ) < text.index("INTENT dispatch preflight failed at scheduler depth")


def test_execute_skill_wires_every_required_outcome_seam() -> None:
    text = SKILL.read_text(encoding="utf-8")
    for marker in (
        'log_execute_efficiency_event surgical_eligibility',
        'log_execute_efficiency_event surgical_result',
        'log_execute_efficiency_event finding_transition',
        'log_execute_efficiency_event preflight_rejection',
        'log_execute_efficiency_event subagent_dispatch',
    ):
        assert marker in text
    assert "execute_efficiency" in text
    assert "2>/dev/null || true" in text
    production_axiom_posture = (
        "4a. **Production axiom posture.** Axiom extraction is a development-only "
        "surface.\n"
        "    `/z-execute` does not parse an axiom-ready marker or dispatch an "
        "extractor in the\n"
        "    production workflow; memory review continues solely through the "
        "exported review agent."
    )
    assert production_axiom_posture in text
    assert '"role":"axiom_extractor"' not in text
    for role in (
        "complexity_classifier",
        "context_curator",
        "implementer",
        "pre_reviewer",
        "remote_runner",
        "review_agent",
        "reviewer",
        "scope_extractor",
        "self_reviewer",
        "spec_precheck",
        "surgical_fixer",
        "task_tree_generator",
        "tier1_doc_updater",
    ):
        assert f'"role":"{role}"' in text
