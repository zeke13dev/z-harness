from __future__ import annotations

import importlib.util
import json
import subprocess

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
Z_EXECUTE_SKILL = REPO_ROOT / "skills" / "z-execute" / "SKILL.md"
IMPLEMENTER = REPO_ROOT / "agents" / "implementer.md"
REVIEWER = REPO_ROOT / "agents" / "reviewer.md"
INTENT_SCHEMA = REPO_ROOT / "scripts" / "intent-schema.py"
TASK_TREE_GENERATOR = REPO_ROOT / "agents" / "task-tree-generator.md"


def intent_schema_module():
    spec = importlib.util.spec_from_file_location("intent_schema", INTENT_SCHEMA)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def done_tasks(count: int, *, criterion: int = 1) -> str:
    blocks = []
    for idx in range(1, count + 1):
        task_id = f"T{idx:03d}"
        blocks.append(
            f"## {task_id} — Task {idx} `[x]`\n"
            "**Depends on:** —\n"
            f"**Advances:** criterion #{criterion}\n"
            "**Acceptance:** done\n"
        )
    return "\n".join(blocks)


def execution_strategy(path: Path, text: str = "# Execution strategy\n\n## Source of truth\n\n- workstreams.json is validated.\n") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_execute_intent_mode_passes_conversation_artifacts() -> None:
    skill = text(Z_EXECUTE_SKILL)

    assert "approved concern flags, optional audit notes, task-to-intent mapping, and execution strategy metadata" in skill
    assert "brainstorm choice" in skill
    assert "INTENT_FLAGS_FILE" in skill
    assert "BRAINSTORM_CHOICE_FILE" in skill
    assert "EXECUTION_STRATEGY_FILE" in skill
    assert "WORKSTREAMS_FILE" in skill
    assert "intent_flags_path: ${INTENT_FLAGS_FILE}" in skill
    assert "execution_strategy_path: ${EXECUTION_STRATEGY_FILE}" in skill
    assert "workstreams_path: ${WORKSTREAMS_FILE}" in skill


def test_execute_bfs_generator_receives_intent_artifacts() -> None:
    skill = text(Z_EXECUTE_SKILL)
    dispatch = skill.split('description="Generate BFS level ${CURRENT_LEVEL} task batch"', 1)[1]
    dispatch = dispatch.split('    ))"', 1)[0]

    for prompt_line in (
        "intent_readthrough_flags_path: ${INTENT_FLAGS_FILE}",
        "brainstorm_choice_path: ${BRAINSTORM_CHOICE_FILE}",
        "execution_strategy_path: ${EXECUTION_STRATEGY_FILE}",
        "workstreams_path: ${WORKSTREAMS_FILE}",
        "execution_strategy_required: true",
        "task_to_intent_mapping_required: true",
    ):
        assert prompt_line in dispatch


def test_execute_intent_parallel_unknown_scope_serializes() -> None:
    skill = text(Z_EXECUTE_SKILL)
    parallelism = skill.split("## Parallelism (read first)", 1)[1]
    rule_zero = parallelism.split("1. **Eligibility.**", 1)[0]

    assert "same-level batching is default-on only after these safety checks pass" in rule_zero
    assert "Every sibling task block in the current level has a parseable precise `**Files:**` scope" in rule_zero
    assert "Missing or unparseable scope serializes the affected INTENT level" in rule_zero
    assert "`scope_unknown: true` serializes the affected INTENT level" in rule_zero
    assert "restrict rule 1's eligibility set to a **single** task" in rule_zero
    assert "Serialized fallback paths, including unknown-scope serialization" in rule_zero
    assert "INTENT_RULE0_SAFETY_PASSED=0" in rule_zero
    assert "INTENT_PARALLEL_BATCH_ACTIVE=0" in rule_zero


def test_execute_intent_parallel_fanout_is_bounded() -> None:
    skill = text(Z_EXECUTE_SKILL)

    assert "INTENT_PARALLEL_FANOUT_LIMIT=3" in skill
    assert "partition them into chunks of at most this many task tracks" in skill
    assert "The dispatch set is capped or partitioned by `$INTENT_PARALLEL_FANOUT_LIMIT`" in skill
    assert "do not launch an unbounded same-level batch" in skill


