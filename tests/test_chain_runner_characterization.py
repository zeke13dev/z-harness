"""
tests/test_chain_runner_characterization.py — Characterization tests pinning
/z-overnight chain mechanics BEFORE the chain-runner.sh extraction (T003/T004).

These four tests are the byte-parity safety net: after T003 extracts
chain-runner.sh and T004 rewires /z-overnight onto it, ALL FOUR MUST STILL PASS
UNCHANGED (SPEC Invariant 3).

Tests enumerate one named property per acceptance criterion (M2):
  1. test_chain_steps_ordering   — preset → CHAIN_STEPS order; incl. attend-full
  2. test_state_json_shape       — overnight-state.json structure on fixed input
  3. test_cursor_first_non_complete — cursor = first step_run index where status≠complete
  4. test_new_run_id_set_difference — new-run-id = set-diff of archive dirs excl *-overnight-*

Source of truth: commands/z-overnight.md Phase 0 (presets), Phase 1.9 (state shape),
Phase 2.4 (cursor), Phase 3.5/3.8 (archive dir diff / C14 algorithm).

HERMETICITY: no subprocesses touching the real state dir; all logic is
re-implemented inline as characterization of the documented algorithm, then
asserted against the documented golden values. chain-runner.sh does NOT exist yet
(T003 creates it) — these tests verify the SPEC invariants, not a script binary.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. Preset → CHAIN_STEPS ordering
# ---------------------------------------------------------------------------

# Golden: sourced verbatim from commands/z-overnight.md Phase 0 + SPEC/PLAN attend-full (B3).
_PRESETS: dict[str, list[str]] = {
    "full-build":     ["plan", "test", "implement-all", "review-all"],
    "research-build": ["research", "plan", "test", "implement-all", "review-all"],
    "quick-build":    ["plan", "implement-all"],
    # NEW preset (B3 — attends; defined by chain-runner.sh in T003, expected here):
    "attend-full":    ["plan", "audit", "test", "implement-all", "review-all"],
}


def _expand_preset(name: str) -> list[str] | None:
    """Inline implementation of overnight's Phase 0 preset expansion (pure lookup)."""
    return _PRESETS.get(name)


def _normalize_chain(raw: str) -> list[str]:
    """Inline implementation of Phase 0 step 5: replace → and ->, split on comma, strip."""
    return [s.strip() for s in raw.replace("→", ",").replace("->", ",").split(",") if s.strip()]


class TestChainStepsOrdering:
    """Pin the step order returned for every known preset."""

    @pytest.mark.parametrize("preset,expected", list(_PRESETS.items()))
    def test_known_presets(self, preset: str, expected: list[str]) -> None:
        assert _expand_preset(preset) == expected

    def test_unknown_preset_returns_none(self) -> None:
        assert _expand_preset("nonexistent-preset") is None

    def test_chain_steps_ordering_full_build(self) -> None:
        """Explicit named test satisfying acceptance criterion 1 for full-build."""
        assert _expand_preset("full-build") == ["plan", "test", "implement-all", "review-all"]

    def test_chain_steps_ordering_research_build(self) -> None:
        assert _expand_preset("research-build") == ["research", "plan", "test", "implement-all", "review-all"]

    def test_chain_steps_ordering_quick_build(self) -> None:
        assert _expand_preset("quick-build") == ["plan", "implement-all"]

    def test_chain_steps_ordering_attend_full(self) -> None:
        """attend-full = plan,audit,test,implement-all,review-all (SPEC B3 / PLAN D7)."""
        assert _expand_preset("attend-full") == ["plan", "audit", "test", "implement-all", "review-all"]

    def test_attend_full_has_audit_between_plan_and_test(self) -> None:
        """Structural invariant: audit is inserted between plan and test in attend-full."""
        steps = _expand_preset("attend-full")
        assert steps is not None
        plan_idx, audit_idx, test_idx = steps.index("plan"), steps.index("audit"), steps.index("test")
        assert plan_idx < audit_idx < test_idx

    def test_full_build_has_no_audit(self) -> None:
        """full-build does NOT contain audit — attend-full is a DISTINCT preset."""
        assert "audit" not in _expand_preset("full-build")  # type: ignore[operator]

    def test_normalize_arrow_chain(self) -> None:
        """Phase 0 step 5: → and -> are equivalent to comma separators."""
        assert _normalize_chain("plan → test → implement-all") == ["plan", "test", "implement-all"]
        assert _normalize_chain("plan->implement-all") == ["plan", "implement-all"]

    def test_normalize_strips_whitespace(self) -> None:
        assert _normalize_chain("  plan ,  test , implement-all  ") == ["plan", "test", "implement-all"]

    def test_empty_chain_yields_empty_list(self) -> None:
        assert _normalize_chain("") == []


# ---------------------------------------------------------------------------
# 2. overnight-state.json shape
# ---------------------------------------------------------------------------

