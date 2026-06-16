"""
tests/test_intent_engine.py — Unit tests for the evaluate_acceptance helper
in scripts/intent-schema.py.

Tests cover:
  TestCriterionExtraction  — _extract_checklist_items parses items correctly
  TestLedgerCitations      — _extract_ledger_cited_criteria parses #N citations
  TestEvaluateAcceptance   — the main evaluate_acceptance API + CLI
  TestEvalCLI              — CLI entry point for evaluate-acceptance subcommand

The invariant under test:
  A criterion is "met" IFF it is cited in the LEDGER with criterion #N AND the
  cumulative diff is non-empty.  Without a ledger citation it is always "unmet".
  Without a non-empty diff it is at most "unknown" even if cited.
  "unknown" is ALWAYS treated as "unmet" for the done/continue verdict.
  Failure class: evaluator returns "done" when ambiguous evidence exists →
  premature BFS loop termination before all acceptance criteria are provably satisfied.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_PY = str(_REPO_ROOT / "scripts" / "intent-schema.py")


# ---------------------------------------------------------------------------
# Module import helper
# ---------------------------------------------------------------------------

def _import_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "intent_schema", _REPO_ROOT / "scripts" / "intent-schema.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _import_module()
evaluate_acceptance = _mod.evaluate_acceptance
_extract_checklist_items = _mod._extract_checklist_items
_extract_ledger_cited_criteria = _mod._extract_ledger_cited_criteria
STATUS_MET = _mod.STATUS_MET
STATUS_UNMET = _mod.STATUS_UNMET
STATUS_UNKNOWN = _mod.STATUS_UNKNOWN
VERDICT_DONE = _mod.VERDICT_DONE
VERDICT_CONTINUE = _mod.VERDICT_CONTINUE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_INTENT_TWO_CRITERIA = textwrap.dedent("""\
    ---
    artifact: intent
    slug: test-eval
    level: quick
    generated_at: 2026-06-16T00:00:00Z
    frozen_at: 2026-06-16T01:00:00Z
    planning_mode: intent
    ---
    ## Intent
    This is what the effort accomplishes.
    ## Acceptance checklist
    - [ ] The evaluate-acceptance CLI exits 0 when all criteria are met
    - [ ] Per-criterion output lines show met|unmet|unknown status
""")

_INTENT_THREE_CRITERIA = textwrap.dedent("""\
    ---
    artifact: intent
    slug: test-eval
    level: quick
    generated_at: 2026-06-16T00:00:00Z
    frozen_at: 2026-06-16T01:00:00Z
    planning_mode: intent
    ---
    ## Intent
    Narrative for a three-criterion plan.
    ## Acceptance checklist
    - [ ] Criterion alpha: command exits 0 on valid input
    - [ ] Criterion beta: output contains the slug value
    - [ ] Criterion gamma: LEDGER.md is append-only (no lines deleted)
