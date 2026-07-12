"""
Tests for T018: setup.py axioms wizard scope + CLAUDE.md pointer install.

Coverage:
  - _WIZARD_SECTIONS has exactly 8 entries and includes "axioms"
  - argparse choices for both inspect --scope and wizard --scope include "axioms"
  - _kernel_pointer_blocks_differ: pure-function logic for manual-edit detection
  - _install_kernel_pointer: fresh install appends; re-run is a no-op; manual-edit
    detection (with Z_HARNESS_NO_ASK=halt to skip prompt)
  - _ensure_gitignore_entry: first call adds; second call is a no-op (dedup)

Hermeticity: all tests redirect HOME / paths to temp dirs; no real ~/.claude/CLAUDE.md
or .gitignore in the worktree is ever touched.
"""

import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SETUP_PY = str(_REPO_ROOT / "scripts" / "setup.py")


# ---------------------------------------------------------------------------
# Helpers to import the module under test with overridden HOME
# ---------------------------------------------------------------------------

def _import_setup():
    """Import scripts/setup.py as a module (cached by importlib)."""
    spec = importlib.util.spec_from_file_location("setup_module", _SETUP_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestWizardSections(unittest.TestCase):
    """_WIZARD_SECTIONS has exactly 7 entries and includes "axioms"."""

    def setUp(self):
        self.setup = _import_setup()

    def test_wizard_sections_count(self):
        sections = self.setup._WIZARD_SECTIONS
        self.assertEqual(len(sections), 7, msg=f"Expected 7 sections, got {len(sections)}: {[s[0] for s in sections]}")

    def test_axioms_in_wizard_sections(self):
        names = [s[0] for s in self.setup._WIZARD_SECTIONS]
        self.assertIn("axioms", names)

    def test_axioms_callable(self):
        funcs = {s[0]: s[1] for s in self.setup._WIZARD_SECTIONS}
        self.assertTrue(callable(funcs["axioms"]))


class TestArgparseChoices(unittest.TestCase):
    """axioms appears in --scope choices for both inspect and wizard subcommands."""

    def _get_help(self, subcommand: str) -> str:
        result = subprocess.run(
            [sys.executable, _SETUP_PY, subcommand, "--help"],
            capture_output=True,
            text=True,
        )
        return result.stdout + result.stderr

    def test_inspect_scope_includes_axioms(self):
        help_text = self._get_help("inspect")
        self.assertIn("axioms", help_text, msg=f"'axioms' not found in inspect --help output:\n{help_text}")

    def test_wizard_scope_includes_axioms(self):
        help_text = self._get_help("wizard")
        self.assertIn("axioms", help_text, msg=f"'axioms' not found in wizard --help output:\n{help_text}")


class TestKernelPointerBlocksDiffer(unittest.TestCase):
    """Pure-function logic: _kernel_pointer_blocks_differ."""

    def setUp(self):
        self.setup = _import_setup()

    def test_canonical_matches(self):
        """Canonical block is not considered different from itself."""
        canonical = self.setup._KERNEL_POINTER_CANONICAL
        self.assertFalse(self.setup._kernel_pointer_blocks_differ(canonical))

    def test_canonical_with_trailing_newline_matches(self):
        """Trailing whitespace should not cause a false positive."""
        canonical = self.setup._KERNEL_POINTER_CANONICAL + "\n"
        self.assertFalse(self.setup._kernel_pointer_blocks_differ(canonical))

    def test_edited_block_differs(self):
        """A manually-edited block is detected as different."""
        edited = (
            "<!-- z-harness-kernel-pointer BEGIN -->\n"
            "This is a manual edit.\n"
            "<!-- z-harness-kernel-pointer END -->"
        )
        self.assertTrue(self.setup._kernel_pointer_blocks_differ(edited))

    def test_empty_block_differs(self):
        """An empty/partial block differs from canonical."""
        self.assertTrue(self.setup._kernel_pointer_blocks_differ(""))


class TestInstallKernelPointer(unittest.TestCase):
    """_install_kernel_pointer: fresh install, re-run no-op, manual-edit detection."""

    def setUp(self):
        self.setup = _import_setup()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _claude_md_path(self) -> str:
        claude_dir = os.path.join(self.tmpdir, ".claude")
        os.makedirs(claude_dir, exist_ok=True)
        return os.path.join(claude_dir, "CLAUDE.md")

    def test_fresh_install_appends(self):
        """Fresh install: marker block is appended to the file."""
        path = self._claude_md_path()
        status = self.setup._install_kernel_pointer(path)
        self.assertEqual(status, "appended")
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn(self.setup._KERNEL_POINTER_BEGIN, content)
        self.assertIn(self.setup._KERNEL_POINTER_END, content)
        self.assertIn("resolve-kernel.sh", content)

    def test_fresh_install_on_nonexistent_file(self):
        """Fresh install on a path whose file doesn't exist yet."""
        path = os.path.join(self.tmpdir, ".claude", "CLAUDE.md")
        # File doesn't exist yet
        self.assertFalse(os.path.exists(path))
        status = self.setup._install_kernel_pointer(path)
        self.assertEqual(status, "appended")
        self.assertTrue(os.path.exists(path))

    def test_rerun_is_noop(self):
        """Re-running after a fresh install is a no-op (block already matches canonical)."""
        path = self._claude_md_path()
        self.setup._install_kernel_pointer(path)  # first install
        status = self.setup._install_kernel_pointer(path)  # second run
        self.assertEqual(status, "no_op")

    def test_rerun_does_not_duplicate_block(self):
        """Re-running does not duplicate the block."""
        path = self._claude_md_path()
        self.setup._install_kernel_pointer(path)
        self.setup._install_kernel_pointer(path)
        content = Path(path).read_text(encoding="utf-8")
        begin_count = content.count(self.setup._KERNEL_POINTER_BEGIN)
        self.assertEqual(begin_count, 1, msg=f"Block was duplicated! Found {begin_count} BEGIN markers.")

    def test_manual_edit_detected_and_skipped_when_no_ask(self):
        """
        If the existing block differs from canonical AND Z_HARNESS_NO_ASK=halt,
        the function returns 'skipped' without overwriting.
        """
        path = self._claude_md_path()
        # Write a manually-edited block
        edited_content = (
            "<!-- z-harness-kernel-pointer BEGIN -->\n"
            "This line was manually edited.\n"
            "<!-- z-harness-kernel-pointer END -->\n"
        )
        Path(path).write_text(edited_content, encoding="utf-8")

        env_backup = os.environ.get("Z_HARNESS_NO_ASK")
        try:
            os.environ["Z_HARNESS_NO_ASK"] = "halt"
            status = self.setup._install_kernel_pointer(path)
        finally:
            if env_backup is None:
                os.environ.pop("Z_HARNESS_NO_ASK", None)
            else:
                os.environ["Z_HARNESS_NO_ASK"] = env_backup

        self.assertEqual(status, "skipped")
        # Confirm the manual edit was NOT overwritten
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("manually edited", content)

    def test_block_differs_triggers_diff_path(self):
        """
        _kernel_pointer_blocks_differ returns True when the block has a manual edit.
        (Tests the pure function that controls the diff/ask branch.)
        """
        edited_block = (
            "<!-- z-harness-kernel-pointer BEGIN -->\n"
            "Custom override text.\n"
            "<!-- z-harness-kernel-pointer END -->"
        )
        self.assertTrue(self.setup._kernel_pointer_blocks_differ(edited_block))

    def test_two_blocks_collapses_to_one_with_no_ask_halt_skips(self):
        """
        A CLAUDE.md with TWO marker blocks still results in 'skipped' when
        Z_HARNESS_NO_ASK=halt — no write occurs, anomaly is detected.
        """
        path = self._claude_md_path()
        # Pre-seed file with two identical canonical blocks
        canonical = self.setup._KERNEL_POINTER_CANONICAL
        initial = (
            "Some preamble content.\n\n"
            + canonical + "\n\n"
            + "Middle text.\n\n"
            + canonical + "\n"
        )
        Path(path).write_text(initial, encoding="utf-8")

        env_backup = os.environ.get("Z_HARNESS_NO_ASK")
        try:
            os.environ["Z_HARNESS_NO_ASK"] = "halt"
            status = self.setup._install_kernel_pointer(path)
        finally:
            if env_backup is None:
                os.environ.pop("Z_HARNESS_NO_ASK", None)
            else:
                os.environ["Z_HARNESS_NO_ASK"] = env_backup

        # With halt, it should skip (not write)
        self.assertEqual(status, "skipped")
        # Both blocks should still be present (no write happened)
        content = Path(path).read_text(encoding="utf-8")
        begin_count = content.count(self.setup._KERNEL_POINTER_BEGIN)
        self.assertEqual(begin_count, 2, msg="Expected 2 blocks to remain since we skipped.")

    def test_two_blocks_collapses_to_one_on_confirm(self, monkeypatch=None):
        """
        A CLAUDE.md with TWO marker blocks collapses to exactly ONE after install
        when the user confirms (simulated via mocked input returning 'y').
        """
        import unittest.mock

        path = self._claude_md_path()
        canonical = self.setup._KERNEL_POINTER_CANONICAL
        initial = (
            "Preamble.\n\n"
            + canonical + "\n\n"
            + "Middle section.\n\n"
            + canonical + "\n"
        )
        Path(path).write_text(initial, encoding="utf-8")

        env_backup = os.environ.get("Z_HARNESS_NO_ASK")
        try:
            os.environ.pop("Z_HARNESS_NO_ASK", None)
            with unittest.mock.patch("builtins.input", return_value="y"):
                status = self.setup._install_kernel_pointer(path)
        finally:
            if env_backup is None:
                os.environ.pop("Z_HARNESS_NO_ASK", None)
            else:
                os.environ["Z_HARNESS_NO_ASK"] = env_backup

        self.assertEqual(status, "updated")
        content = Path(path).read_text(encoding="utf-8")
        begin_count = content.count(self.setup._KERNEL_POINTER_BEGIN)
        self.assertEqual(begin_count, 1, msg=f"Expected exactly 1 block after collapse, got {begin_count}.")
        # Non-marker content should still be present
        self.assertIn("Preamble.", content)
        self.assertIn("Middle section.", content)

    def test_single_canonical_block_is_noop(self):
        """
        Re-running on a file that already has exactly one canonical block is a
        true no-op — no write, returns 'no_op'.
        """
        path = self._claude_md_path()
        # Install once
        self.setup._install_kernel_pointer(path)
        # Install again — must be no-op
        status = self.setup._install_kernel_pointer(path)
        self.assertEqual(status, "no_op")
        # Confirm block count stays at 1
        content = Path(path).read_text(encoding="utf-8")
        begin_count = content.count(self.setup._KERNEL_POINTER_BEGIN)
        self.assertEqual(begin_count, 1, msg=f"Expected 1 block, got {begin_count}.")

    def test_manual_edit_single_block_confirm_path(self):
        """
        Single block that differs from canonical: user confirms → 'updated' returned
        and file now contains exactly one canonical block.
        """
        import unittest.mock

        path = self._claude_md_path()
        edited_content = (
            "Existing content.\n"
            "<!-- z-harness-kernel-pointer BEGIN -->\n"
            "This line was manually edited.\n"
            "<!-- z-harness-kernel-pointer END -->\n"
            "Trailing content.\n"
        )
        Path(path).write_text(edited_content, encoding="utf-8")

        env_backup = os.environ.get("Z_HARNESS_NO_ASK")
        try:
            os.environ.pop("Z_HARNESS_NO_ASK", None)
            with unittest.mock.patch("builtins.input", return_value="y"):
                status = self.setup._install_kernel_pointer(path)
        finally:
            if env_backup is None:
                os.environ.pop("Z_HARNESS_NO_ASK", None)
            else:
                os.environ["Z_HARNESS_NO_ASK"] = env_backup

        self.assertEqual(status, "updated")
        content = Path(path).read_text(encoding="utf-8")
        # Exactly one block
        begin_count = content.count(self.setup._KERNEL_POINTER_BEGIN)
        self.assertEqual(begin_count, 1)
        # Manual edit text is gone
        self.assertNotIn("manually edited", content)
        # Canonical content is present
        self.assertIn("resolve-kernel.sh", content)
        # Surrounding non-marker content preserved
        self.assertIn("Existing content.", content)
        self.assertIn("Trailing content.", content)

    def test_manual_edit_single_block_skip_path(self):
        """
        Single block that differs from canonical + Z_HARNESS_NO_ASK=halt → 'skipped',
        original manual edit preserved.
        """
        path = self._claude_md_path()
        edited_content = (
            "<!-- z-harness-kernel-pointer BEGIN -->\n"
            "Manually edited line.\n"
            "<!-- z-harness-kernel-pointer END -->\n"
        )
        Path(path).write_text(edited_content, encoding="utf-8")

        env_backup = os.environ.get("Z_HARNESS_NO_ASK")
        try:
            os.environ["Z_HARNESS_NO_ASK"] = "halt"
            status = self.setup._install_kernel_pointer(path)
        finally:
            if env_backup is None:
                os.environ.pop("Z_HARNESS_NO_ASK", None)
            else:
                os.environ["Z_HARNESS_NO_ASK"] = env_backup

        self.assertEqual(status, "skipped")
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("Manually edited line.", content)


class TestExtractAllKernelPointerBlocks(unittest.TestCase):
    """Unit tests for _extract_all_kernel_pointer_blocks (pure function)."""

    def setUp(self):
        self.setup = _import_setup()

    def test_no_blocks_returns_empty_list(self):
        blocks = self.setup._extract_all_kernel_pointer_blocks("No markers here.")
        self.assertEqual(blocks, [])

    def test_single_block_returned(self):
        canonical = self.setup._KERNEL_POINTER_CANONICAL
        text = "Before.\n" + canonical + "\nAfter."
        blocks = self.setup._extract_all_kernel_pointer_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0], canonical)

    def test_two_blocks_both_returned(self):
        canonical = self.setup._KERNEL_POINTER_CANONICAL
        text = canonical + "\nSome text\n" + canonical
        blocks = self.setup._extract_all_kernel_pointer_blocks(text)
        self.assertEqual(len(blocks), 2)

    def test_three_blocks_all_returned(self):
        canonical = self.setup._KERNEL_POINTER_CANONICAL
        text = canonical + "\n" + canonical + "\n" + canonical
        blocks = self.setup._extract_all_kernel_pointer_blocks(text)
        self.assertEqual(len(blocks), 3)


