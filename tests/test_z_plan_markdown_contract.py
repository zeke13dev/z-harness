from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
Z_PLAN_SKILL = REPO_ROOT / "skills" / "z-plan" / "SKILL.md"
CONSULTANT_PRIMARY = REPO_ROOT / "agents" / "consultant-primary.md"
CONSULTANT_SECONDARY = REPO_ROOT / "agents" / "consultant-secondary.md"
GENERATE_WORKSTREAMS = REPO_ROOT / "scripts" / "generate-workstreams.py"


def skill_text() -> str:
    return Z_PLAN_SKILL.read_text(encoding="utf-8")


def index_after(text: str, needle: str, start: int = 0) -> int:
    idx = text.find(needle, start)
    assert idx != -1, f"missing marker {needle!r}"
    return idx


def test_mode_gate_precedes_hard_cost_gate() -> None:
    text = skill_text()

    mode_gate = index_after(text, "## Explicit planning mode gate (before hard cost gate)")
    visible_choice = index_after(text, "**Visible planning-mode choice.**", mode_gate)
    cost_gate = index_after(text, "## Pre-subagent cost gate (hard)")

    assert mode_gate < visible_choice < cost_gate
    assert "Intent-vs-Full SDD mode choice before the hard cost gate" in text[mode_gate:cost_gate]
    assert "SPEC.md" in text[mode_gate:cost_gate]
    assert "legacy_spec" in text[mode_gate:cost_gate]


def test_planning_mode_chosen_telemetry_is_documented_and_emitted_before_cost_event() -> None:
    text = skill_text()

    mode_event = index_after(text, 'log-event.sh" "$RUN" planning_mode_chosen')
    cost_event = index_after(text, "cost_gate_decision", mode_event)
    mode_block = text[index_after(text, "**Visible planning-mode choice.**"):cost_event]

    assert mode_event < cost_event
    assert "mandatory and is emitted exactly once per run" in mode_block
    for field in ("mode", "choice", "recommended_mode", "source", "reason", "legacy_spec_forced"):
        assert f'"{field}"' in mode_block
    assert 'PLANNING_MODE_CHOICE="$(AskUserQuestion' in mode_block
    assert 'PLANNING_MODE_CHOICE="${PLANNING_MODE_CHOICE%% — *}"' in mode_block
    assert 'case "$PLANNING_MODE_CHOICE" in' in mode_block
    assert 'intent) PLANNING_MODE="intent"' in mode_block
    assert 'full) PLANNING_MODE="full"' in mode_block
    assert "unattended/no-ask config default from workflow.planning_mode or CLI flag" in mode_block


def test_plan_route_check_uses_amended_signal_names() -> None:
    text = skill_text()

    route_check = index_after(text, "## Plan Route Check")
    signal_start = index_after(text, "Use only already-known signals:", route_check)
    signal_end = index_after(text, "and artifact existence.", signal_start)
    signal_list = text[signal_start:signal_end]

    for signal in (
        "`plan_validation_intent`",
        "`question_heavy_artifacts`",
        "`artifact_unsettled_approach`",
        "`post_artifact_check`",
        "`asks_what_should_we_do`",
        "`alternatives_unsettled`",
        "`architecture_decision`",
        "`reversibility_uncertain`",
    ):
        assert signal in signal_list
    stale_signals = (
        "`plan_validation_" + "requested`",
        "`question_heavy_" + "artifact`",
        "`unsettled_approach_" + "signal`",
    )
    for stale_signal in stale_signals:
        assert stale_signal not in signal_list



def test_plan_route_check_signal_list_matches_planning_router_subset() -> None:
    text = skill_text()
    router_text = (REPO_ROOT / "agents" / "planning-router.md").read_text(encoding="utf-8")

    route_check = index_after(text, "## Plan Route Check")
    signal_start = index_after(text, "Use only already-known signals:", route_check)
    signal_end = index_after(text, "and artifact existence.", signal_start)
    z_plan_signals = set()
    for token in text[signal_start:signal_end].split("`")[1::2]:
        if token and not token.startswith("/"):
            z_plan_signals.add(token)

    router_signal_start = index_after(router_text, "## Expected Signals")
    router_signal_end = index_after(router_text, "## Decision Rules", router_signal_start)
    router_signals = {
        line.split("`", 2)[1]
        for line in router_text[router_signal_start:router_signal_end].splitlines()
        if line.startswith("- `")
    }
    expected_shared = {
        "plan_validation_intent",
        "question_heavy_artifacts",
        "artifact_unsettled_approach",
        "post_artifact_check",
        "asks_what_should_we_do",
        "alternatives_unsettled",
        "architecture_decision",
        "reversibility_uncertain",
    }

    assert expected_shared <= z_plan_signals
    assert expected_shared <= router_signals