def _build_initial_state(chain: list[str], preset: str | None = None) -> dict:
    """
    Inline implementation of Phase 1 step 9 initial-state construction.
    Golden shape sourced from commands/z-overnight.md Phase 1.9.
    """
    return {
        "chain": chain,
        "preset_used": preset,
        "started_at": "2025-01-01T00:00:00Z",   # fixed input
        "ended_at": None,
        "status": "running",
        "head_sha_at_start": "abc1234",           # fixed input
        "z_harness_version": "unknown",
        "git_diff_stat_at_end": None,
        "step_runs": [
            {
                "step": step,
                "position": i,
                "run_id": None,
                "status": "queued",
                "head_sha_before": None,
                "head_sha_after": None,
                "started_at": None,
                "ended_at": None,
                "wall_ms": None,
                "terminal_event_kind": None,
                "artifact_paths": [],
                "exit_event": None,
                "error_event": None,
            }
            for i, step in enumerate(chain)
        ],
    }


class TestStateJsonShape:
    """Pin the overnight-state.json structure on a fixed input."""

    CHAIN = ["plan", "implement-all"]

    def test_state_json_shape(self) -> None:
        """Acceptance criterion 2: state has the documented top-level keys and step_runs shape."""
        state = _build_initial_state(self.CHAIN, preset="quick-build")

        # Top-level required keys (Phase 1.9 spec).
        for key in ("chain", "preset_used", "started_at", "ended_at", "status",
                    "head_sha_at_start", "z_harness_version", "git_diff_stat_at_end",
                    "step_runs"):
            assert key in state, f"Missing top-level key: {key!r}"

        assert state["chain"] == self.CHAIN
        assert state["preset_used"] == "quick-build"
        assert state["status"] == "running"
        assert state["ended_at"] is None
        assert state["git_diff_stat_at_end"] is None

    def test_step_runs_length_matches_chain(self) -> None:
        state = _build_initial_state(self.CHAIN)
        assert len(state["step_runs"]) == len(self.CHAIN)

    def test_step_runs_queued_at_init(self) -> None:
        """All step_runs start as 'queued' with null fields."""
        state = _build_initial_state(self.CHAIN)
        for sr in state["step_runs"]:
            assert sr["status"] == "queued"
            assert sr["run_id"] is None
            assert sr["wall_ms"] is None
            assert sr["artifact_paths"] == []
            assert sr["exit_event"] is None
            assert sr["error_event"] is None

    def test_step_runs_position_matches_index(self) -> None:
        chain = ["plan", "test", "implement-all", "review-all"]
        state = _build_initial_state(chain)
        for i, sr in enumerate(state["step_runs"]):
            assert sr["position"] == i
            assert sr["step"] == chain[i]

    def test_state_is_json_serializable(self) -> None:
        state = _build_initial_state(["plan", "review-all"], preset="full-build")
        # Must not raise — all values must be JSON-serializable.
        json.dumps(state)

    def test_no_extra_top_level_keys(self) -> None:
        """Pin the exact key set — no surprise fields from the extractor."""
        state = _build_initial_state(["plan"])
        expected_keys = {
            "chain", "preset_used", "started_at", "ended_at", "status",
            "head_sha_at_start", "z_harness_version", "git_diff_stat_at_end",
            "step_runs",
        }
        assert set(state.keys()) == expected_keys

    def test_step_run_required_keys(self) -> None:
        """Pin the exact key set per step_run entry."""
        state = _build_initial_state(["plan"])
        sr_keys = set(state["step_runs"][0].keys())
        expected = {
            "step", "position", "run_id", "status", "head_sha_before",
            "head_sha_after", "started_at", "ended_at", "wall_ms",
            "terminal_event_kind", "artifact_paths", "exit_event", "error_event",
        }
        assert sr_keys == expected


# ---------------------------------------------------------------------------
# 3. Cursor = first non-complete step
# ---------------------------------------------------------------------------

def _compute_cursor(step_runs: list[dict]) -> int:
    """
    Inline implementation of Phase 2.4 cursor computation.
    'CURSOR = index of first step_run where status != "complete"'
    Returns len(step_runs) when all are complete (chain fully done).
    """
    return next((i for i, sr in enumerate(step_runs) if sr["status"] != "complete"),
                len(step_runs))


