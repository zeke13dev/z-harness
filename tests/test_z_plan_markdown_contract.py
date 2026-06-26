from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
Z_PLAN_SKILL = REPO_ROOT / "skills" / "z-plan" / "SKILL.md"


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
    for field in ("mode", "recommended_mode", "source", "reason", "legacy_spec_forced"):
        assert f'"{field}"' in mode_block


def test_post_artifact_route_check_fires_after_tasks_and_before_handoff() -> None:
    text = skill_text()

    phase8 = index_after(text, "## Phase 8 — TASKS.md")
    post_route = index_after(text, "## Phase 8.4 — Post-artifact route check", phase8)
    handoff = index_after(text, "## Phase 8.5 — Handoff context producer", post_route)
    final_gate = index_after(text, "## Phase 8.6 — Final handoff gate", handoff)

    assert phase8 < post_route < handoff < final_gate
    block = text[post_route:handoff]
    assert 'route_class: "post_artifact"' in block
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


def test_revised_spine_documents_ordered_skill_edit_sequence() -> None:
    text = skill_text()
    spine = text[
        index_after(text, "## Revised phase spine and `/z-plan` edit sequence"):
        index_after(text, "## Setup")
    ]

    assert "T001 spine/mode gate first" in spine
    assert "T005 Phase 8 sanity" in spine
    assert "T006 Phase 8.5 handoff producer" in spine
    assert "T007 Phase 7 mode-aware reviewer inputs" in spine
    assert "docs sync" in spine