def test_execute_intent_parallel_review_diff_isolation() -> None:
    skill = text(Z_EXECUTE_SKILL)
    diff_capture = skill.split("### 6. Capture diff and spawn reviewer", 1)[1]
    diff_capture = diff_capture.split("**Skip-rereview on clean cycle-1.**", 1)[0]

    assert "INTENT parallel review-diff isolation" in diff_capture
    assert "never capture a combined dirty-tree diff" in diff_capture
    assert 'if [ "${INTENT_RULE0_SAFETY_PASSED:-0}" -eq 1 ] && [ "${INTENT_PARALLEL_BATCH_ACTIVE:-0}" -eq 1 ]; then' in diff_capture
    assert 'if [ "${LEVEL_EXECUTE_ACTIVE:-0}" -eq 1 ] && [ "${INTENT_PARALLEL_LEVELS:-false}" = "true" ]; then' not in diff_capture
    assert "actual INTENT parallel" in diff_capture
    assert "TASK_DIFF_PATHS=(<paths parsed from this task block's **Files:** line>)" in diff_capture
    assert 'git diff -- "${TASK_DIFF_PATHS[@]}"' in diff_capture
    assert "Serialized review/full diff capture" in diff_capture
    assert "unknown-scope serialization" in diff_capture
    assert "per-task path-filtered diff capture" in diff_capture
    assert "INTENT_RULE0_SAFETY_PASSED=1" in diff_capture
    assert "INTENT_PARALLEL_BATCH_ACTIVE=1" in diff_capture
    assert "serialize review capture inside the parallel level" in diff_capture


def test_implementer_and_reviewer_respect_intent_artifacts() -> None:
    implementer = text(IMPLEMENTER)
    reviewer = text(REVIEWER)

    for artifact_line in ("intent_flags_path:", "execution_strategy_path:", "workstreams_path:"):
        assert artifact_line in implementer
        assert artifact_line in reviewer

    assert "must not expand scope beyond INTENT" in implementer
    assert "STOP and return `status: \"decision_needed\"`" in implementer
    assert "ignores a flagged decision, expands beyond INTENT" in reviewer


def test_task_tree_generator_emits_execution_strategy_metadata() -> None:
    generator = text(TASK_TREE_GENERATOR)

    assert "intent_readthrough_flags_path" in generator
    assert "brainstorm_choice_path" in generator
    assert "execution_strategy_path" in generator
    assert "workstreams_path" in generator
    assert "execution_strategy_required" in generator
    assert "task_to_intent_mapping_required" in generator
    assert "**Execution strategy:**" in generator
    assert "**Review gates:**" in generator
    assert "**Workstreams:**" in generator


def test_task_tree_generator_pipelined_scheduler_requires_precise_bounded_tracks() -> None:
    generator = text(TASK_TREE_GENERATOR)
    size_rule = generator.split("### Size rule", 1)[1]
    size_rule = size_rule.split("### Deferral rule", 1)[0]

    assert "Default healthy level batch is 3–8 tasks" in size_rule
    assert "Wider same-level batches are allowed only for pipelined task-track scheduling" in size_rule
    assert "every sibling has a precise, parseable `**Files:**` scope" in size_rule
    assert "every sibling's `**Files:**` set is disjoint from every other sibling's `**Files:**` set" in size_rule
    assert "partitioned into bounded task tracks/workstreams" in size_rule
    assert "append-only/non-conflicting overlap exception is not enough for wider pipelined batches" in size_rule
    assert "MUST NOT mean the executor launches every sibling at once" in size_rule
    assert "actual dispatch remains capped by the executor's fan-out window" in size_rule
    assert "If dependencies are uncertain" in size_rule
    assert "missing `**Files:**`" in size_rule
    assert "any sibling `**Files:**` entries overlap" in size_rule
    assert "unbounded fan-out" in size_rule
    assert "Defer dependent or overlapping work to the next level" in size_rule
    assert "partition it into a smaller bounded level with disjoint file scopes" in size_rule
    assert "serialize the risky work" in size_rule
    assert "More than 10 tasks in one level is acceptable only under the proven safe wider-batch conditions above" in size_rule
    assert "independent from every other sibling under the Independence rule" not in size_rule
    assert "sibling overlap is not provably append-only/non-conflicting" not in size_rule
    assert "10-20" not in generator
    assert "10–20" not in generator


