"""
tests/test_sink_auto_close_check.py — pytest tests for scripts/sink-auto-close-check.py

Acceptance criteria covered:
  - zero-diff pass (mode="noop")
  - docs-allowlist pass (only docs/foo.md touched → mode="docs_only")
  - denylist veto (commands/foo.md → fail even if *.md would allowlist it)
  - mixed allow+deny fail (one path allowed, one denied)
  - test_exit non-zero fail
  - completion_mode != null fail
  - auto_close_eligible false fail
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Import the module directly so we can call run_check without subprocess
import importlib.util
spec = importlib.util.spec_from_file_location(
    "sink_auto_close_check",
    str(REPO_ROOT / "scripts" / "sink-auto-close-check.py"),
)
_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_mod)
run_check = _mod.run_check
_match_glob = _mod._match_glob
_parse_diff = _mod._parse_diff


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    tmp: Path,
    *,
    auto_close_eligible: bool = True,
    completion_mode=None,
) -> str:
    entry = {
        "id": "20260528T123456Z-test-entry",
        "schema_version": 1,
        "priority": "P3",
        "name": "Test entry",
        "status": "verify",
        "sink": "project",
        "created_at": "2026-05-28T12:34:56Z",
        "created_by_run": "20260528T120000Z-run",
        "capture_head": "abc123",
        "source_artifact": "z-harness/plan/archive/run/task.diff",
        "prompt_page_link": "pages/test.md",
        "recommended_command": '/z-do "fix docs"',
        "recommended_command_safe_to_retry": True,
        "cited_paths": ["docs/foo.md"],
        "file_blob_hashes": {"docs/foo.md": "sha256:aabbcc"},
        "depth": 0,
        "auto_close_eligible": auto_close_eligible,
        "completion_mode": completion_mode,
        "audit_evidence_path": None,
        "closed_at": None,
        "closed_by_run": None,
        "failure_reason": None,
        "attempt_count": 0,
        "status_history": [],
        "notion_remote_id": None,
    }
    p = tmp / "entry.json"
    p.write_text(json.dumps(entry), encoding="utf-8")
    return str(p)


def _make_diff(tmp: Path, content: str, filename: str = "test.diff") -> str:
    p = tmp / filename
    p.write_text(content, encoding="utf-8")
    return str(p)


def _zero_diff(tmp: Path) -> str:
    """Diff file with zero lines changed (true no-op)."""
    return _make_diff(tmp, "")


def _numstat_diff(tmp: Path, lines: list[str]) -> str:
    """Diff in git --numstat format."""
    return _make_diff(tmp, "\n".join(lines) + "\n")


def _unified_diff(tmp: Path, paths: list[str], added: int = 1, removed: int = 0) -> str:
    """Generate a minimal unified diff touching the given paths."""
    parts = []
    for p in paths:
        parts.append(f"diff --git a/{p} b/{p}")
        parts.append(f"--- a/{p}")
        parts.append(f"+++ b/{p}")
        parts.append("@@ -1 +1 @@")
        for _ in range(added):
            parts.append("+added line")
        for _ in range(removed):
            parts.append("-removed line")
    return _make_diff(tmp, "\n".join(parts) + "\n")


# ---------------------------------------------------------------------------
# Glob matching unit tests
# ---------------------------------------------------------------------------

class TestGlobMatching(unittest.TestCase):
    """Unit tests for _match_glob to verify ** semantics."""

    def test_double_star_md_matches_nested(self):
        """docs/**/*.md should match docs/sub/file.md."""
        self.assertTrue(_match_glob("docs/**/*.md", "docs/sub/file.md"))

    def test_double_star_md_matches_direct_child(self):
        """docs/**/*.md should match docs/file.md (zero intermediate segments)."""
        self.assertTrue(_match_glob("docs/**/*.md", "docs/file.md"))

    def test_double_star_md_no_match_wrong_ext(self):
        """docs/**/*.md should NOT match docs/sub/file.py."""
        self.assertFalse(_match_glob("docs/**/*.md", "docs/sub/file.py"))

    def test_single_star_md_no_match_nested(self):
        """*.md should NOT match docs/foo.md (only root-level files)."""
        self.assertFalse(_match_glob("*.md", "docs/foo.md"))

    def test_single_star_md_matches_root(self):
        """*.md should match README.md at root level."""
        self.assertTrue(_match_glob("*.md", "README.md"))

    def test_commands_double_star_md(self):
        """commands/**/*.md should match commands/z-plan.md."""
        self.assertTrue(_match_glob("commands/**/*.md", "commands/z-plan.md"))

    def test_commands_double_star_md_nested(self):
        """commands/**/*.md should match commands/sub/z-plan.md."""
        self.assertTrue(_match_glob("commands/**/*.md", "commands/sub/z-plan.md"))

    def test_double_star_only_matches_all(self):
        """**/*.md should match anything ending in .md."""
        self.assertTrue(_match_glob("**/*.md", "commands/foo.md"))
        self.assertTrue(_match_glob("**/*.md", "docs/sub/bar.md"))
        self.assertTrue(_match_glob("**/*.md", "README.md"))

    def test_no_false_positive_prefix(self):
        """docs/**/*.md should NOT match scripts/config.py."""
        self.assertFalse(_match_glob("docs/**/*.md", "scripts/config.py"))

    def test_root_anchored_md_matches_root(self):
        """/*.md (root-anchored, gitignore style) should match README.md.

        Regression for T022: the matcher strips the leading slash from the path
        but previously not from the pattern, so /*.md could never match the
        slash-less README.md, silently neutering the denylist entry."""
        self.assertTrue(_match_glob("/*.md", "README.md"))

    def test_root_anchored_md_no_match_nested(self):
        """/*.md should NOT match a nested docs/foo.md (root-anchored only)."""
        self.assertFalse(_match_glob("/*.md", "docs/foo.md"))