def test_phase84_route_chain_example_uses_object_entries() -> None:
    text = skill_text()
    phase84 = index_after(text, "## Phase 8.4 — Post-artifact route check")
    phase85 = index_after(text, "## Phase 8.5 — Handoff context producer", phase84)
    block = text[phase84:phase85]

    assert '"route_chain": ["/z-plan"]' not in block
    assert '"from_command": "/z-plan"' in block
    assert '"to_command": "/z-sharpen"' in block
    assert '"reason_codes": ["question_heavy_artifacts", "post_artifact_check"]' in block


def test_phase85_calls_handoff_producer_before_phase86() -> None:
    text = skill_text()
    phase85 = index_after(text, "## Phase 8.5 — Handoff context producer")
    producer = index_after(text, "scripts/write-handoff.sh", phase85)
    validate = index_after(text, "handoff_json_validated", producer)
    phase86 = index_after(text, "## Phase 8.6 — Final handoff gate", validate)
    spine = text[
        index_after(text, "## Intent-compiler phase spine"):
        index_after(text, "## Setup")
    ]

    assert "10. **Watcher checkpoint seam**" in spine
    assert "Phase 8.5" not in spine
    assert phase85 < producer < validate < phase86
    phase85_block = text[phase85:phase86]
    for override in (
        "Z_HARNESS_HANDOFF_STATUS",
        "Z_HARNESS_HANDOFF_NEXT_STEP",
        "Z_HARNESS_AGENT",
    ):
        assert override in phase85_block
    assert "HANDOFF_PRODUCER_RC" in phase85_block
    assert "handoff.json" in phase85_block


def test_handoff_template_has_executor_context_categories_and_neutral_next_move() -> None:
    text = skill_text()
    phase85 = index_after(text, "## Phase 8.5 — Handoff context producer")
    phase86 = index_after(text, "## Phase 8.6 — Final handoff gate", phase85)
    block = text[phase85:phase86]

    for heading in (
        "## Invariants",
        "## Rejected approaches",
        "## Decisions archive",
        "## Verification commands",
    ):
        assert heading in block
    next_move = block[index_after(block, "## Next move"):]
    assert "/z-audit-plan <$Z_HARNESS_SLUG>" not in next_move
    assert "Do not hard-code an audit-first recommendation" in next_move

def test_post_artifact_route_check_fires_after_tasks_and_before_handoff() -> None:
    text = skill_text()

    phase8 = index_after(text, "## Phase 8 — TASKS.md")
    post_route = index_after(text, "## Phase 8.4 — Post-artifact route check", phase8)
    handoff = index_after(text, "## Phase 8.5 — Handoff context producer", post_route)
    final_gate = index_after(text, "## Phase 8.6 — Final handoff gate", handoff)

    assert phase8 < post_route < handoff < final_gate
    block = text[post_route:handoff]
    assert 'route_class: "post_artifact"' in block
    assert '"route_class": "post_artifact"' in block
    assert '"reason_codes": ["question_heavy_artifacts", "post_artifact_check"]' in block
    for signal in (
        '"plan_validation_intent"',
        '"question_heavy_artifacts"',
        '"artifact_unsettled_approach"',
        '"post_artifact_check"',
    ):
        assert signal in block
    assert "/z-plan-split" in block
    assert "/z-sharpen" in block
    assert "/z-brainstorm" in block
    assert "legacy `SPEC.md` + `PLAN.md` + `TASKS.md`" in block
    assert "intent `INTENT.md` + canonical `TASKS.md`" in block