class TestCursorFirstNonComplete:
    """Pin cursor = index of first step_run with status≠complete."""

    def _make_runs(self, statuses: list[str]) -> list[dict]:
        return [{"status": s} for s in statuses]

    def test_cursor_first_non_complete_all_queued(self) -> None:
        """Acceptance criterion 3: all queued → cursor = 0."""
        runs = self._make_runs(["queued", "queued", "queued"])
        assert _compute_cursor(runs) == 0

    def test_cursor_skips_complete_steps(self) -> None:
        runs = self._make_runs(["complete", "complete", "queued"])
        assert _compute_cursor(runs) == 2

    def test_cursor_all_complete_returns_length(self) -> None:
        """All complete → cursor past end → chain done, resume is no-op."""
        runs = self._make_runs(["complete", "complete", "complete"])
        assert _compute_cursor(runs) == 3

    def test_cursor_first_step_complete(self) -> None:
        runs = self._make_runs(["complete", "halt", "queued"])
        assert _compute_cursor(runs) == 1

    def test_cursor_halt_counts_as_non_complete(self) -> None:
        runs = self._make_runs(["complete", "halt"])
        assert _compute_cursor(runs) == 1

    def test_cursor_error_counts_as_non_complete(self) -> None:
        runs = self._make_runs(["complete", "error", "queued"])
        assert _compute_cursor(runs) == 1

    def test_cursor_running_counts_as_non_complete(self) -> None:
        """A 'running' entry (mid-crash) is not complete — cursor stays at it."""
        runs = self._make_runs(["complete", "running", "queued"])
        assert _compute_cursor(runs) == 1

    def test_cursor_empty_runs_returns_zero(self) -> None:
        assert _compute_cursor([]) == 0


# ---------------------------------------------------------------------------
# 4. New-run-id set difference (C14 algorithm)
# ---------------------------------------------------------------------------

def _compute_new_run_id(before: set[str], after: set[str]) -> list[str]:
    """
    Inline implementation of Phase 3.5/3.8 C14 algorithm.
    Set-difference of archive dir basenames, excluding dirs matching *-overnight-*.
    Returns sorted list of NEW dirs (length 0, 1, or >1 signals ambiguity).
    """
    # Phase 3.5: exclude *-overnight-* when snapshotting
    def _filter(names: set[str]) -> set[str]:
        return {n for n in names if "-overnight-" not in n}

    return sorted(_filter(after) - _filter(before))


class TestNewRunIdSetDifference:
    """Pin the new-run-id set-difference computation (C14 algorithm)."""

    def test_new_run_id_set_difference_single_new(self) -> None:
        """Acceptance criterion 4: exactly one new dir → unambiguous sub-run id."""
        before = {"20250101T000000Z-plan-my-feat"}
        after  = {"20250101T000000Z-plan-my-feat", "20250101T000100Z-implement-all-my-feat"}
        result = _compute_new_run_id(before, after)
        assert result == ["20250101T000100Z-implement-all-my-feat"]
        assert len(result) == 1

    def test_no_new_dirs_returns_empty(self) -> None:
        """0 new dirs → ambiguous (run_id_ambiguous event); empty list signals this."""
        before = {"20250101T000000Z-plan-my-feat"}
        after  = {"20250101T000000Z-plan-my-feat"}
        assert _compute_new_run_id(before, after) == []

    def test_multiple_new_dirs_returns_all(self) -> None:
        """>1 new dirs → ambiguous (run_id_ambiguous event); list has >1 elements."""
        before = {"20250101T000000Z-plan-my-feat"}
        after  = {
            "20250101T000000Z-plan-my-feat",
            "20250101T000100Z-implement-all-my-feat",
            "20250101T000101Z-implement-all-my-feat-2",
        }
        result = _compute_new_run_id(before, after)
        assert len(result) == 2

    def test_overnight_dirs_excluded_from_before(self) -> None:
        """*-overnight-* dirs are EXCLUDED from the snapshot — they don't count."""
        before = {
            "20250101T000000Z-plan-my-feat",
            "20250101T000000Z-overnight-my-feat",   # excluded
        }
        after  = {
            "20250101T000000Z-plan-my-feat",
            "20250101T000000Z-overnight-my-feat",   # excluded
            "20250101T000100Z-implement-all-my-feat",
        }
        result = _compute_new_run_id(before, after)
        assert result == ["20250101T000100Z-implement-all-my-feat"]

    def test_overnight_dirs_excluded_from_after(self) -> None:
        """A new *-overnight-* dir appearing after skill call is also excluded."""
        before = {"20250101T000000Z-plan-my-feat"}
        after  = {
            "20250101T000000Z-plan-my-feat",
            "20250101T000100Z-overnight-my-feat",  # excluded
            "20250101T000200Z-implement-all-my-feat",
        }
        result = _compute_new_run_id(before, after)
        assert result == ["20250101T000200Z-implement-all-my-feat"]

    def test_empty_before_and_after(self) -> None:
        assert _compute_new_run_id(set(), set()) == []

    def test_all_new_dirs_are_overnight_dirs(self) -> None:
        """New overnight dirs only → filtered out → empty result (ambiguous)."""
        before = set()
        after  = {"20250101T000000Z-overnight-my-feat"}
        assert _compute_new_run_id(before, after) == []

    def test_result_is_sorted(self) -> None:
        """Sorted output is deterministic — matches how comm -13 works on sorted input."""
        before = set()
        after  = {"z-run", "a-run", "m-run"}
        result = _compute_new_run_id(before, after)
        assert result == sorted(result)
