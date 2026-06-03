"""Tests for z_harness_cli/inject_safety.py (T021, F1 BLOCKER).

Covers the four acceptance behaviours:
  * clobber-abort-without-force  — a pre-existing committed AGENTS.md aborts.
  * force-backup-and-restore     — with --force, original is backed up and
                                   RESTORED byte-identical (sha256-verified).
  * idempotent-cleanup           — cleanup runs twice without raising and is a
                                   no-op after the first run.
  * orphan-detection             — doctor can detect an un-cleaned injection.

Each test git-inits a throwaway repo so _git_root() resolves a real toplevel.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from z_harness_cli.inject_safety import (  # noqa: E402
    MAGIC_MARKER,
    ClobberRefused,
    RestoreError,
    cleanup,
    detect_orphans,
    ensure_gitignored,
    manifest_path,
    preflight_targets,
)


def _git_init(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _RepoCase(unittest.TestCase):
    """Base class providing a fresh git repo per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="zh-inject-safety-")
        self.repo = Path(self._tmp.name).resolve()
        _git_init(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestClobberAbort(_RepoCase):
    def test_foreign_file_aborts_without_force(self):
        """A pre-existing non-z-harness AGENTS.md must abort without --force."""
        agents = self.repo / "AGENTS.md"
        agents.write_text("# user's committed agents file\n", encoding="utf-8")

        with self.assertRaises(ClobberRefused) as ctx:
            preflight_targets([agents], self.repo, force=False)

        # The foreign path is surfaced for the caller to print.
        self.assertIn(agents, ctx.exception.foreign)
        # And NOTHING was written / the file is untouched.
        self.assertEqual(agents.read_text(encoding="utf-8"),
                         "# user's committed agents file\n")

    def test_z_harness_authored_file_is_not_foreign(self):
        """An existing file carrying the marker is overwritable, no abort."""
        agents = self.repo / "AGENTS.md"
        agents.write_text(f"<!-- {MAGIC_MARKER} -->\nstale\n", encoding="utf-8")

        # Should NOT raise — it's our own file.
        backup_manifest = preflight_targets([agents], self.repo, force=False)
        self.assertEqual(backup_manifest, {})

    def test_absent_target_no_abort(self):
        """A target that does not exist yet never aborts."""
        agents = self.repo / "AGENTS.md"
        backup_manifest = preflight_targets([agents], self.repo, force=False)
        self.assertEqual(backup_manifest, {})


class TestForceBackupRestore(_RepoCase):
    def test_backup_and_restore_byte_identical(self):
        """With --force the original is backed up and restored byte-identical."""
        agents = self.repo / "AGENTS.md"
        original = "# user file\nline2\né unicode\n"
        agents.write_text(original, encoding="utf-8")
        original_sha = _sha(agents)

        # Pre-flight with force backs up the foreign original.
        backup_manifest = preflight_targets([agents], self.repo, force=True)
        self.assertIn(str(agents), backup_manifest)
        backup = backup_manifest[str(agents)]
        self.assertTrue(backup.exists())
        self.assertEqual(_sha(backup), original_sha)

        # Simulate the adapter overwriting the file with z-harness config.
        agents.write_text(f"<!-- {MAGIC_MARKER} -->\nz-harness content\n",
                          encoding="utf-8")
        self.assertNotEqual(_sha(agents), original_sha)

        # Cleanup restores the user's original byte-for-byte.
        cleanup(self.repo)
        self.assertTrue(agents.exists())
        self.assertEqual(_sha(agents), original_sha)
        self.assertEqual(agents.read_text(encoding="utf-8"), original)

    def test_absent_target_removed_on_cleanup(self):
        """A target that didn't pre-exist is deleted (not restored) on cleanup."""
        agents = self.repo / "AGENTS.md"
        preflight_targets([agents], self.repo, force=False)
        # Adapter writes the file.
        agents.write_text(f"<!-- {MAGIC_MARKER} -->\n", encoding="utf-8")
        self.assertTrue(agents.exists())

        cleanup(self.repo)
        self.assertFalse(agents.exists())

    def test_restore_detects_corrupt_backup(self):
        """A tampered backup fails sha256 and raises rather than restoring."""
        agents = self.repo / "AGENTS.md"
        agents.write_text("original\n", encoding="utf-8")
        backup_manifest = preflight_targets([agents], self.repo, force=True)
        backup = backup_manifest[str(agents)]

        # Corrupt the backup after the manifest recorded its sha256.
        backup.write_text("tampered\n", encoding="utf-8")
        agents.write_text(f"<!-- {MAGIC_MARKER} -->\n", encoding="utf-8")

        with self.assertRaises(RestoreError):
            cleanup(self.repo)

    def test_missing_backup_raises_and_keeps_manifest(self):
        """A restore-required entry whose backup vanished must raise, NOT
        silently skip-and-unlink (which would permanently lose the original)."""
        agents = self.repo / "AGENTS.md"
        agents.write_text("user original\n", encoding="utf-8")
        backup_manifest = preflight_targets([agents], self.repo, force=True)
        backup = backup_manifest[str(agents)]

        # Simulate the adapter overwriting, then the backup being lost (crash /
        # external deletion) while the manifest still references it.
        agents.write_text(f"<!-- {MAGIC_MARKER} -->\nz-harness\n", encoding="utf-8")
        backup.unlink()

        with self.assertRaises(RestoreError):
            cleanup(self.repo)

        # The manifest MUST survive so a later cleanup can surface / retry the
        # unresolved restore — data loss is not silently accepted.
        self.assertTrue(manifest_path(self.repo).exists())

    def test_post_restore_destination_is_verified(self):
        """The restored destination (not just the backup) is sha256-verified.

        We monkeypatch _sha256 so the backup passes its pre-check but the
        written destination reports a mismatch, simulating an interrupted /
        corrupt write.  cleanup() must raise RestoreError and leave the
        manifest in place rather than accept a corrupted destination."""
        from z_harness_cli import inject_safety as mod

        agents = self.repo / "AGENTS.md"
        agents.write_text("user original\n", encoding="utf-8")
        backup_manifest = preflight_targets([agents], self.repo, force=True)
        backup = backup_manifest[str(agents)]
        recorded_sha = _sha(backup)

        agents.write_text(f"<!-- {MAGIC_MARKER} -->\n", encoding="utf-8")

        real_sha256 = mod._sha256

        def fake_sha256(path):
            # Backup pre-check passes (matches recorded), destination temp fails.
            p = Path(path)
            if p == backup:
                return recorded_sha
            if p.name.endswith(".zh-restore.tmp"):
                return "deadbeef" * 8  # deliberately wrong destination digest
            return real_sha256(path)

        mod._sha256 = fake_sha256
        try:
            with self.assertRaises(RestoreError):
                cleanup(self.repo)
        finally:
            mod._sha256 = real_sha256

        # Manifest preserved for retry; no orphaned temp file left behind.
        self.assertTrue(manifest_path(self.repo).exists())
        self.assertEqual(
            list(agents.parent.glob("*.zh-restore.tmp")), []
        )


class TestPreflightTOCTOU(_RepoCase):
    def test_vanished_source_recorded_existed_false(self):
        """If a foreign source is deleted between the classify and backup passes
        (TOCTOU), preflight must record it as existed=False and NOT crash."""
        import json
        from z_harness_cli import inject_safety as mod

        agents = self.repo / "AGENTS.md"
        agents.write_text("user original\n", encoding="utf-8")

        real_copy2 = mod.shutil.copy2
        state = {"first": True}

        def vanishing_copy2(src, dst, *a, **kw):
            # On the first (backup) copy, delete the source first to force the
            # FileNotFoundError TOCTOU path, then fall through to the real copy
            # for any later calls (atomic restore temp copies, etc.).
            if state["first"] and Path(src) == agents:
                state["first"] = False
                Path(src).unlink()
            return real_copy2(src, dst, *a, **kw)

        mod.shutil.copy2 = vanishing_copy2
        try:
            backup_manifest = preflight_targets([agents], self.repo, force=True)
        finally:
            mod.shutil.copy2 = real_copy2

        # No crash; the vanished file is not in the backup manifest.
        self.assertNotIn(str(agents), backup_manifest)

        # And the persisted manifest records it as existed=False (nothing to
        # restore) so cleanup() will simply remove whatever lands there.
        manifest = json.loads(
            manifest_path(self.repo).read_text(encoding="utf-8")
        )
        entry = next(e for e in manifest["entries"] if e["path"] == str(agents))
        self.assertFalse(entry["existed"])
        self.assertNotIn("backup", entry)

        # cleanup() with the existed=False entry must not raise (treats it as a
        # z-harness write to remove, even though nothing is there).
        cleanup(self.repo)


class TestIdempotentCleanup(_RepoCase):
    def test_cleanup_twice_is_safe(self):
        """Cleanup must be idempotent (survives the T015 trap double-fire)."""
        agents = self.repo / "AGENTS.md"
        agents.write_text("orig\n", encoding="utf-8")
        original_sha = _sha(agents)
        preflight_targets([agents], self.repo, force=True)
        agents.write_text(f"<!-- {MAGIC_MARKER} -->\n", encoding="utf-8")

        cleanup(self.repo)
        # Manifest is gone after the first run.
        self.assertFalse(manifest_path(self.repo).exists())
        # Second run is a clean no-op (no raise, no change).
        cleanup(self.repo)
        self.assertEqual(_sha(agents), original_sha)

    def test_cleanup_no_manifest_is_noop(self):
        """Cleanup with no prior injection does nothing and does not raise."""
        cleanup(self.repo)  # must not raise


class TestOrphanDetection(_RepoCase):
    def test_orphan_detected_when_not_cleaned(self):
        """doctor sees a target still present from an un-cleaned injection."""
        agents = self.repo / "AGENTS.md"
        preflight_targets([agents], self.repo, force=False)
        agents.write_text(f"<!-- {MAGIC_MARKER} -->\n", encoding="utf-8")

        orphans = detect_orphans(self.repo)
        self.assertIn(agents, orphans)

    def test_no_orphans_after_cleanup(self):
        agents = self.repo / "AGENTS.md"
        preflight_targets([agents], self.repo, force=False)
        agents.write_text(f"<!-- {MAGIC_MARKER} -->\n", encoding="utf-8")
        cleanup(self.repo)
        self.assertEqual(detect_orphans(self.repo), [])

    def test_no_orphans_without_injection(self):
        self.assertEqual(detect_orphans(self.repo), [])


class TestGitignore(_RepoCase):
    def test_paths_appended_to_gitignore(self):
        agents = self.repo / "AGENTS.md"
        ensure_gitignored([agents], self.repo)
        gitignore = self.repo / ".gitignore"
        self.assertTrue(gitignore.exists())
        body = gitignore.read_text(encoding="utf-8")
        self.assertIn("AGENTS.md", body)
        self.assertIn(MAGIC_MARKER, body)
        # git now ignores it.
        check = subprocess.run(
            ["git", "-C", str(self.repo), "check-ignore", "-q", "AGENTS.md"],
            check=False,
        )
        self.assertEqual(check.returncode, 0)

    def test_already_ignored_path_not_duplicated(self):
        gitignore = self.repo / ".gitignore"
        gitignore.write_text("AGENTS.md\n", encoding="utf-8")
        before = gitignore.read_text(encoding="utf-8")
        ensure_gitignored([self.repo / "AGENTS.md"], self.repo)
        self.assertEqual(gitignore.read_text(encoding="utf-8"), before)


class TestNonGitFailsLoud(unittest.TestCase):
    def test_non_git_dir_raises(self):
        with tempfile.TemporaryDirectory(prefix="zh-nongit-") as tmp:
            target = Path(tmp) / "AGENTS.md"
            with self.assertRaises(RuntimeError):
                preflight_targets([target], Path(tmp), force=False)


if __name__ == "__main__":
    unittest.main()