def test_final_handoff_gate_ordering_and_resume_map() -> None:
    text = skill_text()

    phase8 = index_after(text, "## Phase 8 — TASKS.md")
    post_route = index_after(text, "## Phase 8.4 — Post-artifact route check", phase8)
    handoff = index_after(text, "## Phase 8.5 — Handoff context producer", post_route)
    handoff_written = index_after(text, "handoff_written", handoff)
    final_gate = index_after(text, "## Phase 8.6 — Final handoff gate", handoff_written)
    phase9 = index_after(text, "## Phase 9 — Finalize archive", final_gate)

    assert phase8 < post_route < handoff < handoff_written < final_gate < phase9
    block = text[final_gate:phase9]
    for option in (
        "Fresh-session implementation",
        "Audit first",
        "Stop with handoff",
        "Amend",
    ):
        assert option in block
    assert "scope/goal changes resume at Phase 0" in block
    assert "decision changes resume at Phase 2" in block
    assert "primary artifact wording changes resume at Phase 6" in block
    assert "task decomposition changes resume at Phase 8" in block
    assert "phase_8_6_final_handoff_gate" in block
    capture = index_after(block, 'FINAL_HANDOFF_CHOICE="$(AskUserQuestion')
    normalize = index_after(block, 'FINAL_HANDOFF_CHOICE="${FINAL_HANDOFF_CHOICE%% — *}"', capture)
    export_choice = index_after(block, "export FINAL_HANDOFF_CHOICE", normalize)
    validation_case = index_after(block, 'case "$FINAL_HANDOFF_CHOICE" in', export_choice)
    log_choice = index_after(block, 'log-event.sh" "$RUN" next_step_choice', validation_case)
    next_json_case = index_after(block, 'case "$FINAL_HANDOFF_CHOICE" in', log_choice)
    assert capture < normalize < export_choice < validation_case < log_choice < next_json_case
    for machine_option in (
        "fresh_session_implementation",
        "audit_first",
        "stop_with_handoff",
        "amend",
    ):
        assert machine_option in block


def test_intent_compiler_spine_documents_new_default_flow() -> None:
    text = skill_text()
    spine = text[
        index_after(text, "## Intent-compiler phase spine"):
        index_after(text, "## Setup")
    ]

    assert "conversation → sharpened problem → optional ideated framing → intent contract → execution DAG" in spine
    assert "Sharpen always first" in spine
    assert "Brainstorm ask gate" in spine
    assert "never auto-dispatch" in spine
    assert "Conversational plan + `INTENT.md` iterations" in spine
    assert "LLM concern flags + optional audit-plan ask" in spine
    assert "Execution strategy generation" in spine
    assert "Watcher checkpoint seam" in spine


def test_phase7_final_review_inputs_are_mode_aware_for_intent_and_full() -> None:
    text = skill_text()

    phase7 = index_after(text, "## Phase 7 — Bundled final review")
    phase8 = index_after(text, "## Phase 8 — TASKS.md", phase7)
    block = text[phase7:phase8]
    phase6 = index_after(text, "## Phase 6")
    phase6_block = text[phase6:phase7]
    assert "Create the initial legacy `$Z_HARNESS_PLAN_DIR/TASKS.md`" in phase6_block

    assert "**Phase 7 mode-aware input contract.**" in block
    assert "planning_mode: $PLANNING_MODE" in block
    assert "`INTENT.md` + `TASKS.md` + decisions" in block
    assert "`SPEC.md` + `PLAN.md` + `TASKS.md` + decisions" in block
    assert "intent_path: $Z_HARNESS_PLAN_DIR/INTENT.md" in block
    assert "spec_path: $Z_HARNESS_PLAN_DIR/SPEC.md" in block
    assert "plan_path: $Z_HARNESS_PLAN_DIR/PLAN.md" in block
    assert "tasks_path: $Z_HARNESS_PLAN_DIR/TASKS.md" in block
    assert "decisions_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md" in block
    assert "PHASE7_MODE_AWARE_INPUT_BLOCK" in block
    guard = index_after(block, "**Pre-dispatch TASKS existence/generation guard.**")
    rendered_input = index_after(block, "PHASE7_MODE_AWARE_INPUT_BLOCK", guard)
    assert guard < rendered_input
    first_tasks_path = index_after(block, "tasks_path: $Z_HARNESS_PLAN_DIR/TASKS.md")
    assert guard < first_tasks_path
    guard_block = block[guard:rendered_input]
    assert 'PHASE7_TASKS_PATH="$Z_HARNESS_PLAN_DIR/TASKS.md"' in guard_block
    assert 'PHASE7_TASKS_STALE_REASON=' in guard_block
    assert 'stale_reason:' in guard_block
    assert 'if [[ ! -f "$PHASE7_TASKS_PATH" || "$PHASE7_TASKS_STALE_REASON" == "amended-intent" ]]' in guard_block
    assert 'subagent_type="task-tree-generator"' in guard_block
    assert "full_mode_tasks_missing_before_phase7" in guard_block
    phase8_4 = index_after(text, "## Phase 8.4 — Post-artifact route check", phase8)
    phase8_block = text[phase8:phase8_4]
    assert "Phase 8 does not create the first TASKS.md" in phase8_block
    assert 'subagent_type="task-tree-generator"' not in phase8_block
    phase7_prompt_lines = [line for line in block.splitlines() if 'prompt="' in line and "Critique this plan" in line]
    assert len(phase7_prompt_lines) == 7
    for line in phase7_prompt_lines:
        assert "$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE" in line
    consultant_prompt_lines = [line for line in phase7_prompt_lines if "consultant-" in line]
    assert len(consultant_prompt_lines) == 2
    for line in consultant_prompt_lines:
        assert "MODE: plan-review" in line
    assert "Do **not** ask for or synthesize `SPEC.md`/`PLAN.md` in intent mode." in block
    assert "handed the full SPEC.md + PLAN.md" not in block
    assert "each handed the full SPEC.md + PLAN.md" not in block