def test_execute_aggregate_review_gate_contract_is_conditional() -> None:
    skill = text(Z_EXECUTE_SKILL)

    assert "aggregate-review-gate" in skill
    assert "aggregate-review-required | aggregate-review-not-required" in skill
    assert "aggregate_review_decision" in skill
    assert "aggregate_review_required" in skill
    assert "aggregate_review_not_required" in skill
    assert "aggregate-review-decision.json" in skill
    assert "more than 8 realized implementation tasks" in skill
    assert "more than 1 workstream OR more than 1 parallel batch" in skill
    assert "any high-risk concern/audit flag" in skill
    assert "any acceptance criterion mapped to multiple workstreams" in skill
    assert 'elif [ "${IMPLEMENT_MODE:-}" = "intent" ]; then' in skill
    assert 'NEXT_CMD="none"' in skill
    assert 'NEXT_LABEL="Run /z-review-all for final-gate cross-LLM review"' in skill
    assert "Legacy completed runs keep the historical `/z-review-all`" in skill
    finalize = skill.split("## Finalize", 1)[1]
    assert "No-deviations ledger baseline" in finalize
    assert "before the aggregate-review gate decides whether `/z-review-all` is required" in finalize
    assert "handed to `/z-review-all`" not in finalize
    assert "### Review-all handoff" not in finalize


def test_execute_finalize_writes_outcome_before_next() -> None:
    skill = text(Z_EXECUTE_SKILL)
    finalize = skill.split("## Finalize", 1)[1]
    setup = finalize.split("<!-- include: _fragments/run-brief-finalize.md -->", 1)[0]

    outcome_idx = setup.index('set-section --run "$RUN" --section outcome --value "$OUTCOME"')
    next_idx = setup.index('set-section --run "$RUN" --section next --json "$NEXT_JSON"')
    aggregate_idx = setup.index("aggregate-review-gate")

    assert 'OUTCOME="${RUN_BRIEF_OUTCOME:-Halted: orchestration stopped with ${BLOCKED_COUNT} blocked, ${PENDING_COUNT} pending}"' in setup
    assert 'OUTCOME="Orchestration complete: ${DONE_COUNT} done, ${SKIP_COUNT} skipped, ${BLOCKED_COUNT} blocked."' in setup
    assert aggregate_idx < outcome_idx < next_idx