""")

_LEDGER_CITES_CRITERION_1 = textwrap.dedent("""\
    ---
    artifact: ledger
    slug: test-eval
    intent_frozen_at: 2026-06-16T01:00:00Z
    ---
    ## Level 0
    ### Decisions
    - Added evaluate-acceptance subcommand (advances criterion #1)
    ### Deviations
    - None
""")

_LEDGER_CITES_CRITERIA_1_AND_2 = textwrap.dedent("""\
    ---
    artifact: ledger
    slug: test-eval
    intent_frozen_at: 2026-06-16T01:00:00Z
    ---
    ## Level 0
    ### Decisions
    - Added evaluate-acceptance subcommand (advances criterion #1)
    - Added per-criterion output format (advances criterion #2)
    ### Deviations
    - None
""")

_LEDGER_EMPTY_BODY = textwrap.dedent("""\
    ---
    artifact: ledger
    slug: test-eval
    intent_frozen_at: 2026-06-16T01:00:00Z
    ---
""")

_LEDGER_CITES_ALL_THREE = textwrap.dedent("""\
    ---
    artifact: ledger
    slug: test-eval
    intent_frozen_at: 2026-06-16T01:00:00Z
    ---
    ## Level 0
    ### Decisions
    - Wired evaluate-acceptance CLI (advances criterion #1)
    - Added status output format (advances criterion #2)
    ## Level 1
    ### Decisions
    - Proved append-only invariant in tests (advances criterion #3)
""")

_NONEMPTY_DIFF = textwrap.dedent("""\
    diff --git a/scripts/intent-schema.py b/scripts/intent-schema.py
    index abc123..def456 100644
    --- a/scripts/intent-schema.py
    +++ b/scripts/intent-schema.py
    @@ -1,3 +1,5 @@
    +def evaluate_acceptance(): ...
""")


def _write_tmp(content: str, suffix: str = ".md") -> Path:
    """Write content to a temp file and return its Path. Caller must delete."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    )
    f.write(content)
    f.flush()
    f.close()
    return Path(f.name)


# ---------------------------------------------------------------------------
# TestCriterionExtraction
# ---------------------------------------------------------------------------

class TestCriterionExtraction(unittest.TestCase):
    """_extract_checklist_items parses checklist section correctly."""

    def test_extracts_two_items(self):
        _fm, body = _mod._parse_frontmatter(_INTENT_TWO_CRITERIA)
        items = _extract_checklist_items(body)
        self.assertEqual(len(items), 2, f"Expected 2 items, got: {items}")

    def test_extracts_three_items(self):
        _fm, body = _mod._parse_frontmatter(_INTENT_THREE_CRITERIA)
        items = _extract_checklist_items(body)
        self.assertEqual(len(items), 3, f"Expected 3 items, got: {items}")

    def test_checkbox_prefix_stripped(self):
        _fm, body = _mod._parse_frontmatter(_INTENT_TWO_CRITERIA)
        items = _extract_checklist_items(body)
        # Should not contain checkbox chars
        for item in items:
            self.assertNotIn("[", item[:5],
                             f"Checkbox prefix not stripped from: {item!r}")

    def test_no_items_in_empty_body(self):
        items = _extract_checklist_items("## Intent\nNo checklist here.\n")
        self.assertEqual(items, [])

    def test_items_from_other_sections_excluded(self):
        """Items under ## Intent or ## Not doing must NOT be extracted."""
        body = textwrap.dedent("""\
            ## Intent
            - [ ] This is NOT in the checklist (wrong section)
            ## Acceptance checklist
            - [ ] This IS in the checklist
        """)
        items = _extract_checklist_items(body)
        self.assertEqual(len(items), 1, f"Expected 1 item, got: {items}")
        self.assertIn("This IS in the checklist", items[0])


# ---------------------------------------------------------------------------
# TestLedgerCitations
# ---------------------------------------------------------------------------

class TestLedgerCitations(unittest.TestCase):
    """_extract_ledger_cited_criteria correctly identifies criterion #N citations."""

    def test_cites_criterion_1(self):
        _fm, body = _mod._parse_frontmatter(_LEDGER_CITES_CRITERION_1)
        cited = _extract_ledger_cited_criteria(body)
        self.assertIn(1, cited, f"Expected criterion #1 cited, got: {cited}")
        self.assertNotIn(2, cited)

    def test_cites_criteria_1_and_2(self):
        _fm, body = _mod._parse_frontmatter(_LEDGER_CITES_CRITERIA_1_AND_2)
        cited = _extract_ledger_cited_criteria(body)
        self.assertIn(1, cited)
        self.assertIn(2, cited)

    def test_empty_ledger_cites_nothing(self):
        _fm, body = _mod._parse_frontmatter(_LEDGER_EMPTY_BODY)
        cited = _extract_ledger_cited_criteria(body)
        self.assertEqual(cited, set(), f"Expected empty set, got: {cited}")

    def test_multiple_levels_all_cited(self):
        _fm, body = _mod._parse_frontmatter(_LEDGER_CITES_ALL_THREE)
        cited = _extract_ledger_cited_criteria(body)
        self.assertIn(1, cited)
        self.assertIn(2, cited)
        self.assertIn(3, cited)

    def test_case_insensitive_citation(self):
        body = "- Criterion #5 done.\n- CRITERION #6 done.\n"
        cited = _extract_ledger_cited_criteria(body)
        self.assertIn(5, cited)
        self.assertIn(6, cited)


# ---------------------------------------------------------------------------
# TestEvaluateAcceptance
# ---------------------------------------------------------------------------

class TestEvaluateAcceptance(unittest.TestCase):
    """The main evaluate_acceptance API.

    Core invariant tested:
      unknown treated as unmet — evaluator MUST NOT return verdict "done"
      when any criterion is unknown or unmet.  Premature "done" would cause
      T010's BFS loop to terminate before all criteria are provably satisfied.
    """

    def _eval(self, intent_text: str, ledger_text: str, diff_text: str | None = None):
        """Helper: write fixtures, evaluate, clean up, return AcceptanceResult."""
        intent_path = _write_tmp(intent_text)
        ledger_path = _write_tmp(ledger_text)
        diff_path = _write_tmp(diff_text, suffix=".diff") if diff_text is not None else None
        try:
            return evaluate_acceptance(intent_path, ledger_path, diff_path)
        finally:
            intent_path.unlink(missing_ok=True)
            ledger_path.unlink(missing_ok=True)
            if diff_path is not None:
                diff_path.unlink(missing_ok=True)

    # --- met cases ---

    def test_all_criteria_cited_with_diff_returns_done(self):
        """All cited + non-empty diff → all met → verdict done."""
        result = self._eval(_INTENT_TWO_CRITERIA, _LEDGER_CITES_CRITERIA_1_AND_2, _NONEMPTY_DIFF)
        self.assertEqual(result.verdict, VERDICT_DONE,
                         f"Expected done, criteria: {result.criteria}")
        for cr in result.criteria:
            self.assertEqual(cr.status, STATUS_MET, f"Expected met for criterion {cr.number}")

    def test_three_criteria_all_cited_with_diff_returns_done(self):
        result = self._eval(_INTENT_THREE_CRITERIA, _LEDGER_CITES_ALL_THREE, _NONEMPTY_DIFF)
        self.assertEqual(result.verdict, VERDICT_DONE,
                         f"Expected done, criteria: {result.criteria}")

    # --- unmet cases ---

    def test_no_ledger_citations_all_unmet_continues(self):
        """Empty ledger → all criteria unmet → continue."""
        result = self._eval(_INTENT_TWO_CRITERIA, _LEDGER_EMPTY_BODY, _NONEMPTY_DIFF)
        self.assertEqual(result.verdict, VERDICT_CONTINUE)
        for cr in result.criteria:
            self.assertEqual(cr.status, STATUS_UNMET,
                             f"Criterion {cr.number} should be unmet, got {cr.status}")

    def test_partial_citation_is_continue(self):
        """One criterion cited, one not → verdict continue (not done)."""
        result = self._eval(_INTENT_TWO_CRITERIA, _LEDGER_CITES_CRITERION_1, _NONEMPTY_DIFF)
        self.assertEqual(result.verdict, VERDICT_CONTINUE)
        # criterion 1 is met, criterion 2 is unmet
        c1 = next(c for c in result.criteria if c.number == 1)
        c2 = next(c for c in result.criteria if c.number == 2)
        self.assertEqual(c1.status, STATUS_MET)
        self.assertEqual(c2.status, STATUS_UNMET)

    # --- unknown cases (HARD RULE: unknown == unmet for verdict) ---

    def test_cited_no_diff_is_unknown_not_done(self):
        """Cited in LEDGER but no diff file → unknown, NOT met → verdict continue.

        This is the key conservative invariant: without a diff we cannot confirm
        code was actually changed, so the criterion remains unknown.  The evaluator
        MUST return continue, not done, even if all criteria are cited.
        """
        result = self._eval(_INTENT_TWO_CRITERIA, _LEDGER_CITES_CRITERIA_1_AND_2, None)
        self.assertEqual(result.verdict, VERDICT_CONTINUE,
                         "HARD RULE VIOLATION: unknown should cause continue, not done")
        for cr in result.criteria:
            self.assertEqual(cr.status, STATUS_UNKNOWN,
                             f"Expected unknown (no diff) for criterion {cr.number}, "
                             f"got {cr.status}")

    def test_cited_empty_diff_is_unknown_not_done(self):
        """Cited in LEDGER but diff is empty → unknown → verdict continue."""
        result = self._eval(_INTENT_TWO_CRITERIA, _LEDGER_CITES_CRITERIA_1_AND_2, "")
        self.assertEqual(result.verdict, VERDICT_CONTINUE,
                         "HARD RULE VIOLATION: unknown (empty diff) should cause continue")
        for cr in result.criteria:
            self.assertEqual(cr.status, STATUS_UNKNOWN,
                             f"Expected unknown (empty diff) for criterion {cr.number}")

    def test_cited_nonexistent_diff_path_is_unknown(self):
        """Diff path provided but file does not exist → unknown → continue."""
        intent_path = _write_tmp(_INTENT_TWO_CRITERIA)
        ledger_path = _write_tmp(_LEDGER_CITES_CRITERIA_1_AND_2)
        fake_diff = Path("/tmp/does-not-exist-t024-test.diff")
        try:
            result = evaluate_acceptance(intent_path, ledger_path, fake_diff)
            self.assertEqual(result.verdict, VERDICT_CONTINUE)
            for cr in result.criteria:
                self.assertEqual(cr.status, STATUS_UNKNOWN)
        finally:
            intent_path.unlink(missing_ok=True)
            ledger_path.unlink(missing_ok=True)

    # --- mixed: some unknown + some unmet ---

    def test_partially_cited_no_diff_continues(self):
        """Criterion #1 cited (no diff → unknown), criterion #2 uncited (unmet) → continue."""
        result = self._eval(_INTENT_TWO_CRITERIA, _LEDGER_CITES_CRITERION_1, None)
        self.assertEqual(result.verdict, VERDICT_CONTINUE)
        c1 = next(c for c in result.criteria if c.number == 1)
        c2 = next(c for c in result.criteria if c.number == 2)
        self.assertEqual(c1.status, STATUS_UNKNOWN)
        self.assertEqual(c2.status, STATUS_UNMET)

    # --- edge cases ---

    def test_empty_checklist_returns_continue(self):
        """Zero criteria → cannot be 'done' (nothing to prove) → continue."""
        intent_no_items = textwrap.dedent("""\
            ---
            artifact: intent
            slug: empty
            level: quick
            generated_at: 2026-06-16T00:00:00Z
            frozen_at: 2026-06-16T01:00:00Z
            planning_mode: intent
            ---
            ## Intent
            Nothing to do.
            ## Acceptance checklist
        """)
        result = self._eval(intent_no_items, _LEDGER_EMPTY_BODY, _NONEMPTY_DIFF)
        self.assertEqual(result.verdict, VERDICT_CONTINUE,
                         "Empty checklist should not claim done")
        self.assertEqual(result.criteria, [],
                         "Empty checklist should produce no criterion results")

    def test_criterion_numbers_are_1_based(self):
        """CriterionResult.number must start at 1, not 0."""
        result = self._eval(_INTENT_TWO_CRITERIA, _LEDGER_EMPTY_BODY, _NONEMPTY_DIFF)
        numbers = [c.number for c in result.criteria]
        self.assertEqual(numbers, [1, 2], f"Expected [1, 2], got {numbers}")

    def test_criterion_text_is_stripped(self):
        """CriterionResult.text must have the checkbox prefix removed."""
        result = self._eval(_INTENT_TWO_CRITERIA, _LEDGER_EMPTY_BODY)
        for cr in result.criteria:
            self.assertNotIn("[ ]", cr.text[:5],
                             f"Checkbox not stripped from text: {cr.text!r}")
            self.assertNotIn("[x]", cr.text[:5],
                             f"Checkbox not stripped from text: {cr.text!r}")


# ---------------------------------------------------------------------------
# TestEvalCLI
# ---------------------------------------------------------------------------

class TestEvalCLI(unittest.TestCase):
    """CLI entry point for evaluate-acceptance subcommand."""

    def _run_cli(self, intent_text: str, ledger_text: str, diff_text: str | None = None):
        intent_path = _write_tmp(intent_text)
        ledger_path = _write_tmp(ledger_text)
        diff_path = _write_tmp(diff_text, suffix=".diff") if diff_text is not None else None
        try:
            args = [sys.executable, _SCHEMA_PY, "evaluate-acceptance",
                    str(intent_path), str(ledger_path)]
            if diff_path:
                args.append(str(diff_path))
            return subprocess.run(args, capture_output=True, text=True)
        finally:
            intent_path.unlink(missing_ok=True)
            ledger_path.unlink(missing_ok=True)
            if diff_path:
                diff_path.unlink(missing_ok=True)

    def test_all_met_exits_0_with_done_verdict(self):
        """All criteria cited + non-empty diff → exit 0 + VERDICT: done."""
        result = self._run_cli(
            _INTENT_TWO_CRITERIA, _LEDGER_CITES_CRITERIA_1_AND_2, _NONEMPTY_DIFF
        )
        self.assertEqual(result.returncode, 0,
                         f"Expected exit 0 (done), got {result.returncode}. "
                         f"stdout: {result.stdout}")
        self.assertIn("VERDICT: done", result.stdout)

    def test_unmet_exits_1_with_continue_verdict(self):
        """At least one unmet criterion → exit 1 + VERDICT: continue."""
        result = self._run_cli(_INTENT_TWO_CRITERIA, _LEDGER_EMPTY_BODY, _NONEMPTY_DIFF)
        self.assertEqual(result.returncode, 1,
                         f"Expected exit 1 (continue), got {result.returncode}")
        self.assertIn("VERDICT: continue", result.stdout)

    def test_unknown_exits_1_not_0(self):
        """Unknown (cited but no diff) → exit 1, NOT 0.

        This is the HARD RULE test: the CLI MUST NOT exit 0 (done) when any
        criterion is unknown.  An exit 0 would falsely signal done to T010's
        BFS loop, causing premature termination.
        """
        result = self._run_cli(_INTENT_TWO_CRITERIA, _LEDGER_CITES_CRITERIA_1_AND_2, None)
        self.assertEqual(result.returncode, 1,
                         f"HARD RULE VIOLATION: unknown should exit 1 (continue), "
                         f"got {result.returncode}. stdout: {result.stdout}")
        self.assertIn("VERDICT: continue", result.stdout)

    def test_output_has_criterion_lines(self):
        """Output must contain CRITERION N: <status> lines."""
        result = self._run_cli(_INTENT_TWO_CRITERIA, _LEDGER_EMPTY_BODY, _NONEMPTY_DIFF)
        self.assertIn("CRITERION 1:", result.stdout)
        self.assertIn("CRITERION 2:", result.stdout)

    def test_missing_ledger_arg_exits_2(self):
        """Only one file arg → usage error → exit 2."""
        intent_path = _write_tmp(_INTENT_TWO_CRITERIA)
        try:
            result = subprocess.run(
                [sys.executable, _SCHEMA_PY, "evaluate-acceptance", str(intent_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2,
                             f"Expected exit 2 for missing arg, got {result.returncode}")
        finally:
            intent_path.unlink(missing_ok=True)

    def test_met_criteria_show_met_in_output(self):
        """Met criteria must show 'met' in CRITERION N: line."""
        result = self._run_cli(
            _INTENT_TWO_CRITERIA, _LEDGER_CITES_CRITERIA_1_AND_2, _NONEMPTY_DIFF
        )
        self.assertIn("met", result.stdout.lower())
        # Both should be met
        lines = result.stdout.splitlines()
        crit_lines = [l for l in lines if l.startswith("CRITERION")]
        self.assertTrue(all("met" in l for l in crit_lines),
                        f"Expected all met, got: {crit_lines}")

    def test_unmet_criteria_show_unmet_in_output(self):
        """Unmet criteria must show 'unmet' in CRITERION N: line."""
        result = self._run_cli(_INTENT_TWO_CRITERIA, _LEDGER_EMPTY_BODY, _NONEMPTY_DIFF)
        lines = result.stdout.splitlines()
        crit_lines = [l for l in lines if l.startswith("CRITERION")]
        self.assertTrue(all("unmet" in l for l in crit_lines),
                        f"Expected all unmet, got: {crit_lines}")

    def test_unknown_criteria_show_unknown_in_output(self):
        """Unknown criteria (cited but no diff) must show 'unknown' in CRITERION N: line."""
        result = self._run_cli(_INTENT_TWO_CRITERIA, _LEDGER_CITES_CRITERIA_1_AND_2)
        lines = result.stdout.splitlines()
        crit_lines = [l for l in lines if l.startswith("CRITERION")]
        self.assertTrue(all("unknown" in l for l in crit_lines),
                        f"Expected all unknown, got: {crit_lines}")


if __name__ == "__main__":
    unittest.main()