def test_consultant_plan_review_contract_is_mode_aware() -> None:
    for path in (CONSULTANT_PRIMARY, CONSULTANT_SECONDARY):
        text = path.read_text(encoding="utf-8")
        assert "mode-aware final plan review" in text
        assert "intent-mode or full-mode plan artifacts" in text
        modes = text[index_after(text, "## Modes"):index_after(text, "## Building the prompt to the provider")]
        plan_review = modes[
            index_after(modes, "- **`plan-review`**"):
            index_after(modes, "- **`light-fix`**")
        ]
        prompt_contract = text[
            index_after(text, "## Building the prompt to the provider"):
            index_after(text, "## Returning to the caller")
        ]

        assert "`planning_mode` and concrete artifact paths" in plan_review
        assert "caller hands you mode-aware final-review inputs" in plan_review
        assert "intent mode, read `INTENT.md` + `TASKS.md` + decisions" in plan_review
        assert "full mode, read `SPEC.md` + `PLAN.md` + `TASKS.md` + decisions" in plan_review
        assert "intent mode = INTENT.md + TASKS.md + decisions" in prompt_contract
        assert "full mode = SPEC.md + PLAN.md + TASKS.md + decisions" in prompt_contract
        assert "caller hands you SPEC.md + PLAN.md" not in plan_review


def test_intent_compiler_sharpen_brainstorm_and_checkpoint_gates() -> None:
    text = skill_text()

    sharpen = index_after(text, "### 0-sharpen. Mandatory conversational sharpen")
    brainstorm = index_after(text, "### 0.5 Brainstorm ask gate (no auto-route)", sharpen)
    checkpoint = index_after(text, "### 0.6 Planning-entry watcher checkpoint seam", brainstorm)
    premise = index_after(text, "**Do not take the prompt's premises for granted.**", checkpoint)

    assert sharpen < brainstorm < checkpoint < premise
    block = text[sharpen:premise]
    assert "shared `/z-sharpen` inline component contract" in block
    assert "MUST NOT depend on `/z-sharpen` wrapper-only behavior" in block
    assert "does not auto-dispatch `/z-brainstorm`" in block
    assert "brainstorm-choice.json" in block
    assert "scripts/check-compaction.sh" in block
    assert "scripts/write-clear-checkpoint.sh" in block
    route_check = text[index_after(text, "## Plan Route Check"):index_after(text, "## Explicit planning mode gate")]
    assert "pre-Phase-0/pre-gate invocation MUST NOT route or recommend `/z-brainstorm`" in route_check
    assert "brainstorm_recommendation_deferred_until_after_sharpen" in route_check
    assert "only in Phase 0.5 or later" in route_check


