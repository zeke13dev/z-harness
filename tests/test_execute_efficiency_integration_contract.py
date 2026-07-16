"""Integration contract for the execute-efficiency documentation seams.

The skill is the executable contract for host drivers, so these tests pin the
three small helpers to their documented hand-off points without pretending that
the documentation itself starts a scheduler or supervisor.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "z-execute" / "SKILL.md"
FINDING_STATE = ROOT / "scripts" / "review-finding-state.py"
PREFLIGHT = ROOT / "scripts" / "intent-dispatch-preflight.py"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _context(tmp_path: Path) -> dict[str, str]:
    result = {}
    for name in ("frozen_intent", "graph", "ledger", "strategy", "dependency_context"):
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        result[name] = str(path)
    return result


def _builder_code() -> str:
    match = re.search(
        r"# PREFLIGHT-INPUT-BUILDER-BEGIN\n(.*?)# PREFLIGHT-INPUT-BUILDER-END",
        _text(),
        re.S,
    )
    assert match is not None
    return match.group(1)


def _run_builder(
    tmp_path: Path,
    task_text: str,
    graph: dict,
    selected: str,
    leases: list[dict] | None = None,
) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    tasks_file = tmp_path / "TASKS.md"
    graph_file = tmp_path / "work-graph.json"
    lease_file = tmp_path / "leases.json"
    tasks_file.write_text(task_text, encoding="utf-8")
    graph_file.write_text(json.dumps(graph), encoding="utf-8")
    lease_file.write_text(json.dumps(leases or []), encoding="utf-8")
    context = _context(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-",
            str(tasks_file),
            str(graph_file),
            selected,
            "3",
            str(lease_file),
            context["frozen_intent"],
            context["ledger"],
            context["strategy"],
            context["dependency_context"],
            "run-a",
        ],
        input=_builder_code(),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


REAL_TASK_BLOCKS = """\
## T005 — Integrate the selected batch `[ ]`
**Files:** skills/z-execute/SKILL.md, tests/test_execute_efficiency_integration_contract.py
**Depends on:** T001, T002, T003
**Complexity:** high