class TestRemoveAllKernelPointerBlocks(unittest.TestCase):
    """Unit tests for _remove_all_kernel_pointer_blocks (pure function)."""

    def setUp(self):
        self.setup = _import_setup()

    def test_no_blocks_unchanged(self):
        text = "No markers here."
        result = self.setup._remove_all_kernel_pointer_blocks(text)
        self.assertEqual(result, text)

    def test_single_block_removed(self):
        canonical = self.setup._KERNEL_POINTER_CANONICAL
        text = "Before.\n" + canonical + "\nAfter."
        result = self.setup._remove_all_kernel_pointer_blocks(text)
        self.assertNotIn(self.setup._KERNEL_POINTER_BEGIN, result)
        self.assertIn("Before.", result)
        self.assertIn("After.", result)

    def test_two_blocks_both_removed(self):
        canonical = self.setup._KERNEL_POINTER_CANONICAL
        text = "A.\n" + canonical + "\nB.\n" + canonical + "\nC."
        result = self.setup._remove_all_kernel_pointer_blocks(text)
        self.assertNotIn(self.setup._KERNEL_POINTER_BEGIN, result)
        self.assertIn("A.", result)
        self.assertIn("B.", result)
        self.assertIn("C.", result)

    def test_idempotent_on_no_blocks(self):
        text = "Plain content."
        result1 = self.setup._remove_all_kernel_pointer_blocks(text)
        result2 = self.setup._remove_all_kernel_pointer_blocks(result1)
        self.assertEqual(result1, result2)


