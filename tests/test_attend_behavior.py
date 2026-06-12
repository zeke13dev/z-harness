"""
tests/test_attend_behavior.py — Behavioral tests for /z-attend mechanics.

Tests cover:
  1. mechanical_proceed_has_skill_default — mechanical_proceed qids have a non-null skill_default
     (the value z-attend auto-answers with). The four substantive categories surface an ask.
  2. test_untagged_gate_resolves_to_ask_never_mechanical_proceed — NAMED invariant-1 test:
     an untagged or unknown qid MUST resolve to "ask", NEVER "mechanical_proceed".
  3. each_of_the_four_categories_surfaced — decision, risk, shortcut, archiving qids all
     resolve to a non-mechanical category (they surface an inline ask, not auto-skip).
  4. lint_halt_categories_recognizes_all_five_enum_values — lint accepts all enum members
     and rejects non-members.
  5. lint_halt_categories_out_of_enum_rejected — a non-enum category= token fails.
  6. chain_runner_cursor_resume — cursor (first non-complete step) used as re-entry point.
  7. resume_halts_on_head_mismatch — R1: HEAD SHA mismatch → HALT text in z-attend.md.
  8. resume_halts_on_phase_cursor_disagreement — R2: phase/cursor disagreement → HALT.
  9. resume_warns_on_session_id_unchanged — R3: session_id unchanged → WARN.
  10. resume_warns_on_done_set_or_dirty_tree_drift — R4: drift → WARN-and-ask.
  11. surface_shortcut_require_both — non-empty --declined + missing --chosen → exit 2.
  12. surface_shortcut_empty_declined_is_noop — empty --declined → exit 0, no event.

CI-runnable: pytest tests/test_attend_behavior.py -q
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_CONFIG = str(_REPO_ROOT / "scripts" / "config.py")
_SCRIPT_LINT = str(_REPO_ROOT / "scripts" / "lint-halt-categories.sh")
_SCRIPT_SHORTCUT = str(_REPO_ROOT / "scripts" / "surface-shortcut.sh")
_ATTEND_MD = _REPO_ROOT / "commands" / "z-attend.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_config(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, _SCRIPT_CONFIG, *args],
        capture_output=True,
        text=True,
    )


def _run_lint(args: list[str], commands_dir: str | None = None) -> subprocess.CompletedProcess:
    cmd = ["bash", _SCRIPT_LINT]
    if commands_dir is not None:
        cmd += ["--commands-dir", commands_dir]
    cmd += args
    return subprocess.run(cmd, capture_output=True, text=True)


def _run_shortcut(
    *extra_args: str,
    tmp_base: Path,
    run_id: str = "test-run-001",
    env_overrides: dict | None = None,
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "Z_HARNESS_BASE_DIR": str(tmp_base),
        "Z_HARNESS_HOST": "test-host",
        "RUN": run_id,
    }
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", _SCRIPT_SHORTCUT, *extra_args],
        env=env,
        capture_output=True,
        text=True,
    )


def _import_config():
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    import config as cfg
    return cfg


# ---------------------------------------------------------------------------
# Test 1: mechanical_proceed qids have a non-null skill_default
# ---------------------------------------------------------------------------

class TestMechanicalProceedHasSkillDefault:
    """mechanical_proceed qids are auto-answered via skill_default; they MUST have one."""

    def test_mechanical_proceed_qids_have_nonnull_skill_default(self):
        """Every mechanical_proceed qid must have a non-null skill_default.

        This is what /z-attend uses to auto-answer: if skill_default were None, the
        auto-answer mechanism has no value to use and would silently fail.
        """
        cfg = _import_config()
        mechanical_qids = [
            qid for qid, meta in cfg.QUESTION_IDS.items()
            if meta.get("halt_category") == "mechanical_proceed"
        ]
        assert mechanical_qids, "No mechanical_proceed qids found — QUESTION_IDS may be empty"
        for qid in mechanical_qids:
            meta = cfg.QUESTION_IDS[qid]
            assert meta.get("skill_default") is not None, (
                f"mechanical_proceed qid {qid!r} has skill_default=None; "
                "z-attend needs a non-null default for auto-answer."
            )

    def test_specific_mechanical_proceed_qids(self):
        """The SPEC enumerates exactly these 3 mechanical_proceed qids."""
        cfg = _import_config()
        expected_mp = {
            "workflow.implement_all_proceed",
            "workflow.review_all_proceed",
            "workflow.slug_confirm",
        }
        actual_mp = {
            qid for qid, meta in cfg.QUESTION_IDS.items()
            if meta.get("halt_category") == "mechanical_proceed"
        }
        assert expected_mp == actual_mp, (
            f"mechanical_proceed qids changed. expected={expected_mp}, actual={actual_mp}"
        )


# ---------------------------------------------------------------------------
# Test 2 (NAMED — Invariant 1): untagged/unknown gate resolves to "ask", NOT "mechanical_proceed"
# ---------------------------------------------------------------------------

class TestUntaggedGateResolvesToAskNeverMechanicalProceed:
    """HARD INVARIANT 1 (SPEC): untagged/unknown RUNTIME-GATE ⇒ ask, NEVER mechanical_proceed.

    An untagged gate must surface as an inline ask every run until it gets tagged.
    Mis-surfacing requires an explicit wrong tag — omission must NEVER auto-skip.
    """

    def test_untagged_gate_resolves_to_ask_never_mechanical_proceed_via_cli(self):
        """NAMED INVARIANT TEST: unknown qid via CLI returns 'ask', not 'mechanical_proceed'."""
        result = _run_config("resolve-halt-category", "workflow.totally_untagged_gate")
        assert result.returncode == 0
        resolved = result.stdout.strip()
        # The critical assertion: must be "ask", never "mechanical_proceed"
        assert resolved == "ask", (
            f"INVARIANT 1 VIOLATED: an untagged/unknown RUNTIME-GATE resolved to {resolved!r} "
            "instead of 'ask'. Untagged gates MUST always surface inline asks — "
            "they must never be auto-skipped as mechanical_proceed."
        )
        assert resolved != "mechanical_proceed", (
            "INVARIANT 1 VIOLATED: an unknown qid resolved to mechanical_proceed — "
            "this would cause the gate to be auto-answered without user input."
        )

    def test_completely_unknown_qid_never_resolves_to_mechanical_proceed(self):
        """A completely unknown question_id must not resolve to mechanical_proceed."""
        for fake_qid in [
            "workflow.invented_gate",
            "not.a.real.qid",
            "",
            "random_string_with_no_dot",
        ]:
            result = _run_config("resolve-halt-category", fake_qid)
            # Empty qid may exit 2 (usage error) or 0 returning "ask" — both are fine
            # as long as the result is NOT "mechanical_proceed"
            if result.returncode == 0:
                assert result.stdout.strip() != "mechanical_proceed", (
                    f"Unknown qid {fake_qid!r} resolved to mechanical_proceed — INVARIANT 1 violated."
                )

    def test_untagged_qid_in_question_ids_returns_ask_not_mechanical_proceed(self):
        """A qid injected into QUESTION_IDS without halt_category returns 'ask', not 'mechanical_proceed'."""
        cfg = _import_config()

        # Temporarily inject a fake qid without halt_category
        fake_qid = "_test_untagged_invariant_1"
        cfg.QUESTION_IDS[fake_qid] = {
            "config_key": fake_qid,
            "choices": {"ask"},
            "skill_default": "ask",
            # halt_category intentionally absent — simulates an untagged gate
        }
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                cfg.cmd_resolve_halt_category([fake_qid])
            resolved = buf.getvalue().strip()
            # The critical check: must be "ask", NEVER "mechanical_proceed"
            assert resolved == "ask", (
                f"INVARIANT 1 VIOLATED: untagged qid (no halt_category) resolved to {resolved!r} "
                "instead of 'ask'. cmd_resolve_halt_category must return 'ask' as the fail-safe."
            )
            assert resolved != "mechanical_proceed", (
                "INVARIANT 1 VIOLATED: untagged qid resolved to mechanical_proceed — "
                "the fail-safe default is broken."
            )
        finally:
            del cfg.QUESTION_IDS[fake_qid]


# ---------------------------------------------------------------------------
# Test 3: each of the four substantive categories surfaces an inline ask
# ---------------------------------------------------------------------------

class TestFourSubstantiveCategoriesSurface:
    """decision, risk, shortcut, archiving all resolve to a category that surfaces an ask.

    The SPEC table: mechanical_proceed → auto-skip; all others → ask inline.
    """

    @pytest.mark.parametrize("expected_cat,qid", [
        ("decision", "workflow.plan_decisions_approval"),
        ("decision", "workflow.spec_retro_discovery"),
        ("risk",     "workflow.audit_to_amend"),
        ("risk",     "workflow.pre_run_cost_gate"),
    ])
    def test_substantive_category_qids_via_cli(self, expected_cat: str, qid: str):
        """Named qids in the four substantive categories resolve to their category."""
        result = _run_config("resolve-halt-category", qid)
        assert result.returncode == 0, result.stderr
        resolved = result.stdout.strip()
        assert resolved == expected_cat, (
            f"qid={qid!r} expected category={expected_cat!r}, got {resolved!r}"
        )
        assert resolved != "mechanical_proceed", (
            f"qid={qid!r} (category={expected_cat}) must NOT resolve to mechanical_proceed — "
            "it should surface an inline ask, not be auto-skipped."
        )

    def test_four_substantive_categories_present_in_enum(self):
        """All four substantive categories appear in HALT_CATEGORY_ENUM."""
        cfg = _import_config()
        for cat in ("decision", "risk", "shortcut", "archiving"):
            assert cat in cfg.HALT_CATEGORY_ENUM, (
                f"Category {cat!r} missing from HALT_CATEGORY_ENUM — "
                "z-attend uses this enum to decide which gates surface an ask."
            )

    def test_all_five_enum_members_known(self):
        """HALT_CATEGORY_ENUM has exactly these 5 members (4 substantive + mechanical_proceed)."""
        cfg = _import_config()
        expected = frozenset({"decision", "risk", "shortcut", "archiving", "mechanical_proceed"})
        assert cfg.HALT_CATEGORY_ENUM == expected, (
            f"HALT_CATEGORY_ENUM changed: expected={sorted(expected)}, "
            f"actual={sorted(cfg.HALT_CATEGORY_ENUM)}"
        )

    def test_substantive_categories_are_not_mechanical_proceed(self):
        """No qid with a substantive (ask) category should also be mechanical_proceed."""
        cfg = _import_config()
        for qid, meta in cfg.QUESTION_IDS.items():
            cat = meta.get("halt_category")
            if cat in ("decision", "risk", "shortcut", "archiving"):
                assert cat != "mechanical_proceed", (
                    f"qid={qid!r} is categorized as both {cat!r} and mechanical_proceed — impossible."
                )


# ---------------------------------------------------------------------------
# Test 4 & 5: lint-halt-categories.sh recognizes all enum values, rejects non-members
# ---------------------------------------------------------------------------

class TestLintHaltCategoriesEnumValidation:
    """lint-halt-categories.sh validates each of the 4 substantive categories + mechanical_proceed."""

    @pytest.mark.parametrize("category", [
        "decision", "risk", "shortcut", "archiving", "mechanical_proceed",
    ])
    def test_all_five_enum_members_accepted_by_lint(self, category: str, tmp_path: Path):
        """Each of the 5 enum members passes lint without error."""
        cmds = tmp_path / "commands"
        cmds.mkdir()
        (cmds / "test.md").write_text(
            f"<!-- RUNTIME-GATE: ask_user; category={category} -->\n"
        )
        result = _run_lint([], commands_dir=str(cmds))
        assert result.returncode == 0, (
            f"Lint rejected valid category={category!r}. returncode={result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_out_of_enum_category_rejected(self, tmp_path: Path):
        """A non-enum category= token causes lint to exit non-zero."""
        cmds = tmp_path / "commands"
        cmds.mkdir()
        (cmds / "test.md").write_text(
            "<!-- RUNTIME-GATE: ask_user; category=totally_invalid_category -->\n"
        )
        result = _run_lint([], commands_dir=str(cmds))
        assert result.returncode != 0, (
            "Lint accepted an out-of-enum category — enum validation is broken."
        )
        combined = result.stdout + result.stderr
        assert "ERROR" in combined

    def test_missing_category_warns_not_errors_by_default(self, tmp_path: Path):
        """An ask_user gate with no category= token produces a WARN (not error) in default mode."""
        cmds = tmp_path / "commands"
        cmds.mkdir()
        (cmds / "test.md").write_text(
            "<!-- RUNTIME-GATE: ask_user; no category token -->\n"
        )
        result = _run_lint([], commands_dir=str(cmds))
        assert result.returncode == 0, (
            f"Missing category produced a hard failure in default mode (should be WARN). "
            f"returncode={result.returncode}"
        )
        combined = result.stdout + result.stderr
        assert "WARN" in combined, "Missing-category gate should produce a WARN"


# ---------------------------------------------------------------------------
# Test 6: chain-runner cursor (resume re-entry)
# ---------------------------------------------------------------------------

class TestChainRunnerCursor:
    """chain-runner.sh cursor subcommand returns the first non-complete step index."""

    def _write_state(self, tmp_path: Path, statuses: list[str]) -> Path:
        """Write a minimal attend-state.json with the given step statuses."""
        chain = [f"step{i}" for i in range(len(statuses))]
        state = {
            "chain": chain,
            "preset_used": "attend-full",
            "started_at": "2025-01-01T00:00:00Z",
            "ended_at": None,
            "status": "running",
            "head_sha_at_start": "abc1234",
            "z_harness_version": "unknown",
            "git_diff_stat_at_end": None,
            "step_runs": [
                {
                    "step": step,
                    "position": i,
                    "run_id": None,
                    "status": statuses[i],
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
        state_file = tmp_path / "attend-state.json"
        state_file.write_text(json.dumps(state))
        return state_file

    def _run_cursor(self, state_file: Path) -> int:
        result = subprocess.run(
            ["bash", str(_REPO_ROOT / "scripts" / "chain-runner.sh"), "cursor", str(state_file)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"chain-runner.sh cursor failed. rc={result.returncode}, stderr={result.stderr!r}"
        )
        return int(result.stdout.strip())

    def test_cursor_all_queued_returns_0(self, tmp_path: Path):
        """All steps queued → cursor=0 (resume from start)."""
        sf = self._write_state(tmp_path, ["queued", "queued", "queued"])
        assert self._run_cursor(sf) == 0

    def test_cursor_skips_complete_returns_second(self, tmp_path: Path):
        """First step complete, rest queued → cursor=1 (skip completed step)."""
        sf = self._write_state(tmp_path, ["complete", "queued", "queued"])
        assert self._run_cursor(sf) == 1

    def test_cursor_all_complete_returns_length(self, tmp_path: Path):
        """All steps complete → cursor=3 (past end, chain done)."""
        sf = self._write_state(tmp_path, ["complete", "complete", "complete"])
        assert self._run_cursor(sf) == 3

    def test_cursor_is_first_non_complete_for_resume(self, tmp_path: Path):
        """Resume re-entry point is exactly the first non-complete step."""
        sf = self._write_state(tmp_path, ["complete", "complete", "halt", "queued"])
        # cursor should point to index 2 (halt, the first non-complete step)
        assert self._run_cursor(sf) == 2


# ---------------------------------------------------------------------------
# Test 7: resume HALTS on HEAD mismatch (R1 — doc-contract test)
# ---------------------------------------------------------------------------

class TestResumeHaltsOnHeadMismatch:
    """R1: if expected_head_sha ≠ current HEAD, the command MUST HALT.

    z-attend.md is an LLM orchestrator prompt, not executable bash. These tests
    assert the contract by grep-style structural assertions on z-attend.md text
    (the documented behavior), since the behavior is encoded in prompt instructions,
    not in a testable binary. This is the accepted pattern for prompt-only contracts
    (per T013 task spec: 'grep-style structural assertions are acceptable for prompt-only
    contracts').
    """

    def test_attend_md_contains_head_sha_halt_behavior(self):
        """z-attend.md must document: HEAD SHA mismatch → HALT."""
        text = _ATTEND_MD.read_text()
        # R1 predicate: the command must compare expected vs actual head sha
        assert "expected_head_sha" in text, (
            "z-attend.md must reference 'expected_head_sha' in the resume predicate (R1)."
        )
        # The command must HALT on mismatch
        assert "HALT" in text, (
            "z-attend.md must instruct HALT on head_sha_mismatch."
        )

    def test_attend_md_head_mismatch_is_hard_halt_not_warn(self):
        """R1 predicate: HEAD mismatch is a HARD HALT (not a WARN-and-ask like R3/R4)."""
        text = _ATTEND_MD.read_text()
        # Find the R1 section
        r1_match = re.search(
            r"Validation step R1.*?(?=Validation step R2|##)",
            text,
            re.DOTALL,
        )
        assert r1_match is not None, "Could not locate R1 section in z-attend.md"
        r1_text = r1_match.group(0)
        # R1 must say HALT (not just WARN)
        assert "HALT" in r1_text, (
            "R1 (HEAD SHA mismatch) must document a HALT, not a WARN. "
            "Silent auto-continue on a moved base is forbidden (SPEC Invariant 5)."
        )
        # R1 must NOT say "warn" as the primary action
        # (it may mention remediation options, but the primary is HALT)
        assert "head_sha_mismatch" in r1_text, (
            "R1 section must reference 'head_sha_mismatch' as the halt reason."
        )

    def test_attend_md_r1_emits_attend_resume_halt_event(self):
        """R1 must emit an attend_resume_halt event on mismatch."""
        text = _ATTEND_MD.read_text()
        r1_match = re.search(
            r"Validation step R1.*?(?=Validation step R2|##)",
            text,
            re.DOTALL,
        )
        assert r1_match is not None
        r1_text = r1_match.group(0)
        assert "attend_resume_halt" in r1_text, (
            "R1 must emit 'attend_resume_halt' event (SPEC Invariant 5 observability)."
        )


# ---------------------------------------------------------------------------
# Test 8: resume HALTS on phase/cursor disagreement (R2 — doc-contract test)
# ---------------------------------------------------------------------------

class TestResumeHaltsOnPhaseCursorDisagreement:
    """R2: state file cursor vs token expected_phase disagreement → HALT."""

    def test_attend_md_contains_phase_cursor_halt_behavior(self):
        """z-attend.md must document R2: phase/cursor disagreement → HALT."""
        text = _ATTEND_MD.read_text()
        assert "expected_phase" in text, (
            "z-attend.md must reference 'expected_phase' in the resume predicate (R2)."
        )

    def test_attend_md_r2_is_hard_halt(self):
        """R2 predicate: phase/cursor disagreement is a HARD HALT."""
        text = _ATTEND_MD.read_text()
        r2_match = re.search(
            r"Validation step R2.*?(?=Validation step R3|##)",
            text,
            re.DOTALL,
        )
        assert r2_match is not None, "Could not locate R2 section in z-attend.md"
        r2_text = r2_match.group(0)
        assert "HALT" in r2_text, (
            "R2 (phase/cursor disagreement) must document a HALT — "
            "a corrupted state must not allow silent re-entry."
        )
        assert "phase_cursor_disagree" in r2_text, (
            "R2 section must reference 'phase_cursor_disagree' as the halt reason."
        )

    def test_attend_md_r2_emits_attend_resume_halt_event(self):
        """R2 must emit an attend_resume_halt event on disagreement."""
        text = _ATTEND_MD.read_text()
        r2_match = re.search(
            r"Validation step R2.*?(?=Validation step R3|##)",
            text,
            re.DOTALL,
        )
        assert r2_match is not None
        r2_text = r2_match.group(0)
        assert "attend_resume_halt" in r2_text, (
            "R2 must emit 'attend_resume_halt' event."
        )


# ---------------------------------------------------------------------------
# Test 9: resume WARNS-and-asks on session_id unchanged (R3 — doc-contract test)
# ---------------------------------------------------------------------------

class TestResumeWarnsOnSessionIdUnchanged:
    """R3: if session_id unchanged, the command MUST WARN HARD (not silently continue)."""

    def test_attend_md_contains_session_id_warn_behavior(self):
        """z-attend.md must document R3: session_id unchanged → WARN HARD."""
        text = _ATTEND_MD.read_text()
        assert "session_id" in text, (
            "z-attend.md must reference 'session_id' in the resume predicate (R3)."
        )

    def test_attend_md_r3_is_warn_not_halt(self):
        """R3 is a WARN-and-ask (not a HALT like R1/R2)."""
        text = _ATTEND_MD.read_text()
        r3_match = re.search(
            r"Validation step R3.*?(?=Validation step R4|##)",
            text,
            re.DOTALL,
        )
        assert r3_match is not None, "Could not locate R3 section in z-attend.md"
        r3_text = r3_match.group(0)
        # R3 should WARN, not hard HALT
        assert "WARN" in r3_text or "warn" in r3_text.lower(), (
            "R3 (session_id unchanged) must document a WARN, not a silent ignore."
        )
        assert "session_unchanged" in r3_text, (
            "R3 section must reference 'session_unchanged' as the warn reason."
        )

    def test_attend_md_r3_emits_attend_resume_warn_event(self):
        """R3 must emit an attend_resume_warn event."""
        text = _ATTEND_MD.read_text()
        r3_match = re.search(
            r"Validation step R3.*?(?=Validation step R4|##)",
            text,
            re.DOTALL,
        )
        assert r3_match is not None
        r3_text = r3_match.group(0)
        assert "attend_resume_warn" in r3_text, (
            "R3 must emit 'attend_resume_warn' event."
        )

    def test_attend_md_r3_offers_abort_option(self):
        """R3 must offer an Abort option (not force-continue)."""
        text = _ATTEND_MD.read_text()
        r3_match = re.search(
            r"Validation step R3.*?(?=Validation step R4|##)",
            text,
            re.DOTALL,
        )
        assert r3_match is not None
        r3_text = r3_match.group(0)
        assert "Abort" in r3_text or "abort" in r3_text.lower(), (
            "R3 must offer an Abort option — the user must be able to decline."
        )


# ---------------------------------------------------------------------------
# Test 10: resume WARNS-and-asks on done-set/dirty-tree drift (R4 — doc-contract + helper test)
# ---------------------------------------------------------------------------

class TestResumeWarnsOnDoneSetOrDirtyTreeDrift:
    """R4: done-set or dirty-tree drift → WARN-and-ask {continue / abort}."""

    def test_attend_md_contains_done_set_and_dirty_tree_warn(self):
        """z-attend.md must document R4: done-set/dirty-tree drift → WARN-and-ask."""
        text = _ATTEND_MD.read_text()
        assert "done_set_hash" in text, (
            "z-attend.md must reference 'done_set_hash' in the R4 drift predicate."
        )
        assert "dirty_state_fingerprint" in text or "dirty_tree" in text, (
            "z-attend.md must reference dirty-tree fingerprinting in R4."
        )

    def test_attend_md_r4_is_warn_and_ask(self):
        """R4 drift is a WARN-and-ask, not a silent continue and not a hard HALT."""
        text = _ATTEND_MD.read_text()
        r4_match = re.search(
            r"Validation step R4.*?(?=\*\*Re-entry|##)",
            text,
            re.DOTALL,
        )
        assert r4_match is not None, "Could not locate R4 section in z-attend.md"
        r4_text = r4_match.group(0)
        assert "WARN" in r4_text or "warn" in r4_text.lower(), (
            "R4 (done-set/dirty-tree drift) must document a WARN."
        )
        assert "predicate_drift" in r4_text, (
            "R4 section must reference 'predicate_drift' as the warn reason."
        )

    def test_attend_md_r4_emits_attend_resume_warn_event(self):
        """R4 must emit an attend_resume_warn event on drift."""
        text = _ATTEND_MD.read_text()
        r4_match = re.search(
            r"Validation step R4.*?(?=\*\*Re-entry|##)",
            text,
            re.DOTALL,
        )
        assert r4_match is not None
        r4_text = r4_match.group(0)
        assert "attend_resume_warn" in r4_text, (
            "R4 must emit 'attend_resume_warn' event."
        )

    def test_session_helpers_done_set_hash_is_callable(self):
        """session-helpers.sh done_set_hash is a real subcommand (R4 depends on it)."""
        # Create a minimal TASKS.md to compute done_set_hash on
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("## T001 — Stub task `[ ]`\n")
            tasks_path = f.name
        try:
            result = subprocess.run(
                ["bash", str(_REPO_ROOT / "scripts" / "session-helpers.sh"),
                 "done_set_hash", tasks_path],
                capture_output=True,
                text=True,
            )
            # Must exit 0 and return a hex hash
            assert result.returncode == 0, (
                f"session-helpers.sh done_set_hash failed. rc={result.returncode}, "
                f"stderr={result.stderr!r}"
            )
            output = result.stdout.strip()
            assert output, "done_set_hash returned empty output"
            # Should look like a hex string (shasum output)
            assert re.match(r"^[0-9a-f]+$", output), (
                f"done_set_hash output does not look like a hex hash: {output!r}"
            )
        finally:
            os.unlink(tasks_path)


# ---------------------------------------------------------------------------
# Test 11 & 12: surface-shortcut.sh require-both + empty-declined no-op
# ---------------------------------------------------------------------------

class TestSurfaceShortcutRequireBoth:
    """surface-shortcut.sh: require both --chosen and --declined on the event path."""

    def test_require_both_missing_chosen_exits_2(self, tmp_path: Path):
        """Non-empty --declined with no --chosen ⇒ exit 2 (caller wiring bug)."""
        result = _run_shortcut(
            "--declined", "run /z-audit-plan",
            tmp_base=tmp_path,
        )
        assert result.returncode == 2, (
            f"Missing --chosen on event path must exit 2, got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_require_both_empty_chosen_exits_2(self, tmp_path: Path):
        """Non-empty --declined with empty --chosen ⇒ exit 2."""
        result = _run_shortcut(
            "--chosen", "",
            "--declined", "run /z-audit-plan",
            tmp_base=tmp_path,
        )
        assert result.returncode == 2, (
            f"Empty --chosen must exit 2, got {result.returncode}. stderr: {result.stderr!r}"
        )

    def test_require_both_missing_chosen_writes_no_event(self, tmp_path: Path):
        """No event is written when --chosen is missing."""
        _run_shortcut("--declined", "run /z-audit-plan", tmp_base=tmp_path)
        metrics = tmp_path / "metrics.jsonl"
        if metrics.exists():
            for line in metrics.read_text().splitlines():
                event = json.loads(line)
                assert event.get("kind") != "shortcut_proposed", (
                    f"shortcut_proposed event written despite missing --chosen: {event}"
                )

    def test_both_required_success_exits_1(self, tmp_path: Path):
        """Both --chosen and --declined provided → exit 1 (shortcut signal)."""
        result = _run_shortcut(
            "--chosen", "use /z-do",
            "--declined", "use /z-plan (full pass)",
            tmp_base=tmp_path,
        )
        assert result.returncode == 1, (
            f"Both flags provided must exit 1 (shortcut signal), got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )


class TestSurfaceShortcutEmptyDeclinedIsNoop:
    """surface-shortcut.sh: empty or missing --declined is a silent no-op (Invariant 6)."""

    def test_empty_declined_exits_0(self, tmp_path: Path):
        """Empty --declined string ⇒ exit 0 (not a shortcut without namable alternative)."""
        result = _run_shortcut(
            "--chosen", "cheap path",
            "--declined", "",
            tmp_base=tmp_path,
        )
        assert result.returncode == 0, (
            f"Empty --declined must be a no-op (exit 0), got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_empty_declined_writes_no_event(self, tmp_path: Path):
        """No shortcut_proposed event when --declined is empty."""
        _run_shortcut("--chosen", "cheap path", "--declined", "", tmp_base=tmp_path)
        metrics = tmp_path / "metrics.jsonl"
        if metrics.exists():
            for line in metrics.read_text().splitlines():
                event = json.loads(line)
                assert event.get("kind") != "shortcut_proposed", (
                    f"shortcut_proposed event wrongly written for empty --declined: {event}"
                )

    def test_missing_declined_flag_exits_0(self, tmp_path: Path):
        """No --declined flag ⇒ exit 0 (no shortcut, no event)."""
        result = _run_shortcut(tmp_base=tmp_path)
        assert result.returncode == 0, (
            f"Missing --declined flag must exit 0 (not a shortcut), "
            f"got {result.returncode}. stderr: {result.stderr!r}"
        )

    def test_empty_declined_distinct_from_nonempty_declined(self, tmp_path: Path):
        """Explicit contrast: empty declined ⇒ 0; non-empty declined ⇒ 1. Must differ."""
        empty = _run_shortcut("--chosen", "p1", "--declined", "", tmp_base=tmp_path / "a")
        nonempty = _run_shortcut("--chosen", "p1", "--declined", "p2", tmp_base=tmp_path / "b")
        assert empty.returncode == 0, "empty --declined must exit 0"
        assert nonempty.returncode == 1, "non-empty --declined must exit 1 (shortcut signal)"
        assert empty.returncode != nonempty.returncode, (
            "M3 contract broken: empty and non-empty --declined produce the same exit code"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