## T006 — A later partition `[ ]`
**Files:** scripts/later.py
**Depends on:** T005
**Complexity:** low
"""


REAL_GRAPH = {
    "nodes": [
        {"id": "T001", "status": "done", "depends_on": []},
        {"id": "T002", "status": "done", "depends_on": []},
        {"id": "T003", "status": "done", "depends_on": []},
        {"id": "T005", "status": "ready", "depends_on": ["T001", "T002", "T003"]},
        {"id": "T006", "status": "blocked", "depends_on": ["T005"]},
    ]
}


def _live_lease(run_id: str, path: str, **overrides: object) -> dict:
    record = {
        "schema_version": 2,
        "run_id": run_id,
        "status": "running",
        "last_heartbeat": "2999-01-01T00:00:00Z",
        "held_paths": [{"path": path}],
    }
    record.update(overrides)
    return record


def test_surgical_retry_is_bounded_and_preserves_normal_deep_retry() -> None:
    text = _text()

    assert "#### Bounded surgical lane before the existing deep retry" in text
    assert "Only after the **first full semantic review**" in text
    assert "at most three actionable blocker/major findings" in text
    assert "at most two declared task paths" in text
    assert "ATTEMPT_LIMIT: 1" in text
    assert "does not increment `CYCLE` or consume the normal retry allowance" in text
    assert "fall through to the normal\ndeep retry" in text
    assert "SEMANTIC_REVIEW_ROUND=0" in text
    assert "SURGICAL_ATTEMPTED=0" in text
    assert "NORMAL_DEEP_RETRY_USED=0" in text
    assert "review-findings-semantic-v$SEMANTIC_REVIEW_ROUND.json" in text
    assert "leave `CYCLE=1` and `NORMAL_DEEP_RETRY_USED=0`" in text
    assert "post-deep-retry full review reaches the existing second-failure user gate" in text
    assert "never dispatch surgery twice" in text
    assert "never overwrite the v1\nsurgical artifacts" in text
    assert "If that post-surgical review\nfails, flow to the still-untouched normal step-7a deep retry" in text
    assert "then run yet another full semantic review" in text
    assert "review_mode: full_semantic_current_task" in text
    assert "semantic_finding_state_path: $TASK_ARCHIVE/review-findings-semantic-v$((SEMANTIC_REVIEW_ROUND-1)).json" in text
    assert "may report new\nregressions anywhere in that diff" in text
    assert "do NOT re-flag issues outside the delta" not in text
    assert "reviewer is explicitly told to scope to the delta" not in text


def test_finding_state_preserves_resolved_open_and_new_findings() -> None:
    completed = subprocess.run(
        [sys.executable, str(FINDING_STATE)],
        input=json.dumps(
            {
                "task_id": "T001",
                "prior_findings": [
                    {"path": "scripts/a.py", "message": "fixed"},
                    {"path": "scripts/b.py", "message": "still open"},
                ],
                "current_findings": [
                    {"path": "scripts/b.py", "message": "still open"},
                    {"path": "scripts/c.py", "message": "new"},
                ],
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    result = json.loads(completed.stdout)
    prior = {entry["message"]: entry["disposition"] for entry in result["prior_findings"]}
    current = {entry["message"]: entry["disposition"] for entry in result["current_findings"]}

    assert prior == {"fixed": "resolved", "still open": "still_open"}
    assert current == {"still open": "still_open", "new": "new"}
    assert result["aggregate_review"]["preserved"] is True
    assert "Retry finding-state artifact (every full semantic review)" in _text()
    assert "conditional aggregate review" in _text()


def test_documented_builder_executes_on_real_task_block_and_exact_batch(tmp_path: Path) -> None:
    document = _run_builder(
        tmp_path,
        REAL_TASK_BLOCKS,
        REAL_GRAPH,
        "T005",
        leases=[
            _live_lease("peer-run", "scripts/unrelated.py"),
            _live_lease("run-a", "skills/z-execute/SKILL.md"),
        ],
    )

    assert document["ready_ids"] == ["T005"]
    assert [task["id"] for task in document["tasks"]] == ["T005"]
    assert document["tasks"][0]["paths"] == [
        "skills/z-execute/SKILL.md",
        "tests/test_execute_efficiency_integration_contract.py",
    ]
    assert document["graph"] == {
        "nodes": [{"id": "T005", "dependencies": [], "status": "ready"}]
    }
    assert document["fanout"] == 3
    assert document["held_paths"] == [
        {"run_id": "peer-run", "path": "scripts/unrelated.py"},
    ]
    assert r're.split(r"(?=^## T\d+\b)"' in _builder_code()

    completed = subprocess.run(
        [sys.executable, str(PREFLIGHT)],
        input=json.dumps(document),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["ok"] is True


def test_held_path_snapshot_keeps_only_live_lease_capable_peers(tmp_path: Path) -> None:
    leases = [
        _live_lease("live-peer", "scripts/live.py"),
        _live_lease("run-a", "scripts/self.py"),
        _live_lease("terminal-peer", "scripts/terminal.py", status="complete"),
        _live_lease("aborted-peer", "scripts/aborted.py", status="aborted"),
        _live_lease("stale-status-peer", "scripts/stale-status.py", status="stale"),
        _live_lease(
            "stale-age-peer",
            "scripts/stale-age.py",
            last_heartbeat="2000-01-01T00:00:00Z",
        ),
        {
            "schema_version": 1,
            "run_id": "legacy-peer",
            "status": "running",
            "last_heartbeat": "2999-01-01T00:00:00Z",
            "held_paths": [{"path": "scripts/legacy.py"}],
        },
        {
            "schema_version": 2,
            "run_id": "missing-held-paths-peer",
            "status": "running",
            "last_heartbeat": "2999-01-01T00:00:00Z",
        },
    ]
    document = _run_builder(tmp_path, REAL_TASK_BLOCKS, REAL_GRAPH, "T005", leases=leases)

    assert document["held_paths"] == [{"run_id": "live-peer", "path": "scripts/live.py"}]


@pytest.mark.parametrize(
    ("declared_path", "held_path"),
    [
        ("scripts/supervisor", "scripts/supervisor/session.py"),
        ("scripts/supervisor/session.py", "scripts/supervisor"),
    ],
)
def test_held_path_parent_child_overlap_blocks_dispatch(
    tmp_path: Path, declared_path: str, held_path: str
) -> None:
    document = _run_builder(
        tmp_path,
        f"## T007 — Parent child collision `[ ]`\n**Files:** {declared_path}\n**Complexity:** high\n",
        {"nodes": [{"id": "T007", "status": "ready", "depends_on": []}]},
        "T007",
        leases=[_live_lease("peer-run", held_path)],
    )
    result = subprocess.run(
        [sys.executable, str(PREFLIGHT)],
        input=json.dumps(document),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert {item["code"] for item in json.loads(result.stdout)["errors"]} == {
        "HELD_PATH_COLLISION"
    }
    assert {entry["path"] for entry in document["held_paths"]} == {
        held_path,
        declared_path,
    }


def test_intent_preflight_is_at_selected_batch_seam_and_keeps_lifecycle_out_of_scope() -> None:
    text = _text()
    parallelism_at = text.index("## Parallelism (read first)")
    preflight_at = text.index("### Exact selected-batch INTENT dispatch preflight")
    hard_caps_at = text.index("## Hard caps (token / wall-clock safety)")
    assert parallelism_at < preflight_at < hard_caps_at
    assert "**after** Rules 0-2 have produced the\nordered, conflict-deduplicated `SELECTED_BATCH_TASK_IDS`" in text
    assert "and immediately before\nRule 3 dispatches" in text
    assert "Do not reselect, widen, reorder, or merge partitions" in text
    assert "Never implement this response by changing\n`INTENT_PARALLEL_LEVELS`" in text
    assert "active-plan-registry.py\" list --json" in text
    assert "do not call `register`, `heartbeat`, `claim`, `release`, `wait-for`, `reap`" in text
    assert "full semantic reviewer and conditional aggregate-review decision remain\nauthoritative" in text


def test_runtime_inputs_reject_held_supervisor_and_all_frozen_exclusions(tmp_path: Path) -> None:
    held_document = _run_builder(
        tmp_path / "held",
        """## T007 — Supervisor helper `[ ]`\n**Files:** scripts/supervisor/session.py\n**Complexity:** high\n""",
        {"nodes": [{"id": "T007", "status": "ready", "depends_on": []}]},
        "T007",
        leases=[_live_lease("peer-run", "scripts/supervisor/session.py")],
    )
    held_result = subprocess.run(
        [sys.executable, str(PREFLIGHT)],
        input=json.dumps(held_document),
        text=True,
        capture_output=True,
        check=False,
    )
    assert held_result.returncode == 1
    assert "HELD_PATH_COLLISION" in {item["code"] for item in json.loads(held_result.stdout)["errors"]}

    excluded_cases = [
        "runtime/watchdog/poll.py",
        "tests/test_watchdog_poll.py",
        "tests/fixtures/watchdog/codex/token_count_nominal.json",
        "skills/z-plan/SKILL.md",
        "skills/z-plan-split/SKILL.md",
        "tests/test_z_plan_markdown_contract.py",
    ]
    for index, excluded_path in enumerate(excluded_cases):
        case_dir = tmp_path / f"excluded-{index}"
        document = _run_builder(
            case_dir,
            f"## T008 — Excluded `[ ]`\n**Files:** {excluded_path}\n**Complexity:** low\n",
            {"nodes": [{"id": "T008", "status": "ready", "depends_on": []}]},
            "T008",
        )
        result = subprocess.run(
            [sys.executable, str(PREFLIGHT)],
            input=json.dumps(document),
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 1, excluded_path
        assert "HARD_EXCLUSION" in {
            item["code"] for item in json.loads(result.stdout)["errors"]
        }, excluded_path