def test_aggregate_review_gate_triggers_on_thresholds(tmp_path) -> None:
    module = intent_schema_module()
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(done_tasks(9, criterion=1), encoding="utf-8")
    workstreams = tmp_path / "workstreams.json"
    workstreams.write_text(
        json.dumps(
            {
                "workstreams": [
                    {
                        "id": "ws-1",
                        "status": "ready",
                        "tasks": [f"T{idx:03d}" for idx in range(1, 6)],
                        "parallel_group": "level-0",
                    },
                    {
                        "id": "ws-2",
                        "status": "ready",
                        "tasks": [f"T{idx:03d}" for idx in range(6, 10)],
                        "parallel_group": "level-1",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    flags = tmp_path / "intent-readthrough-flags.md"
    flags.write_text("- concern: high-risk audit flag around shared executor state\n", encoding="utf-8")

    decision = module.compute_aggregate_review_gate(tasks, workstreams, flags, execution_strategy(tmp_path / "execution-strategy.md"))

    assert decision.required is True
    assert decision.decision == "aggregate-review-required"
    assert decision.triggers["task_count_gt_8"] is True
    assert decision.triggers["workstream_count_gt_1"] is True
    assert decision.triggers["parallel_batch_count_gt_1"] is True
    assert decision.triggers["high_risk_flag"] is True
    assert decision.triggers["criteria_mapped_to_multiple_workstreams"] is True
    assert decision.criteria_multi_workstream == {"1": ["ws-1", "ws-2"]}


def test_aggregate_review_gate_records_no_trigger_path(tmp_path) -> None:
    module = intent_schema_module()
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(done_tasks(8, criterion=1), encoding="utf-8")
    workstreams = tmp_path / "workstreams.json"
    workstreams.write_text(
        json.dumps(
            {
                "workstreams": [
                    {
                        "id": "ws-1",
                        "status": "ready",
                        "tasks": [f"T{idx:03d}" for idx in range(1, 9)],
                        "parallel_group": "level-0",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    flags = tmp_path / "intent-readthrough-flags.md"
    flags.write_text("- no high-risk concern or audit flag\n", encoding="utf-8")

    decision = module.compute_aggregate_review_gate(tasks, workstreams, flags, execution_strategy(tmp_path / "execution-strategy.md"))

    assert decision.required is False
    assert decision.decision == "aggregate-review-not-required"
    assert decision.task_count == 8
    assert decision.workstream_count == 1
    assert decision.parallel_batch_count == 1
    assert decision.high_risk_flag is False

    cli = subprocess.run(
        [
            "python3",
            str(INTENT_SCHEMA),
            "aggregate-review-gate",
            str(tasks),
            str(workstreams),
            str(flags),
            str(execution_strategy(tmp_path / "execution-strategy-cli.md")),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(cli.stdout)
    assert payload["decision"] == "aggregate-review-not-required"
    assert payload["required"] is False
    assert decision.criteria_multi_workstream == {}
    assert not any(decision.triggers.values())


def test_aggregate_review_gate_fails_closed_on_missing_metadata(tmp_path) -> None:
    module = intent_schema_module()
    tasks = tmp_path / "TASKS.md"
    tasks.write_text(done_tasks(2, criterion=1), encoding="utf-8")

    decision = module.compute_aggregate_review_gate(tasks, tmp_path / "missing-workstreams.json", None, tmp_path / "missing-strategy.md")

    assert decision.required is True
    assert decision.decision == "aggregate-review-required"
    assert decision.triggers["metadata_missing_or_invalid"] is True
    assert decision.metadata_fail_reasons == ["workstreams_missing", "execution_strategy_missing"]

    invalid_workstreams = tmp_path / "invalid-workstreams.json"
    invalid_workstreams.write_text("{not json", encoding="utf-8")
    valid_strategy = execution_strategy(tmp_path / "execution-strategy.md")

    invalid_decision = module.compute_aggregate_review_gate(tasks, invalid_workstreams, None, valid_strategy)

    assert invalid_decision.required is True
    assert invalid_decision.triggers["metadata_missing_or_invalid"] is True
    assert invalid_decision.metadata_fail_reasons == ["workstreams_invalid_json"]

    partial_workstreams = tmp_path / "partial-workstreams.json"
    partial_workstreams.write_text(
        json.dumps({"workstreams": [{"id": "ws-1", "status": "ready", "tasks": ["T001"]}]}),
        encoding="utf-8",
    )
    empty_strategy = execution_strategy(tmp_path / "empty-strategy.md", "")

    incomplete_decision = module.compute_aggregate_review_gate(tasks, partial_workstreams, None, empty_strategy)

    assert incomplete_decision.required is True
    assert incomplete_decision.triggers["metadata_missing_or_invalid"] is True
    assert incomplete_decision.metadata_fail_reasons == [
        "execution_strategy_empty",
        "workstreams_missing_task_mapping",
    ]

    cli = subprocess.run(
        [
            "python3",
            str(INTENT_SCHEMA),
            "aggregate-review-gate",
            str(tasks),
            "-",
            "-",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(cli.stdout)
    assert payload["decision"] == "aggregate-review-required"
    assert payload["required"] is True
    assert payload["triggers"]["metadata_missing_or_invalid"] is True


def test_execute_intent_artifacts_do_not_use_latest_archive_scan() -> None:
    skill = text(Z_EXECUTE_SKILL)
    artifact_block = skill.split("# Intent-conversation companion artifacts from /z-plan.", 1)[1]
    artifact_block = artifact_block.split("# -----------------------------------------------------------------------", 1)[0]

    assert 'find "$BASE/archive"' not in artifact_block
    assert "tail -1" not in artifact_block
    assert "exact pointers in handoff.json/execution-strategy.md" in artifact_block
    assert "_resolve_exact_plan_artifact" in artifact_block