# ---------------------------------------------------------------------------
# run_check tests
# ---------------------------------------------------------------------------

class TestRunCheck(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    # ── Pass condition A: diff_stat == 0 ──────────────────────────────────────

    def test_zero_diff_pass(self):
        """Empty diff (diff_stat=0) → pass with mode='noop'."""
        entry = _make_entry(self.tmp)
        diff = _zero_diff(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")
        self.assertEqual(result["mode"], "noop")
        self.assertEqual(rc, 0)

    def test_zero_diff_violates_invariant_if_test_exit_nonzero(self):
        """test_exit != 0 must fail even if diff_stat == 0."""
        entry = _make_entry(self.tmp)
        diff = _zero_diff(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=1,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"])
        self.assertIsNone(result["mode"])
        self.assertEqual(rc, 1)

    # ── Pass condition B: allowlist match ─────────────────────────────────────

    def test_docs_allowlist_pass(self):
        """Only docs/foo.md touched → allowlist matches, denylist clear → pass."""
        entry = _make_entry(self.tmp)
        diff = _unified_diff(self.tmp, ["docs/sub/foo.md"])
        # Supply explicit allowlist/denylist via config by passing known patterns
        # The script calls config.py; in a tempdir without config.py it falls back
        # to spec defaults. docs/**/*.md matches docs/sub/foo.md.
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")
        self.assertEqual(result["mode"], "docs_only")
        self.assertEqual(rc, 0)

    def test_docs_allowlist_pass_numstat_format(self):
        """docs-only diff in numstat format → pass."""
        entry = _make_entry(self.tmp)
        diff = _numstat_diff(self.tmp, ["2\t1\tdocs/changelog.md"])
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")
        self.assertEqual(result["mode"], "docs_only")

    # ── Denylist veto ─────────────────────────────────────────────────────────

    def test_denylist_veto_commands_md(self):
        """commands/foo.md is in denylist → fail even though *.md might allowlist it."""
        entry = _make_entry(self.tmp)
        diff = _unified_diff(self.tmp, ["commands/foo.md"])
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"], msg=f"Expected fail but got: {result}")
        self.assertIsNone(result["mode"])
        self.assertEqual(rc, 1)
        self.assertIn("denylist", result["reason"])

    def test_denylist_veto_agents_md(self):
        """agents/reviewer.md touches denylist → fail."""
        entry = _make_entry(self.tmp)
        diff = _unified_diff(self.tmp, ["agents/reviewer.md"])
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"])
        self.assertIn("denylist", result["reason"])

    def test_denylist_veto_root_md(self):
        """README.md is in denylist (*.md) → fail."""
        entry = _make_entry(self.tmp)
        diff = _unified_diff(self.tmp, ["README.md"])
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"])
        self.assertIn("denylist", result["reason"])

    # ── Mixed allow + deny ────────────────────────────────────────────────────

    def test_mixed_allow_and_deny_fail(self):
        """One path allowed (docs/foo.md), one denied (commands/bar.md) → fail."""
        entry = _make_entry(self.tmp)
        diff = _unified_diff(self.tmp, ["docs/sub/foo.md", "commands/bar.md"])
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"], msg=f"Expected fail but got: {result}")
        self.assertEqual(rc, 1)

    def test_mixed_allow_and_noallow_fail(self):
        """One path allowed, one unmatched (scripts/config.py) → fail."""
        entry = _make_entry(self.tmp)
        diff = _unified_diff(self.tmp, ["docs/foo.md", "scripts/config.py"])
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"], msg=f"Expected fail but got: {result}")
        self.assertEqual(rc, 1)

    # ── test_exit non-zero ────────────────────────────────────────────────────

    def test_test_exit_nonzero_fail(self):
        """test_exit=2 → fail regardless of diff."""
        entry = _make_entry(self.tmp)
        diff = _unified_diff(self.tmp, ["docs/sub/foo.md"])
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=2,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"])
        self.assertIn("test_exit", result["reason"])
        self.assertEqual(rc, 1)

    def test_test_exit_nonzero_with_zero_diff_fail(self):
        """test_exit=1 even with empty diff → fail (test_exit check comes first)."""
        entry = _make_entry(self.tmp)
        diff = _zero_diff(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=1,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"])
        self.assertEqual(rc, 1)

    # ── completion_mode != null ───────────────────────────────────────────────

    def test_completion_mode_not_null_fail(self):
        """completion_mode='human_confirmed' → fail."""
        entry = _make_entry(self.tmp, completion_mode="human_confirmed")
        diff = _zero_diff(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"])
        self.assertIn("completion_mode", result["reason"])
        self.assertEqual(rc, 1)

    def test_completion_mode_audit_confirmed_fail(self):
        """completion_mode='audit_confirmed' → fail."""
        entry = _make_entry(self.tmp, completion_mode="audit_confirmed")
        diff = _zero_diff(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"])
        self.assertEqual(rc, 1)

    # ── auto_close_eligible false ─────────────────────────────────────────────

    def test_auto_close_eligible_false_fail(self):
        """auto_close_eligible=False → fail."""
        entry = _make_entry(self.tmp, auto_close_eligible=False)
        diff = _zero_diff(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"])
        self.assertIn("auto_close_eligible", result["reason"])
        self.assertEqual(rc, 1)

    # ── Output structure ──────────────────────────────────────────────────────

    def test_pass_output_has_all_keys(self):
        """Passing result has 'passed', 'reason', 'mode' keys."""
        entry = _make_entry(self.tmp)
        diff = _zero_diff(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertIn("passed", result)
        self.assertIn("reason", result)
        self.assertIn("mode", result)
        self.assertTrue(result["passed"])
        self.assertIsInstance(result["reason"], str)

    def test_fail_output_has_all_keys(self):
        """Failing result has 'passed'=false, 'reason' (non-empty), 'mode'=null."""
        entry = _make_entry(self.tmp, auto_close_eligible=False)
        diff = _zero_diff(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"])
        self.assertIsInstance(result["reason"], str)
        self.assertGreater(len(result["reason"]), 0)
        self.assertIsNone(result["mode"])


# ---------------------------------------------------------------------------
# Diff parsing unit tests
# ---------------------------------------------------------------------------

class TestDiffParsing(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_empty_diff_returns_zero_stat(self):
        diff = _make_diff(self.tmp, "")
        stat, paths = _parse_diff(diff)
        self.assertEqual(stat, 0)
        self.assertEqual(paths, [])

    def test_numstat_parses_correctly(self):
        diff = _numstat_diff(self.tmp, ["3\t1\tdocs/foo.md", "0\t2\tscripts/bar.py"])
        stat, paths = _parse_diff(diff)
        self.assertEqual(stat, 6)  # 3+1+0+2
        self.assertIn("docs/foo.md", paths)
        self.assertIn("scripts/bar.py", paths)

    def test_unified_diff_parses_paths(self):
        diff = _unified_diff(self.tmp, ["README.md", "docs/sub/guide.md"], added=2, removed=1)
        stat, paths = _parse_diff(diff)
        self.assertGreater(stat, 0)
        self.assertIn("README.md", paths)
        self.assertIn("docs/sub/guide.md", paths)

    def test_unified_diff_counts_lines(self):
        diff_content = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-old1\n"
            "-old2\n"
            "+new1\n"
            "+new2\n"
            "+new3\n"
        )
        p = self.tmp / "d.diff"
        p.write_text(diff_content, encoding="utf-8")
        stat, paths = _parse_diff(str(p))
        # 2 removed + 3 added = 5
        self.assertEqual(stat, 5)
        self.assertIn("foo.py", paths)


# ---------------------------------------------------------------------------
# Regression: binary/rename/mode-only diffs bypass allowlist (T009 v2 fixes)
# ---------------------------------------------------------------------------

class TestBinaryAndRenameEdgeCases(unittest.TestCase):
    """
    Covers the three bypass vectors fixed in T009 v2:
    1. Binary diffs (diff --git header + "Binary files differ", zero content lines)
    2. Numstat rename entries (0\\t0\\t<path>)
    3. Unified diff with +++ b/<path> but no diff --git header
    4. Mode-only change (diff --git header, no +/- content lines)
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    # -- 1. Binary diff -------------------------------------------------------

    def test_binary_diff_not_noop_denylist_checked(self):
        """
        A binary diff (diff --git header + 'Binary files differ') on a denylist
        path must NOT be treated as noop — it must fail the denylist check.

        Failure class: binary diff bypassing allowlist → silently auto-closing
        a change to a commands/*.md file without human review.
        """
        content = (
            "diff --git a/commands/foo.md b/commands/foo.md\n"
            "index aabbcc..ddeeff 100644\n"
            "Binary files a/commands/foo.md and b/commands/foo.md differ\n"
        )
        diff = _make_diff(self.tmp, content)
        entry = _make_entry(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"],
                         msg=f"Binary diff on denylist path must fail, got: {result}")
        self.assertIsNone(result["mode"])
        self.assertEqual(rc, 1)
        self.assertIn("denylist", result["reason"])

    def test_binary_diff_not_noop_allowlist_pass(self):
        """
        A binary diff on an allowlisted path (docs/**/*.md) must pass the
        allow/deny check (not be blocked as noop; not be incorrectly denied).

        This verifies the binary path is routed through allow/deny, not short-
        circuited as noop.
        """
        content = (
            "diff --git a/docs/sub/guide.md b/docs/sub/guide.md\n"
            "index aabbcc..ddeeff 100644\n"
            "Binary files a/docs/sub/guide.md and b/docs/sub/guide.md differ\n"
        )
        diff = _make_diff(self.tmp, content)
        entry = _make_entry(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        # docs/**/*.md is in the allowlist and not in the denylist
        self.assertTrue(result["passed"],
                        msg=f"Binary diff on allowlist path must pass, got: {result}")
        self.assertEqual(result["mode"], "docs_only")
        self.assertEqual(rc, 0)

    # -- 2. Numstat rename (0\t0\tpath) --------------------------------------

    def test_numstat_rename_zero_lines_not_noop(self):
        """
        A numstat line '0\\t0\\tcommands/foo.md' (rename or mode-only) must NOT
        be treated as noop — the path is touched and denylist must be checked.

        Failure class: rename bypassing allowlist → silently auto-closing a
        rename of commands/*.md as if nothing changed.
        """
        diff = _numstat_diff(self.tmp, ["0\t0\tcommands/foo.md"])
        entry = _make_entry(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"],
                         msg=f"Numstat 0/0 on denylist path must fail, got: {result}")
        self.assertIsNone(result["mode"])
        self.assertEqual(rc, 1)
        self.assertIn("denylist", result["reason"])

    def test_numstat_rename_zero_lines_allowlist_pass(self):
        """
        A numstat '0\\t0\\t' on an allowlisted docs path must pass (renamed doc
        with no content change is low-risk).
        """
        diff = _numstat_diff(self.tmp, ["0\t0\tdocs/sub/guide.md"])
        entry = _make_entry(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertTrue(result["passed"],
                        msg=f"Numstat 0/0 on allowlist path must pass, got: {result}")
        self.assertEqual(result["mode"], "docs_only")

    # -- 3. Unified diff without diff --git header ---------------------------

    def test_unified_no_git_header_paths_extracted(self):
        """
        A plain `diff -u` output (no 'diff --git' header, only '+++ b/<path>')
        must have its paths extracted and subject to allow/deny.

        Failure class: unified diff without diff --git header → paths invisible
        to allow/deny → silently auto-closing any file change.
        """
        content = (
            "--- a/commands/foo.md\n"
            "+++ b/commands/foo.md\n"
            "@@ -1 +1 @@\n"
            "-old line\n"
            "+new line\n"
        )
        diff = _make_diff(self.tmp, content)
        entry = _make_entry(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"],
                         msg=f"Unified diff (no git header) on denylist path must fail, got: {result}")
        self.assertIn("denylist", result["reason"])
        self.assertEqual(rc, 1)

    def test_unified_no_git_header_allowlist_pass(self):
        """
        A plain `diff -u` output touching only allowlisted docs path must pass.
        """
        content = (
            "--- a/docs/sub/guide.md\n"
            "+++ b/docs/sub/guide.md\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        diff = _make_diff(self.tmp, content)
        entry = _make_entry(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertTrue(result["passed"],
                        msg=f"Unified diff (no git header) on allowlist path must pass, got: {result}")
        self.assertEqual(result["mode"], "docs_only")

    # -- 4. Mode-only change (diff --git header, no content lines) -----------

    def test_mode_only_change_not_noop_denylist_checked(self):
        """
        A mode-only change (diff --git header + 'old/new mode' lines, no +/-)
        on a denylist path must NOT be treated as noop — allow/deny must run.

        Failure class: mode-only change bypassing allowlist → silently
        auto-closing a chmod on commands/*.md.
        """
        content = (
            "diff --git a/commands/foo.md b/commands/foo.md\n"
            "old mode 100644\n"
            "new mode 100755\n"
        )
        diff = _make_diff(self.tmp, content)
        entry = _make_entry(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertFalse(result["passed"],
                         msg=f"Mode-only change on denylist path must fail, got: {result}")
        self.assertIsNone(result["mode"])
        self.assertEqual(rc, 1)
        self.assertIn("denylist", result["reason"])

    def test_mode_only_change_allowlist_pass(self):
        """
        A mode-only change on an allowlisted docs path must pass.
        """
        content = (
            "diff --git a/docs/sub/guide.md b/docs/sub/guide.md\n"
            "old mode 100644\n"
            "new mode 100755\n"
        )
        diff = _make_diff(self.tmp, content)
        entry = _make_entry(self.tmp)
        result, rc = run_check(entry_path=entry, diff_path=diff, test_exit=0,
                               repo_root=str(self.tmp))
        self.assertTrue(result["passed"],
                        msg=f"Mode-only change on allowlist path must pass, got: {result}")
        self.assertEqual(result["mode"], "docs_only")


# ---------------------------------------------------------------------------
# Regression: _parse_diff unit tests for new edge cases
# ---------------------------------------------------------------------------

class TestDiffParsingEdgeCases(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_binary_diff_returns_zero_stat_with_path(self):
        """Binary diff: stat=0 but paths non-empty."""
        content = (
            "diff --git a/commands/foo.md b/commands/foo.md\n"
            "Binary files a/commands/foo.md and b/commands/foo.md differ\n"
        )
        p = self.tmp / "b.diff"
        p.write_text(content, encoding="utf-8")
        stat, paths = _parse_diff(str(p))
        self.assertEqual(stat, 0)
        self.assertIn("commands/foo.md", paths)

    def test_numstat_zero_zero_returns_path(self):
        """Numstat 0\\t0\\t<path> returns (0, [path]) not (0, [])."""
        diff = _make_diff(self.tmp, "0\t0\tcommands/foo.md\n")
        stat, paths = _parse_diff(diff)
        self.assertEqual(stat, 0)
        self.assertIn("commands/foo.md", paths)

    def test_unified_no_git_header_extracts_path(self):
        """Unified diff without diff --git header: paths extracted from +++ b/<path>."""
        content = (
            "--- a/commands/foo.md\n"
            "+++ b/commands/foo.md\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        p = self.tmp / "u.diff"
        p.write_text(content, encoding="utf-8")
        stat, paths = _parse_diff(str(p))
        self.assertGreater(stat, 0)
        self.assertIn("commands/foo.md", paths)

    def test_mode_only_change_returns_path_zero_stat(self):
        """Mode-only diff: stat=0 but paths non-empty (from diff --git header)."""
        content = (
            "diff --git a/commands/foo.md b/commands/foo.md\n"
            "old mode 100644\n"
            "new mode 100755\n"
        )
        p = self.tmp / "m.diff"
        p.write_text(content, encoding="utf-8")
        stat, paths = _parse_diff(str(p))
        self.assertEqual(stat, 0)
        self.assertIn("commands/foo.md", paths)

    def test_truly_empty_diff_returns_empty(self):
        """Truly empty diff (no headers) returns (0, [])."""
        diff = _make_diff(self.tmp, "")
        stat, paths = _parse_diff(diff)
        self.assertEqual(stat, 0)
        self.assertEqual(paths, [])


if __name__ == "__main__":
    unittest.main()
