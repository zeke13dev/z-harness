from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCOUT_SKILLS = {
    "/z-plan": "skills/z-plan/SKILL.md",
    "/z-brainstorm": "skills/z-brainstorm/SKILL.md",
    "/z-audit": "skills/z-audit/SKILL.md",
    "/z-audit-plan": "skills/z-audit-plan/SKILL.md",
    "/z-audit-plan-style": "skills/z-audit-plan-style/SKILL.md",
    "/z-debug": "skills/z-debug/SKILL.md",
    "/z-research": "skills/z-research/SKILL.md",
    "/z-uplift": "skills/z-uplift/SKILL.md",
    "/z-plan-split": "skills/z-plan-split/SKILL.md",
}

FIRST_EXPENSIVE_BOUNDARY = {
    "/z-plan": "### Branch: `planning_mode=full`",
    "/z-brainstorm": "## Phase 0 — Scope probe",
    "/z-audit": "doc-fetcher` (Haiku) to get the concept list",
    "/z-audit-plan": "**Docs Grounding:**",
    "/z-audit-plan-style": "**Voice availability pre-check:**",
    "/z-debug": "## Auto-bail thresholds",
    "/z-research": "## Phase 1 — Subcommand dispatch",
    "/z-uplift": "## Phase 2 — Cross-cutting pass",
    "/z-plan-split": "## Phase 2 — Parallel cluster-planner dispatch",
}

HARD_GATE_MARKERS = {
    "/z-plan": "## Pre-subagent cost gate (hard)",
    "/z-research": "## Phase 0.5 — Cost gate",
    "/z-audit-plan-style": "**STYLE.md hard gate:**",
    "/z-uplift": "## STYLE.md gate",
    "/z-plan-split": "## Phase 1.5 — Pre-fanout cost gate",
}

REQUIRED_EVENTS = {
    "artifact_scout_inventory_complete",
    "artifact_scout_classified",
    "artifact_scout_warning",
    "artifact_scout_route",
}


def skill_text(command: str) -> str:
    return (REPO_ROOT / SCOUT_SKILLS[command]).read_text(encoding="utf-8")


def index_after(text: str, needle: str, start: int = 0) -> int:
    idx = text.find(needle, start)
    assert idx != -1, f"missing marker {needle!r}"
    return idx


def test_artifact_scout_hooks_exist_for_all_command_skills() -> None:
    for command in SCOUT_SKILLS:
        text = skill_text(command)
        assert "scripts/artifact-scout-inventory.py" in text, command
        assert "subagent_type=\"artifact-scout\"" in text, command
        assert "artifact-scout-inventory.json" in text, command
        assert "artifact-scout.md" in text, command
        missing = REQUIRED_EVENTS - set(e for e in REQUIRED_EVENTS if e in text)
        assert not missing, f"{command} missing events: {sorted(missing)}"


def test_inventory_event_payload_contract_is_standardized() -> None:
    required = {
        "source_status",
        "mandatory_candidate_count",
        "historical_candidate_count",
        "active_record_count",
        "worktree_count",
        "truncated",
    }
    for command in SCOUT_SKILLS:
        text = skill_text(command)
        missing = required - set(field for field in required if field in text)
        assert not missing, f"{command} missing inventory payload fields: {sorted(missing)}"


def test_z_plan_inventory_precedes_plan_route_check() -> None:
    text = skill_text("/z-plan")
    inventory_idx = index_after(text, "scripts/artifact-scout-inventory.py")
    route_check_idx = index_after(text, "## Plan Route Check")
    assert inventory_idx < route_check_idx


def test_artifact_scout_agent_blocks_use_runtime_gate_comment() -> None:
    for command in SCOUT_SKILLS:
        text = skill_text(command)
        classifier_idx = index_after(text, "subagent_type=\"artifact-scout\"")
        prelude = text[max(0, classifier_idx - 260):classifier_idx]
        assert "RUNTIME-GATE: subagent" in prelude, command
        assert "skip the Agent() call" in prelude, command


def test_inventory_and_classifier_precede_first_expensive_dispatch() -> None:
    for command, boundary in FIRST_EXPENSIVE_BOUNDARY.items():
        text = skill_text(command)
        inventory_idx = index_after(text, "scripts/artifact-scout-inventory.py")
        classifier_idx = index_after(text, "subagent_type=\"artifact-scout\"")
        boundary_idx = index_after(text, boundary, classifier_idx)
        assert inventory_idx < classifier_idx < boundary_idx, command


def test_hard_gated_commands_do_not_dispatch_scout_before_gate() -> None:
    for command, gate_marker in HARD_GATE_MARKERS.items():
        text = skill_text(command)
        gate_idx = index_after(text, gate_marker)
        classifier_idx = index_after(text, "subagent_type=\"artifact-scout\"")
        assert classifier_idx > gate_idx, command
        assert "subagent_type=\"artifact-scout\"" not in text[:gate_idx], command


def test_debug_inventory_precedes_soft_cost_estimate() -> None:
    text = skill_text("/z-debug")
    inventory_idx = index_after(text, "scripts/artifact-scout-inventory.py")
    soft_cost_idx = index_after(text, "**Soft cost estimate (non-blocking).**")
    assert inventory_idx < soft_cost_idx


def test_debug_similar_warns_but_exact_active_same_slug_asks() -> None:
    text = skill_text("/z-debug")
    assert "warning-only debug/similar path" in text
    assert "exact active same-slug debug run is not a similarity warning" in text
    assert "AskUser gate" in text


def test_inventory_runs_before_hard_cost_gates_when_split_from_classifier() -> None:
    for command in ("/z-plan", "/z-research", "/z-plan-split"):
        text = skill_text(command)
        inventory_idx = index_after(text, "scripts/artifact-scout-inventory.py")
        gate_idx = index_after(text, HARD_GATE_MARKERS[command])
        classifier_idx = index_after(text, "subagent_type=\"artifact-scout\"")
        assert inventory_idx < gate_idx < classifier_idx, command


def test_route_decision_boundary_is_warning_only_safe() -> None:
    for command in SCOUT_SKILLS:
        text = skill_text(command)
        assert "route_chain_effect: \"write_route_decision\"" in text, command
        assert "Warning-only" in text or "warning-only" in text, command
        assert "never writes `route-decision.md`" in text, command
        assert "never emits `artifact_scout_route`" in text, command
        assert "never advances `route_chain`" in text, command
        assert "emit `plan_route_decision`" in text, command


def test_audit_scope_from_children_inherit_parent_scout_context() -> None:
    text = skill_text("/z-audit")
    scope_idx = index_after(text, "## --scope-from flag handling")
    setup_idx = index_after(text, "## Setup")
    block = text[scope_idx:setup_idx]
    assert "ARTIFACT_SCOUT_SKIP_HISTORICAL_RESCAN=true" in block
    assert "MUST NOT run `scripts/artifact-scout-inventory.py`" in block
    assert "MUST NOT dispatch `artifact-scout`" in block
    assert "inherit" in block.lower()


def test_attend_is_wrapper_only_pass_through() -> None:
    text = (REPO_ROOT / "skills/z-attend/SKILL.md").read_text(encoding="utf-8")
    block_idx = index_after(text, "Artifact Scout wrapper-only pass-through")
    block = text[block_idx:block_idx + 1200]
    assert "does not run `scripts/artifact-scout-inventory.py`" in block
    assert "does not dispatch `artifact-scout`" in block
    assert "does not scan historical artifacts independently" in block
    assert "only passes it through" in block
    assert "artifact-scout-inventory.json" in block
    assert "artifact-scout.md" in block
    assert "never advances the attend chain's `route_chain`" in block