class TestEnsureGitignoreEntry(unittest.TestCase):
    """_ensure_gitignore_entry: first call adds; second call is no-op (dedup)."""

    def setUp(self):
        self.setup = _import_setup()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _gitignore_path(self) -> str:
        return os.path.join(self.tmpdir, ".gitignore")

    def test_first_call_adds_entry(self):
        """First call to _ensure_gitignore_entry adds the entry."""
        path = self._gitignore_path()
        status = self.setup._ensure_gitignore_entry(path, ".z-harness/axioms/")
        self.assertEqual(status, "added")
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn(".z-harness/axioms/", content)

    def test_second_call_is_noop(self):
        """Second call with the same entry returns 'already_present' (dedup)."""
        path = self._gitignore_path()
        self.setup._ensure_gitignore_entry(path, ".z-harness/axioms/")
        status = self.setup._ensure_gitignore_entry(path, ".z-harness/axioms/")
        self.assertEqual(status, "already_present")

    def test_second_call_does_not_duplicate_line(self):
        """The line is not duplicated on a second call."""
        path = self._gitignore_path()
        self.setup._ensure_gitignore_entry(path, ".z-harness/KERNEL.md")
        self.setup._ensure_gitignore_entry(path, ".z-harness/KERNEL.md")
        content = Path(path).read_text(encoding="utf-8")
        occurrences = content.count(".z-harness/KERNEL.md")
        self.assertEqual(occurrences, 1, msg=f"Entry duplicated! Found {occurrences} times.")

    def test_two_different_entries_both_added(self):
        """Two distinct entries can both be added without collision."""
        path = self._gitignore_path()
        s1 = self.setup._ensure_gitignore_entry(path, ".z-harness/axioms/")
        s2 = self.setup._ensure_gitignore_entry(path, ".z-harness/KERNEL.md")
        self.assertEqual(s1, "added")
        self.assertEqual(s2, "added")
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn(".z-harness/axioms/", content)
        self.assertIn(".z-harness/KERNEL.md", content)

    def test_existing_gitignore_not_duplicated(self):
        """If .gitignore already has the entry (from a prior setup run), skip."""
        path = self._gitignore_path()
        # Pre-seed with the entry (simulates the real worktree .gitignore)
        Path(path).write_text(".z-harness/axioms/\n", encoding="utf-8")
        status = self.setup._ensure_gitignore_entry(path, ".z-harness/axioms/")
        self.assertEqual(status, "already_present")


if __name__ == "__main__":
    unittest.main()