def test_intent_readthrough_flags_precede_final_approval() -> None:
    text = skill_text()

    phase5 = index_after(text, "## Phase 5 — Present + approve")
    phase6 = index_after(text, "## Phase 6 — Write SPEC.md", phase5)
    block = text[phase5:phase6]

    assert "bounded 1–2 pass iteration loop" in block
    assert "LLM concern/decision flagging pass" in block
    assert "intent-readthrough-flags.md" in block
    assert "ask whether to fold in an audit-plan scan" in block
    assert "not an automatic `/z-audit-plan` handoff" in block
    assert "single prose plan brief" in block
    assert "Read-through flags" in block
    assert "Do not leave these only on disk" in block
    assert "Grill the draft" in block
    assert "post-draft grill loop" in block
    assert "post-draft-grill.md" in block
    assert "must not create a separate popup per shortcut" in block
    assert "category=shortcut" in block
    assert "Reject shortcut(s); use robust alternative(s)" in block
    assert "do not spawn a separate popup per shortcut" in block
    assert "surface each post-draft grill question" in block
    assert 'source: "intent-readthrough-flags"' in block
    assert "transcript_path" in block
    assert "Use `AskUserQuestion` for explicit approval on each major design decision" not in block
    assert "surface this shortcut approval question" not in block
    assert "Block until all design decisions and all shortcut records are answered" not in block


def test_execution_strategy_and_pre_execute_checkpoint_are_documented() -> None:
    text = skill_text()

    phase8 = index_after(text, "## Phase 8 — TASKS.md")
    phase85 = index_after(text, "## Phase 8.5 — Handoff context producer", phase8)
    phase86 = index_after(text, "## Phase 8.6 — Final handoff gate", phase85)
    phase8_block = text[phase8:phase85]
    handoff_block = text[phase85:phase86]

    assert "execution-strategy.md" in phase8_block
    assert "task-to-intent mapping" in text
    assert "Review gates" in phase8_block
    assert "load-bearing execution-strategy data, not an optional Hermes nicety" in phase8_block
    assert "derived from TASKS.md + validated workstreams.json" in phase8_block
    assert "derived_from_tasks" in phase8_block
    assert "workstreams_validated" in phase8_block
    assert "phase8_workstreams_generation_failed" in phase8_block
    assert "phase8_workstreams_validation_failed" in phase8_block
    assert "phase8_execution_strategy_failed" in phase8_block
    execution_strategy_start = index_after(phase8_block, 'EXECUTION_STRATEGY_OUT="$(python3 -')
    execution_strategy_block = phase8_block[
        execution_strategy_start:
        index_after(phase8_block, "\nPYEOF", execution_strategy_start)
    ]
    broad_catch = "except " + "Exception"
    assert broad_catch not in execution_strategy_block
    assert "except (OSError, json.JSONDecodeError)" in execution_strategy_block
    assert "except OSError as exc" in execution_strategy_block
    assert "TASKS.md unreadable while writing execution strategy" in execution_strategy_block
    assert "cannot write execution-strategy.md" in execution_strategy_block
    assert "### Pre-execute watcher checkpoint seam" in handoff_block
    assert "Z_HARNESS_CHECKPOINT_PHASE_ID=\"pre-execute-handoff\"" in handoff_block
    assert "scripts/check-compaction.sh" in handoff_block
    assert "scripts/write-clear-checkpoint.sh" in handoff_block


def test_intent_phase8_workstreams_generation_is_not_silent() -> None:
    text = skill_text()
    phase8 = index_after(text, "## Phase 8 — TASKS.md")
    legacy = index_after(text, "**Legacy path (planning_mode=full", phase8)
    intent_block = text[phase8:legacy]

    assert 'WORKSTREAMS_FILE="$Z_HARNESS_PLAN_DIR/workstreams.json"' in intent_block
    assert "WORKSTREAM_GEN_RC=$?" in intent_block
    assert "phase8_workstreams_generation_failed" in intent_block
    assert "phase8_workstreams_validation_failed" in intent_block
    assert "phase8_execution_strategy_failed" in intent_block
    assert "workstreams must be a non-empty list" in intent_block
    assert "merge_order must be a permutation of workstream ids" in intent_block
    assert "|| true" not in intent_block[
        index_after(intent_block, "scripts/generate-workstreams.py"):
        index_after(intent_block, "WORKSTREAM_GEN_RC=$?")
    ]
    assert "fall back to file-overlap dedup if workstreams.json is absent" not in intent_block


def test_generate_workstreams_flat_mode_surfaces_invalid_dag_inputs() -> None:
    script = GENERATE_WORKSTREAMS.read_text(encoding="utf-8")
    flat_block = script[
        index_after(script, "def build_from_flat"):
        index_after(script, "# ---------------------------------------------------------------------------\n# Main")
    ]

    assert "TASKS.md contained no canonical task headings" in flat_block
    assert "except CycleError" not in flat_block
    assert "return [], [], [], True, False" not in flat_block
