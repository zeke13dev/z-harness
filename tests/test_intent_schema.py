"""
tests/test_intent_schema.py — Unit tests for scripts/intent-schema.py

Tests cover:
  TestFrontmatterValidation     — INTENT.md frontmatter field presence + value checks
  TestRequiredSections          — per-level required section checks
  TestCriteriaLint              — acceptance-criterion lint heuristic
  TestLedgerValidation          — LEDGER.md frontmatter checks
  TestCLI                       — CLI entry-point (validate-intent, lint-criteria, validate-ledger)
  TestValidateIntentShellHelper — session-helpers.sh validate_intent wrapper

The criterion lint invariant under test:
  A criterion containing only "runs" or "works" with no observable object MUST be
  flagged. A criterion with an observable object following MUST NOT be flagged.
  Failure class: lint passes a bare "runs"/"works" criterion → false-negative gate skip
  (acceptance criterion gate in /z-plan would let bad criteria through).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

import tempfile

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMA_PY = str(_REPO_ROOT / "scripts" / "intent-schema.py")
_HELPERS_SH = str(_REPO_ROOT / "scripts" / "session-helpers.sh")

# ---------------------------------------------------------------------------
# Helper to import the module under test (avoid sys.path pollution globally)
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
validate_intent = _mod.validate_intent
lint_criteria = _mod.lint_criteria
validate_ledger = _mod.validate_ledger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_VALID_QUICK_INTENT = textwrap.dedent("""\
    ---
    artifact: intent
    slug: test-slug
    level: quick
    generated_at: 2026-06-16T00:00:00Z
    frozen_at: pending
    planning_mode: intent
    ---
    ## Intent
    This is what the effort accomplishes.
    ## Acceptance checklist
    - [ ] The command exits 0 when given a valid input file
    - [ ] Output contains the slug value from frontmatter
""")

_VALID_STANDARD_INTENT = textwrap.dedent("""\
    ---
    artifact: intent
    slug: test-slug
    level: standard
    generated_at: 2026-06-16T00:00:00Z
    frozen_at: pending
    planning_mode: intent
    ---
    ## Intent
    This is what the effort accomplishes.
    ## Not doing
    We are not rewriting the legacy path.
    ## Consider for this
    Budget: small; tier: Sonnet.
    ## Acceptance checklist
    - [ ] The command exits 0 when given a valid input file
    - [ ] Output contains the slug value from frontmatter
""")

_VALID_DEEP_INTENT = _VALID_STANDARD_INTENT.replace("level: standard", "level: deep")

_VALID_LEDGER = textwrap.dedent("""\
    ---
    artifact: ledger
    slug: test-slug
    intent_frozen_at: 2026-06-16T01:00:00Z
    ---
    ## Level 0
    ### Decisions
    - Added validate_intent helper (advances criterion #1)
    ### Deviations
    - None
""")


def _write_tmp(content: str) -> Path:
    """Write content to a temp file and return its Path. Caller must delete."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.flush()
    f.close()
    return Path(f.name)


# ---------------------------------------------------------------------------
# TestFrontmatterValidation
# ---------------------------------------------------------------------------

class TestFrontmatterValidation(unittest.TestCase):
    """INTENT.md frontmatter field presence + value checks."""

    def test_valid_quick_intent_passes(self):
        p = _write_tmp(_VALID_QUICK_INTENT)
        try:
            result = validate_intent(p)
            self.assertTrue(result.valid, msg=result.errors)
            self.assertEqual(result.errors, [])
        finally:
            p.unlink(missing_ok=True)

    def test_valid_standard_intent_passes(self):
        p = _write_tmp(_VALID_STANDARD_INTENT)
        try:
            result = validate_intent(p)
            self.assertTrue(result.valid, msg=result.errors)
        finally:
            p.unlink(missing_ok=True)

    def test_missing_frontmatter_fails(self):
        content = "## Intent\nNo frontmatter here.\n## Acceptance checklist\n- [ ] something"
        p = _write_tmp(content)
        try:
            result = validate_intent(p)
            self.assertFalse(result.valid)
            self.assertTrue(any("frontmatter" in e.lower() for e in result.errors),
                            msg=f"Expected frontmatter error, got: {result.errors}")
        finally:
            p.unlink(missing_ok=True)

    def test_missing_required_field_artifact_fails(self):
        content = _VALID_QUICK_INTENT.replace("artifact: intent\n", "")
        p = _write_tmp(content)
        try:
            result = validate_intent(p)
            self.assertFalse(result.valid)
            self.assertTrue(any("artifact" in e for e in result.errors),
                            msg=f"Expected artifact error, got: {result.errors}")
        finally:
            p.unlink(missing_ok=True)

    def test_missing_required_field_frozen_at_fails(self):
        content = _VALID_QUICK_INTENT.replace("frozen_at: pending\n", "")
        p = _write_tmp(content)
        try:
            result = validate_intent(p)
            self.assertFalse(result.valid)
            self.assertTrue(any("frozen_at" in e for e in result.errors),
                            msg=f"Expected frozen_at error, got: {result.errors}")
        finally:
            p.unlink(missing_ok=True)

    def test_invalid_artifact_value_fails(self):
        content = _VALID_QUICK_INTENT.replace("artifact: intent", "artifact: spec")
        p = _write_tmp(content)
        try:
            result = validate_intent(p)
            self.assertFalse(result.valid)
            self.assertTrue(any("artifact" in e for e in result.errors),
                            msg=f"Expected artifact error, got: {result.errors}")
        finally:
            p.unlink(missing_ok=True)

    def test_invalid_level_value_fails(self):
        content = _VALID_QUICK_INTENT.replace("level: quick", "level: mega")
        p = _write_tmp(content)
        try:
            result = validate_intent(p)
            self.assertFalse(result.valid)
            self.assertTrue(any("level" in e for e in result.errors),
                            msg=f"Expected level error, got: {result.errors}")
        finally:
            p.unlink(missing_ok=True)

    def test_invalid_planning_mode_fails(self):
        content = _VALID_QUICK_INTENT.replace("planning_mode: intent", "planning_mode: magic")
        p = _write_tmp(content)
        try:
            result = validate_intent(p)
            self.assertFalse(result.valid)
            self.assertTrue(any("planning_mode" in e for e in result.errors),
                            msg=f"Expected planning_mode error, got: {result.errors}")
        finally:
            p.unlink(missing_ok=True)

    def test_nonexistent_file_fails(self):
        result = validate_intent(Path("/tmp/does-not-exist-intent-schema-test.md"))
        self.assertFalse(result.valid)
        self.assertTrue(any("read" in e.lower() or "cannot" in e.lower() for e in result.errors),
                        msg=f"Expected file read error, got: {result.errors}")


# ---------------------------------------------------------------------------
# TestRequiredSections
# ---------------------------------------------------------------------------

class TestRequiredSections(unittest.TestCase):
    """Per-level required section checks."""

    def test_quick_missing_checklist_fails(self):
        content = _VALID_QUICK_INTENT.replace(
            "## Acceptance checklist\n- [ ] The command exits 0 when given a valid input file\n",
            ""
        )
        p = _write_tmp(content)
        try:
            result = validate_intent(p)
            self.assertFalse(result.valid)
            self.assertTrue(
                any("checklist" in e.lower() for e in result.errors),
                msg=f"Expected checklist error, got: {result.errors}"
            )
        finally:
            p.unlink(missing_ok=True)

    def test_quick_optional_sections_not_required(self):
        # quick level should NOT require not-doing or consider-for-this
        p = _write_tmp(_VALID_QUICK_INTENT)
        try:
            result = validate_intent(p)
            self.assertTrue(result.valid, msg=result.errors)
        finally:
            p.unlink(missing_ok=True)

    def test_standard_missing_not_doing_fails(self):
        content = _VALID_STANDARD_INTENT.replace(
            "## Not doing\nWe are not rewriting the legacy path.\n", ""
        )
        p = _write_tmp(content)
        try:
            result = validate_intent(p)
            self.assertFalse(result.valid)
            self.assertTrue(
                any("not doing" in e.lower() for e in result.errors),
                msg=f"Expected not-doing error, got: {result.errors}"
            )
        finally:
            p.unlink(missing_ok=True)

    def test_standard_missing_consider_fails(self):
        content = _VALID_STANDARD_INTENT.replace(
            "## Consider for this\nBudget: small; tier: Sonnet.\n", ""
        )
        p = _write_tmp(content)
        try:
            result = validate_intent(p)
            self.assertFalse(result.valid)
            self.assertTrue(
                any("consider" in e.lower() for e in result.errors),
                msg=f"Expected consider error, got: {result.errors}"
            )
        finally:
            p.unlink(missing_ok=True)

    def test_deep_requires_same_sections_as_standard(self):
        # deep should require the same L2+ sections as standard
        content_ok = _VALID_DEEP_INTENT
        p_ok = _write_tmp(content_ok)
        try:
            result = validate_intent(p_ok)
            self.assertTrue(result.valid, msg=result.errors)
        finally:
            p_ok.unlink(missing_ok=True)

        content_bad = _VALID_DEEP_INTENT.replace(
            "## Not doing\nWe are not rewriting the legacy path.\n", ""
        )
        p_bad = _write_tmp(content_bad)
        try:
            result = validate_intent(p_bad)
            self.assertFalse(result.valid)
        finally:
            p_bad.unlink(missing_ok=True)

    def test_standard_all_sections_present_passes(self):
        p = _write_tmp(_VALID_STANDARD_INTENT)
        try:
            result = validate_intent(p)
            self.assertTrue(result.valid, msg=result.errors)
        finally:
            p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TestCriteriaLint
# ---------------------------------------------------------------------------

class TestCriteriaLint(unittest.TestCase):
    """Acceptance-criterion lint heuristic.

    Invariant: bare 'runs'/'works' criteria with no observable object MUST be
    flagged. Criteria with an observable object following MUST NOT be flagged.
    Failure class: lint passes a bare verb → false-negative gate skip.
    """

    def _make_intent_with_criteria(self, *criteria: str, level: str = "quick") -> str:
        lines = "\n".join(f"- [ ] {c}" for c in criteria)
        if level == "quick":
            sections = f"## Intent\nNarrative.\n## Acceptance checklist\n{lines}\n"
        else:
            sections = (
                f"## Intent\nNarrative.\n"
                f"## Not doing\nNothing.\n"
                f"## Consider for this\nBudget: small.\n"
                f"## Acceptance checklist\n{lines}\n"
            )
        return textwrap.dedent(f"""\
            ---
            artifact: intent
            slug: lint-test
            level: {level}
            generated_at: 2026-06-16T00:00:00Z
            frozen_at: pending
            planning_mode: intent
            ---
            {sections}""")

    # --- Bare verb (MUST be flagged) ---

    def test_bare_runs_alone_is_flagged(self):
        """'runs' alone (no observable object) must be flagged."""
        p = _write_tmp(self._make_intent_with_criteria("runs"))
        try:
            failures = lint_criteria(p)
            self.assertTrue(len(failures) > 0,
                            "Expected lint failure for bare 'runs' criterion")
        finally:
            p.unlink(missing_ok=True)

    def test_bare_works_alone_is_flagged(self):
        """'works' alone must be flagged."""
        p = _write_tmp(self._make_intent_with_criteria("works"))
        try:
            failures = lint_criteria(p)
            self.assertTrue(len(failures) > 0,
                            "Expected lint failure for bare 'works' criterion")
        finally:
            p.unlink(missing_ok=True)

    def test_runs_with_only_filler_is_flagged(self):
        """'runs correctly' with no observable object must be flagged."""
        p = _write_tmp(self._make_intent_with_criteria("runs correctly"))
        try:
            failures = lint_criteria(p)
            self.assertTrue(len(failures) > 0,
                            "Expected lint failure for 'runs correctly'")
        finally:
            p.unlink(missing_ok=True)

    def test_works_as_expected_is_flagged(self):
        """'works as expected' is bare (filler only) and must be flagged."""
        p = _write_tmp(self._make_intent_with_criteria("works as expected"))
        try:
            failures = lint_criteria(p)
            self.assertTrue(len(failures) > 0,
                            "Expected lint failure for 'works as expected'")
        finally:
            p.unlink(missing_ok=True)

    def test_system_runs_without_errors_is_flagged(self):
        """'system runs without errors' — 'without errors' is filler — must be flagged."""
        p = _write_tmp(self._make_intent_with_criteria("system runs without errors"))
        try:
            failures = lint_criteria(p)
            self.assertTrue(len(failures) > 0,
                            "Expected lint failure for 'system runs without errors'")
        finally:
            p.unlink(missing_ok=True)

    # --- Observable criteria (MUST NOT be flagged) ---

    def test_runs_and_exits_0_is_not_flagged(self):
        """'runs and exits 0' has an observable outcome — must NOT be flagged."""
        p = _write_tmp(self._make_intent_with_criteria("the command runs and exits 0"))
        try:
            failures = lint_criteria(p)
            self.assertEqual(failures, [],
                             f"Expected no failures for observable criterion, got: {failures}")
        finally:
            p.unlink(missing_ok=True)

    def test_runs_the_tests_is_not_flagged(self):
        """'runs the tests' has a noun object — must NOT be flagged."""
        p = _write_tmp(self._make_intent_with_criteria("runs the tests"))
        try:
            failures = lint_criteria(p)
            self.assertEqual(failures, [],
                             f"Expected no failures for 'runs the tests', got: {failures}")
        finally:
            p.unlink(missing_ok=True)

    def test_works_with_spec_is_not_flagged(self):
        """'works with the spec' has a preposition phrase — must NOT be flagged."""
        p = _write_tmp(self._make_intent_with_criteria("validate-intent works with a valid INTENT.md"))
        try:
            failures = lint_criteria(p)
            self.assertEqual(failures, [],
                             f"Expected no failures for 'works with...', got: {failures}")
        finally:
            p.unlink(missing_ok=True)

    def test_observable_criterion_no_bare_verb_not_flagged(self):
        """Criteria with no bare verb at all must not be flagged."""
        p = _write_tmp(self._make_intent_with_criteria(
            "The command exits 0 when given a valid INTENT.md file",
            "Output contains the slug value from frontmatter",
        ))
        try:
            failures = lint_criteria(p)
            self.assertEqual(failures, [],
                             f"Unexpected failures: {failures}")
        finally:
            p.unlink(missing_ok=True)

    def test_multiple_criteria_one_bare_flags_only_that_line(self):
        """With mixed criteria, only the bare-verb ones are flagged."""
        p = _write_tmp(self._make_intent_with_criteria(
            "The command exits 0 on valid input",
            "runs",
            "Output contains the slug",
        ))
        try:
            failures = lint_criteria(p)
            self.assertEqual(len(failures), 1,
                             f"Expected exactly 1 failure, got: {failures}")
            self.assertIn("runs", failures[0].text)
        finally:
            p.unlink(missing_ok=True)

    def test_lint_returns_correct_line_numbers(self):
        """LintFailure.line_number must point to the offending line (1-based)."""
        content = textwrap.dedent("""\
            ---
            artifact: intent
            slug: lineno-test
            level: quick
            generated_at: 2026-06-16T00:00:00Z
            frozen_at: pending
            planning_mode: intent
            ---
            ## Intent
            Something.
            ## Acceptance checklist
            - [ ] exits 0 on valid input
            - [ ] runs
            - [ ] output matches expected
        """)
        p = _write_tmp(content)
        try:
            failures = lint_criteria(p)
            self.assertEqual(len(failures), 1, f"Got: {failures}")
            # Line 13 is "- [ ] runs" in the above content (1-based)
            self.assertEqual(failures[0].line_number, 13,
                             f"Expected line 13, got line {failures[0].line_number}")
        finally:
            p.unlink(missing_ok=True)

    def test_lint_only_checks_within_checklist_section(self):
        """Bare 'runs' in the Intent section body must NOT be flagged (only checklist)."""
        content = textwrap.dedent("""\
            ---
            artifact: intent
            slug: section-test
            level: quick
            generated_at: 2026-06-16T00:00:00Z
            frozen_at: pending
            planning_mode: intent
            ---
            ## Intent
            The system runs the pipeline on demand.
            ## Acceptance checklist
            - [ ] The pipeline exits 0 on a valid config
        """)
        p = _write_tmp(content)
        try:
            failures = lint_criteria(p)
            self.assertEqual(failures, [],
                             f"Expected no failures (bare verb in Intent section, not checklist): {failures}")
        finally:
            p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TestLedgerValidation
# ---------------------------------------------------------------------------

class TestLedgerValidation(unittest.TestCase):
    """LEDGER.md frontmatter checks."""

    def test_valid_ledger_passes(self):
        p = _write_tmp(_VALID_LEDGER)
        try:
            result = validate_ledger(p)
            self.assertTrue(result.valid, msg=result.errors)
        finally:
            p.unlink(missing_ok=True)

    def test_missing_artifact_fails(self):
        content = _VALID_LEDGER.replace("artifact: ledger\n", "")
        p = _write_tmp(content)
        try:
            result = validate_ledger(p)
            self.assertFalse(result.valid)
            self.assertTrue(any("artifact" in e for e in result.errors),
                            msg=result.errors)
        finally:
            p.unlink(missing_ok=True)

    def test_missing_intent_frozen_at_fails(self):
        content = _VALID_LEDGER.replace("intent_frozen_at: 2026-06-16T01:00:00Z\n", "")
        p = _write_tmp(content)
        try:
            result = validate_ledger(p)
            self.assertFalse(result.valid)
            self.assertTrue(any("intent_frozen_at" in e for e in result.errors),
                            msg=result.errors)
        finally:
            p.unlink(missing_ok=True)

    def test_wrong_artifact_value_fails(self):
        content = _VALID_LEDGER.replace("artifact: ledger", "artifact: intent")
        p = _write_tmp(content)
        try:
            result = validate_ledger(p)
            self.assertFalse(result.valid)
        finally:
            p.unlink(missing_ok=True)

    def test_missing_slug_fails(self):
        content = _VALID_LEDGER.replace("slug: test-slug\n", "")
        p = _write_tmp(content)
        try:
            result = validate_ledger(p)
            self.assertFalse(result.valid)
            self.assertTrue(any("slug" in e for e in result.errors),
                            msg=result.errors)
        finally:
            p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# TestCLI
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):
    """CLI entry-point tests via subprocess."""

    def _run_cli(self, *args: str, content: str = None, file_path: str = None):
        import os
        if content is not None:
            p = _write_tmp(content)
            try:
                result = subprocess.run(
                    [sys.executable, _SCHEMA_PY] + list(args) + [str(p)],
                    capture_output=True,
                    text=True,
                )
            finally:
                p.unlink(missing_ok=True)
        else:
            result = subprocess.run(
                [sys.executable, _SCHEMA_PY] + list(args) + ([file_path] if file_path else []),
                capture_output=True,
                text=True,
            )
        return result

    def test_validate_intent_valid_exits_0(self):
        result = self._run_cli("validate-intent", content=_VALID_QUICK_INTENT)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("OK", result.stdout)

    def test_validate_intent_invalid_exits_1(self):
        content = _VALID_QUICK_INTENT.replace("artifact: intent\n", "")
        result = self._run_cli("validate-intent", content=content)
        self.assertEqual(result.returncode, 1, msg=result.stdout)

    def test_lint_criteria_clean_exits_0(self):
        result = self._run_cli("lint-criteria", content=_VALID_QUICK_INTENT)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_lint_criteria_bare_runs_exits_1(self):
        import textwrap
        content = textwrap.dedent("""\
            ---
            artifact: intent
            slug: cli-test
            level: quick
            generated_at: 2026-06-16T00:00:00Z
            frozen_at: pending
            planning_mode: intent
            ---
            ## Intent
            Something.
            ## Acceptance checklist
            - [ ] runs
        """)
        result = self._run_cli("lint-criteria", content=content)
        self.assertEqual(result.returncode, 1, msg=result.stdout)
        self.assertIn("LINE", result.stdout)

    def test_validate_ledger_valid_exits_0(self):
        result = self._run_cli("validate-ledger", content=_VALID_LEDGER)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_validate_ledger_invalid_exits_1(self):
        content = _VALID_LEDGER.replace("artifact: ledger\n", "")
        result = self._run_cli("validate-ledger", content=content)
        self.assertEqual(result.returncode, 1, msg=result.stdout)

    def test_no_args_exits_2(self):
        result = subprocess.run(
            [sys.executable, _SCHEMA_PY],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)

    def test_unknown_command_exits_2(self):
        result = self._run_cli("no-such-command", content=_VALID_QUICK_INTENT)
        self.assertEqual(result.returncode, 2)


# ---------------------------------------------------------------------------
# TestValidateIntentShellHelper
# ---------------------------------------------------------------------------

class TestValidateIntentShellHelper(unittest.TestCase):
    """session-helpers.sh validate_intent wrapper tests."""

    def _run_sh(self, *args: str, content: str = None):
        if content is not None:
            p = _write_tmp(content)
            try:
                result = subprocess.run(
                    ["bash", _HELPERS_SH, "validate_intent", str(p)] + list(args),
                    capture_output=True,
                    text=True,
                )
            finally:
                p.unlink(missing_ok=True)
        else:
            result = subprocess.run(
                ["bash", _HELPERS_SH, "validate_intent"] + list(args),
                capture_output=True,
                text=True,
            )
        return result

    def test_shell_helper_valid_intent_exits_0(self):
        result = self._run_sh(content=_VALID_QUICK_INTENT)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_shell_helper_invalid_intent_exits_1(self):
        content = _VALID_QUICK_INTENT.replace("artifact: intent\n", "")
        result = self._run_sh(content=content)
        self.assertEqual(result.returncode, 1, msg=result.stdout)

    def test_shell_helper_lint_mode_clean_exits_0(self):
        result = self._run_sh("lint", content=_VALID_QUICK_INTENT)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_shell_helper_lint_mode_bare_verb_exits_1(self):
        import textwrap
        content = textwrap.dedent("""\
            ---
            artifact: intent
            slug: sh-test
            level: quick
            generated_at: 2026-06-16T00:00:00Z
            frozen_at: pending
            planning_mode: intent
            ---
            ## Intent
            Something.
            ## Acceptance checklist
            - [ ] works
        """)
        result = self._run_sh("lint", content=content)
        self.assertEqual(result.returncode, 1, msg=result.stdout)

    def test_shell_helper_is_registered_in_case_statement(self):
        """validate_intent must be in the case statement — calling it via CLI must not produce 'Unknown function'."""
        # Use a non-existent file: should fail with a read error (exit 1), NOT
        # "Unknown function" (which would indicate it's not wired up in the case statement).
        result = subprocess.run(
            ["bash", _HELPERS_SH, "validate_intent", "/tmp/nonexistent-intent-test-file.md"],
            capture_output=True,
            text=True,
        )
        # Should NOT print "Unknown function"
        self.assertNotIn("Unknown function", result.stdout + result.stderr,
                         msg="validate_intent not found in session-helpers.sh case statement")
        # Should exit 1 (validation error) not 127 or 2 (bad usage)
        self.assertEqual(result.returncode, 1,
                         msg=f"Expected exit 1 for missing file, got {result.returncode}. "
                             f"stderr: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
