"""
tests/test_sink_audit_validate.py — pytest tests for scripts/sink-audit-validate.py

Fixture design:
  A temporary git repository is created for each test class. Two commits are made so
  that a valid ancestor→descendant SHA pair exists for check 7. All other artifacts
  (evidence, entry, verdict, diff) are placed under the temp git repo root.

Rules tested:
  Rule 1  — File exists at expected path
  Rule 2  — schema_version == 1
  Rule 3  — entry_id matches
  Rule 4  — review_verdict_path AND diff_artifact_path both exist
  Rule 5  — review_verdict == "PASS"
  Rule 6  — test_exit_code == 0
  Rule 7  — git merge-base --is-ancestor <capture_head> <verify_head>
  Rule 8  — verified_by_run is a valid run id in some plan's archive
  Rule 9  — diff_artifact_path touches at least one cited_path
  Rule 10 — verdict file references entry_id OR recommended_command
  Rule 11 — trust-root: audit_evidence.json path under z-harness/<plan>/archive/<RUN>/audit_evidence/<id>/
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(REPO_ROOT / "scripts" / "sink-audit-validate.py")

ENTRY_ID = "20260528T123456Z-fix-stale-readme-badge"
RECOMMENDED_COMMAND = '/z-do "update README badge URL"'
RUN_ID = "20260529T010000Z-verify-run"
PLAN = "test-plan"


# ── Git repo + fixture helpers ─────────────────────────────────────────────────

def _git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _make_git_repo(path: Path) -> tuple[str, str]:
    """
    Initialise a bare-minimum git repo at path with two commits.
    Returns (ancestor_sha, descendant_sha) where descendant descends from ancestor.
    """
    td = str(path)
    _git("init", cwd=td)
    _git("config", "user.email", "test@test.com", cwd=td)
    _git("config", "user.name", "Test", cwd=td)

    # First commit
    sentinel = path / "sentinel.txt"
    sentinel.write_text("first\n")
    _git("add", "sentinel.txt", cwd=td)
    _git("commit", "-m", "first commit", cwd=td)
    r1 = _git("rev-parse", "HEAD", cwd=td)
    ancestor = r1.stdout.strip()

    # Second commit
    sentinel.write_text("second\n")
    _git("add", "sentinel.txt", cwd=td)
    _git("commit", "-m", "second commit", cwd=td)
    r2 = _git("rev-parse", "HEAD", cwd=td)
    descendant = r2.stdout.strip()

    return ancestor, descendant


def _make_base_fixtures(
    repo_root: Path,
    ancestor_sha: str,
    descendant_sha: str,
) -> tuple[Path, Path, Path, Path]:
    """
    Create a valid set of fixture files inside repo_root.

    Returns (evidence_path, entry_path, verdict_path, diff_path).

    evidence_path is placed at the trust-root-compliant location:
       <repo_root>/z-harness/<PLAN>/archive/<RUN_ID>/audit_evidence/<ENTRY_ID>/audit_evidence.json
    """
    # Create the trust-root compliant path inside repo_root
    evidence_dir = (
        repo_root / "z-harness" / PLAN / "archive" / RUN_ID
        / "audit_evidence" / ENTRY_ID
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / "audit_evidence.json"

    # Verdict and diff artifacts (inside archive run dir)
    run_dir = repo_root / "z-harness" / PLAN / "archive" / RUN_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    verdict_path = run_dir / "verdict.md"
    diff_path = run_dir / "cumulative.diff"

    # Verdict references entry_id
    verdict_path.write_text(
        f"# Verdict\n\nEntry: {ENTRY_ID}\n\nAll checks PASS.\n",
        encoding="utf-8",
    )

    # Diff touches cited_paths (README.md)
    diff_path.write_text(
        "diff --git a/README.md b/README.md\n"
        "index abc..def 100644\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1 @@\n"
        "-old badge\n"
        "+new badge\n",
        encoding="utf-8",
    )

    evidence = {
        "schema_version": 1,
        "entry_id": ENTRY_ID,
        "review_verdict_path": str(verdict_path.relative_to(repo_root)),
        "review_verdict": "PASS",
        "test_exit_code": 0,
        "diff_artifact_path": str(diff_path.relative_to(repo_root)),
        "capture_head": ancestor_sha,
        "verify_head": descendant_sha,
        "verified_at": "2026-05-29T01:00:00Z",
        "verified_by_run": RUN_ID,
    }
    evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    entry = {
        "id": ENTRY_ID,
        "schema_version": 1,
        "priority": "P2",
        "name": "Fix stale README badge",
        "status": "open",
        "sink": "project",
        "created_at": "2026-05-28T12:34:56Z",
        "created_by_run": "20260528T120000Z-some-other-plan",
        "capture_head": ancestor_sha,
        "source_artifact": "z-harness/some-plan/archive/20260528T120000Z/task-T003/diff.patch",
        "prompt_page_link": f"pages/{ENTRY_ID}.md",
        "recommended_command": RECOMMENDED_COMMAND,
        "recommended_command_safe_to_retry": True,
        "cited_paths": ["README.md", "scripts/lint.sh"],
        "file_blob_hashes": {
            "README.md": "sha256:aabbcc",
            "scripts/lint.sh": "sha256:ddeeff",
        },
        "depth": 0,
        "auto_close_eligible": False,
        "completion_mode": None,
        "audit_evidence_path": None,
        "closed_at": None,
        "closed_by_run": None,
        "failure_reason": None,
        "attempt_count": 0,
        "status_history": [],
        "notion_remote_id": None,
    }
    entry_path = repo_root / "entry.json"
    entry_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")

    return evidence_path, entry_path, verdict_path, diff_path


def _run_validator(
    evidence_path: str,
    entry_path: str,
    repo_root: str,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT, evidence_path, entry_path, repo_root],
        capture_output=True,
        text=True,
    )


# ── Shared test base class ─────────────────────────────────────────────────────

class _GitRepoTestCase(unittest.TestCase):
    """Base class that sets up a temp git repo with two commits per test method."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._td.name)
        self.ancestor_sha, self.descendant_sha = _make_git_repo(self.repo_root)
        (
            self.evidence_path,
            self.entry_path,
            self.verdict_path,
            self.diff_path,
        ) = _make_base_fixtures(self.repo_root, self.ancestor_sha, self.descendant_sha)

    def tearDown(self):
        self._td.cleanup()

    def _run(self, evidence_path: str | None = None, repo_root: str | None = None) -> dict:
        ep = evidence_path or str(self.evidence_path)
        rr = repo_root or str(self.repo_root)
        r = _run_validator(ep, str(self.entry_path), rr)
        return json.loads(r.stdout), r.returncode

    def _patch_evidence(self, **kwargs) -> None:
        """Overwrite evidence JSON with patched fields."""
        ev = json.loads(self.evidence_path.read_text())
        ev.update(kwargs)
        self.evidence_path.write_text(json.dumps(ev), encoding="utf-8")

    def _patch_entry(self, **kwargs) -> None:
        entry = json.loads(self.entry_path.read_text())
        entry.update(kwargs)
        self.entry_path.write_text(json.dumps(entry), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# Baseline: all 11 checks should pass with valid fixtures
# ══════════════════════════════════════════════════════════════════════════════

class TestBaseline(_GitRepoTestCase):
    def test_all_checks_pass_on_valid_fixtures(self):
        """Valid fixtures → passed=True, exit 0."""
        result, rc = self._run()
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")
        self.assertIsNone(result["rejected_check"])
        self.assertEqual(rc, 0)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 1 — File exists at expected path
# ══════════════════════════════════════════════════════════════════════════════

class TestRule1FileExists(_GitRepoTestCase):
    def test_fail_evidence_missing(self):
        """Missing audit_evidence.json → rejected_check=1, exit 1."""
        r = _run_validator(
            "/nonexistent/audit_evidence.json",
            str(self.entry_path),
            str(self.repo_root),
        )
        result = json.loads(r.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 1)
        self.assertEqual(r.returncode, 1)

    def test_pass_file_exists(self):
        """Evidence file present → passes check 1."""
        result, rc = self._run()
        self.assertTrue(result["passed"])
        self.assertEqual(rc, 0)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 2 — schema_version == 1
# ══════════════════════════════════════════════════════════════════════════════

class TestRule2SchemaVersion(_GitRepoTestCase):
    def test_pass_schema_version_1(self):
        result, _ = self._run()
        self.assertTrue(result["passed"])

    def test_fail_schema_version_2(self):
        """schema_version=2 → rejected_check=2."""
        self._patch_evidence(schema_version=2)
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 2)
        self.assertEqual(rc, 1)

    def test_fail_schema_version_string(self):
        """schema_version='1' (string, not integer) → rejected_check=2."""
        self._patch_evidence(schema_version="1")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 2)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 3 — entry_id matches
# ══════════════════════════════════════════════════════════════════════════════

class TestRule3EntryId(_GitRepoTestCase):
    def test_pass_entry_id_matches(self):
        result, _ = self._run()
        self.assertTrue(result["passed"])

    def test_fail_entry_id_mismatch(self):
        """Mismatched entry_id → rejected_check=3."""
        self._patch_evidence(entry_id="20260101T000000Z-different-entry")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 3)
        self.assertEqual(rc, 1)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 4 — review_verdict_path AND diff_artifact_path both exist
# ══════════════════════════════════════════════════════════════════════════════

class TestRule4ArtifactsExist(_GitRepoTestCase):
    def test_pass_both_artifacts_exist(self):
        result, _ = self._run()
        self.assertTrue(result["passed"])

    def test_fail_verdict_missing(self):
        """Missing review_verdict_path → rejected_check=4."""
        self.verdict_path.unlink()
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 4)
        self.assertEqual(rc, 1)

    def test_fail_diff_missing(self):
        """Missing diff_artifact_path → rejected_check=4."""
        self.diff_path.unlink()
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 4)
        self.assertEqual(rc, 1)

    def test_fail_verdict_path_empty_string(self):
        """review_verdict_path="" → rejected_check=4 (not a crash or false-positive).

        Without the explicit empty-string guard, Path(repo_root) / "" resolves to
        repo_root itself (a directory), causing .exists() to return True and then
        .read_text() to crash with IsADirectoryError.
        """
        self._patch_evidence(review_verdict_path="")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 4)
        self.assertEqual(rc, 1)

    def test_fail_diff_path_empty_string(self):
        """diff_artifact_path="" → rejected_check=4 (not a crash or false-positive)."""
        self._patch_evidence(diff_artifact_path="")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 4)
        self.assertEqual(rc, 1)

    def test_fail_verdict_path_non_string_list(self):
        """review_verdict_path=[] (JSON array) → rejected_check=4.

        A non-string value would crash on Path(repo_root) / [] or string ops.
        The validator must reject with check 4 rather than raising an exception.
        """
        self._patch_evidence(review_verdict_path=[])
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 4)
        self.assertEqual(rc, 1)

    def test_fail_diff_path_non_string_integer(self):
        """diff_artifact_path=42 (integer) → rejected_check=4.

        Same type-safety guard: an integer is not a valid path string.
        """
        self._patch_evidence(diff_artifact_path=42)
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 4)
        self.assertEqual(rc, 1)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 5 — review_verdict == "PASS"
# ══════════════════════════════════════════════════════════════════════════════

class TestRule5ReviewVerdict(_GitRepoTestCase):
    def test_pass_verdict_pass(self):
        result, _ = self._run()
        self.assertTrue(result["passed"])

    def test_fail_verdict_fail(self):
        """review_verdict='FAIL' → rejected_check=5."""
        self._patch_evidence(review_verdict="FAIL")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 5)

    def test_fail_verdict_lowercase_pass(self):
        """review_verdict='pass' (lowercase) → rejected_check=5."""
        self._patch_evidence(review_verdict="pass")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 5)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 6 — test_exit_code == 0
# ══════════════════════════════════════════════════════════════════════════════

class TestRule6TestExitCode(_GitRepoTestCase):
    def test_pass_exit_code_0(self):
        result, _ = self._run()
        self.assertTrue(result["passed"])

    def test_fail_exit_code_1(self):
        """test_exit_code=1 → rejected_check=6."""
        self._patch_evidence(test_exit_code=1)
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 6)

    def test_fail_exit_code_zero_string(self):
        """test_exit_code='0' (string, not integer 0) → rejected_check=6."""
        self._patch_evidence(test_exit_code="0")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 6)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 7 — git merge-base --is-ancestor
# ══════════════════════════════════════════════════════════════════════════════

class TestRule7GitAncestor(_GitRepoTestCase):
    def test_pass_ancestor_relationship(self):
        """Valid ancestor → descendant in temp git repo → passes check 7."""
        result, rc = self._run()
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")
        self.assertEqual(rc, 0)

    def test_fail_reversed_ancestor(self):
        """Reversed SHAs (descendant set as capture_head) → rejected_check=7."""
        # Descendant is NOT an ancestor of ancestor
        self._patch_evidence(
            capture_head=self.descendant_sha,
            verify_head=self.ancestor_sha,
        )
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 7)

    def test_fail_invalid_sha(self):
        """Non-existent verify_head SHA → rejected_check=7."""
        self._patch_evidence(verify_head="0000000000000000000000000000000000000000")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 7)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 8 — verified_by_run is a valid run id in some plan's archive
# ══════════════════════════════════════════════════════════════════════════════

class TestRule8VerifiedByRun(_GitRepoTestCase):
    def test_pass_run_archive_exists(self):
        """Archive directory for RUN_ID exists → passes check 8."""
        result, rc = self._run()
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")

    def test_fail_run_archive_missing(self):
        """No matching archive directory → rejected_check=8."""
        self._patch_evidence(verified_by_run="20991231T235959Z-nonexistent-run")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 8)
        self.assertEqual(rc, 1)

    def test_fail_verified_by_run_empty(self):
        """Empty verified_by_run → rejected_check=8.

        Without this guard, Path(archive_dir) / "" resolves to archive_dir itself,
        making any plan's archive dir a false match.
        """
        self._patch_evidence(verified_by_run="")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 8)
        self.assertEqual(rc, 1)

    def test_fail_verified_by_run_with_path_separator(self):
        """verified_by_run containing '/' → rejected_check=8 (path traversal guard)."""
        self._patch_evidence(verified_by_run="../../etc/passwd")
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 8)
        self.assertEqual(rc, 1)

    def test_fail_verified_by_run_non_string_integer(self):
        """verified_by_run=123 (integer) → rejected_check=8.

        A non-string value crashes on string membership tests ('/' in <int>).
        """
        self._patch_evidence(verified_by_run=123)
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 8)
        self.assertEqual(rc, 1)

    def test_pass_run_archive_in_canonical_plans_layout(self):
        """Archive under z-harness/plans/<slug>/archive/<RUN>/ → passes check 8.

        The canonical layout uses z-harness/plans/ rather than the legacy
        z-harness/<slug>/ structure. Both must be discovered.
        """
        # Move the archive directory to the canonical plans layout
        canonical_plan_dir = self.repo_root / "z-harness" / "plans" / "canonical-plan"
        canonical_archive_dir = canonical_plan_dir / "archive" / RUN_ID
        canonical_archive_dir.mkdir(parents=True, exist_ok=True)

        # The evidence archive still needs to exist; we also create the trust-root
        # compliant path under the canonical layout
        canonical_evidence_dir = canonical_archive_dir / "audit_evidence" / ENTRY_ID
        canonical_evidence_dir.mkdir(parents=True, exist_ok=True)
        canonical_evidence_path = canonical_evidence_dir / "audit_evidence.json"

        # Copy verdict + diff into canonical run dir
        verdict_path = canonical_archive_dir / "verdict.md"
        diff_path = canonical_archive_dir / "cumulative.diff"
        verdict_path.write_text(
            f"# Verdict\n\nEntry: {ENTRY_ID}\n\nAll checks PASS.\n",
            encoding="utf-8",
        )
        diff_path.write_text(
            "diff --git a/README.md b/README.md\n"
            "index abc..def 100644\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -1 +1 @@\n"
            "-old badge\n"
            "+new badge\n",
            encoding="utf-8",
        )

        evidence = {
            "schema_version": 1,
            "entry_id": ENTRY_ID,
            "review_verdict_path": str(verdict_path.relative_to(self.repo_root)),
            "review_verdict": "PASS",
            "test_exit_code": 0,
            "diff_artifact_path": str(diff_path.relative_to(self.repo_root)),
            "capture_head": self.ancestor_sha,
            "verify_head": self.descendant_sha,
            "verified_at": "2026-05-29T01:00:00Z",
            "verified_by_run": RUN_ID,
        }
        canonical_evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

        r = _run_validator(
            str(canonical_evidence_path),
            str(self.entry_path),
            str(self.repo_root),
        )
        result = json.loads(r.stdout)
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")
        self.assertEqual(r.returncode, 0)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 9 — diff touches at least one cited_path
# ══════════════════════════════════════════════════════════════════════════════

class TestRule9DiffTouchesCitedPaths(_GitRepoTestCase):
    def test_pass_diff_touches_cited(self):
        """Diff touches README.md (in cited_paths) → passes check 9."""
        result, _ = self._run()
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")

    def test_fail_diff_touches_only_unrelated(self):
        """Diff only touches an unrelated file → rejected_check=9."""
        self.diff_path.write_text(
            "diff --git a/some/other/file.py b/some/other/file.py\n"
            "--- a/some/other/file.py\n"
            "+++ b/some/other/file.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n",
            encoding="utf-8",
        )
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 9)
        self.assertEqual(rc, 1)

    def test_fail_empty_cited_paths(self):
        """Entry with empty cited_paths → rejected_check=9.

        Spec requires "at least one path in cited_paths" to be touched; an empty
        cited_paths list can never satisfy that invariant so the check must reject.
        """
        self._patch_entry(cited_paths=[])
        self.diff_path.write_text(
            "diff --git a/unrelated.txt b/unrelated.txt\n"
            "--- a/unrelated.txt\n"
            "+++ b/unrelated.txt\n"
            "@@ -1 +1 @@\n"
            "-x\n"
            "+y\n",
            encoding="utf-8",
        )
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 9)
        self.assertEqual(rc, 1)

    def test_pass_dot_github_path_not_mangled(self):
        """.github/workflows/ci.yml cited path is NOT collapsed to github/workflows/ci.yml.

        lstrip("./") strips characters in any order: .github → github (wrong).
        The fixed normalization must only strip a leading "./" prefix, not
        individual '.' or '/' characters from the start.
        """
        # Make diff touch .github/workflows/ci.yml
        self.diff_path.write_text(
            "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
            "index abc..def 100644\n"
            "--- a/.github/workflows/ci.yml\n"
            "+++ b/.github/workflows/ci.yml\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n",
            encoding="utf-8",
        )
        # Set cited_paths to the dotfile path
        self._patch_entry(cited_paths=[".github/workflows/ci.yml"])
        result, rc = self._run()
        # With lstrip("./") the path becomes "github/workflows/ci.yml", causing a
        # mismatch. With the correct fix the paths match and check 9 passes.
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")
        self.assertEqual(rc, 0)

    def test_pass_dotslash_prefix_stripped_correctly(self):
        """cited_path with ./ prefix matches diff path without prefix."""
        # Diff touches README.md (no ./ prefix in diff headers)
        # cited_paths uses "./" prefix → should normalize to same value
        self._patch_entry(cited_paths=["./README.md"])
        result, rc = self._run()
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")
        self.assertEqual(rc, 0)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 10 — verdict file references entry_id OR recommended_command
# ══════════════════════════════════════════════════════════════════════════════

class TestRule10VerdictReferences(_GitRepoTestCase):
    def test_pass_verdict_contains_entry_id(self):
        """Verdict file contains entry_id (default fixture) → passes check 10."""
        result, _ = self._run()
        self.assertTrue(result["passed"])

    def test_pass_verdict_contains_recommended_command_only(self):
        """Verdict references recommended_command (not entry_id) → passes check 10."""
        self.verdict_path.write_text(
            f"# Verdict\n\nCommand: {RECOMMENDED_COMMAND}\n\nAll checks PASS.\n",
            encoding="utf-8",
        )
        result, _ = self._run()
        self.assertTrue(result["passed"])

    def test_fail_verdict_references_neither(self):
        """Verdict mentions neither entry_id nor recommended_command → rejected_check=10."""
        self.verdict_path.write_text(
            "# Verdict\n\nSome generic text with no relevant identifiers.\n",
            encoding="utf-8",
        )
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 10)
        self.assertEqual(rc, 1)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 11 — Trust-root check
# ══════════════════════════════════════════════════════════════════════════════

class TestRule11TrustRoot(_GitRepoTestCase):
    def test_pass_correct_trust_root_path(self):
        """Evidence at correct trust-root path → passes check 11."""
        result, rc = self._run()
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")

    def test_fail_evidence_directly_under_plan(self):
        """Evidence placed at z-harness/<plan>/audit_evidence.json → rejected_check=11."""
        wrong_dir = self.repo_root / "z-harness" / "some-plan"
        wrong_dir.mkdir(parents=True, exist_ok=True)
        wrong_evidence_path = wrong_dir / "audit_evidence.json"

        # Build a valid evidence blob but at the wrong location
        ev = json.loads(self.evidence_path.read_text())
        wrong_evidence_path.write_text(json.dumps(ev), encoding="utf-8")

        r = _run_validator(
            str(wrong_evidence_path),
            str(self.entry_path),
            str(self.repo_root),
        )
        result = json.loads(r.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 11)

    def test_fail_evidence_outside_repo_root(self):
        """Evidence placed outside repo_root entirely → rejected_check=11."""
        with tempfile.TemporaryDirectory() as outside_td:
            outside_path = Path(outside_td) / "audit_evidence.json"
            ev = json.loads(self.evidence_path.read_text())
            outside_path.write_text(json.dumps(ev), encoding="utf-8")

            r = _run_validator(
                str(outside_path),
                str(self.entry_path),
                str(self.repo_root),
            )
            result = json.loads(r.stdout)
            self.assertFalse(result["passed"])
            self.assertEqual(result["rejected_check"], 11)

    def test_fail_entry_id_not_in_subdir_path(self):
        """Evidence under archive but wrong entry-id subdir → rejected_check=11."""
        wrong_id_dir = (
            self.repo_root / "z-harness" / PLAN / "archive" / RUN_ID
            / "audit_evidence" / "20260101T000000Z-different-entry"
        )
        wrong_id_dir.mkdir(parents=True, exist_ok=True)
        wrong_evidence_path = wrong_id_dir / "audit_evidence.json"

        # Evidence still claims ENTRY_ID but lives under different-entry subdir
        ev = json.loads(self.evidence_path.read_text())
        wrong_evidence_path.write_text(json.dumps(ev), encoding="utf-8")

        r = _run_validator(
            str(wrong_evidence_path),
            str(self.entry_path),
            str(self.repo_root),
        )
        result = json.loads(r.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 11)

    def test_fail_wrong_filename(self):
        """Evidence file named 'not-evidence.json' instead of 'audit_evidence.json' → rejected_check=11.

        The trust-root check must validate the filename, not just the directory structure.
        Otherwise z-harness/<plan>/archive/<RUN>/audit_evidence/<entry-id>/not-evidence.json
        would pass all structural checks.
        """
        correct_dir = self.evidence_path.parent
        wrong_file = correct_dir / "not-evidence.json"
        ev = json.loads(self.evidence_path.read_text())
        wrong_file.write_text(json.dumps(ev), encoding="utf-8")

        r = _run_validator(
            str(wrong_file),
            str(self.entry_path),
            str(self.repo_root),
        )
        result = json.loads(r.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 11)

    def test_fail_wrong_run_in_path(self):
        """Evidence under a different RUN directory than verified_by_run → rejected_check=11.

        The trust-root check must verify that the archive run directory in the path
        matches verified_by_run; otherwise a file from one run could claim to belong
        to another.
        """
        other_run = "20261231T000000Z-different-run"
        other_run_dir = (
            self.repo_root / "z-harness" / PLAN / "archive" / other_run
            / "audit_evidence" / ENTRY_ID
        )
        other_run_dir.mkdir(parents=True, exist_ok=True)
        other_evidence_path = other_run_dir / "audit_evidence.json"

        # Evidence claims RUN_ID as verified_by_run but is stored under other_run
        ev = json.loads(self.evidence_path.read_text())
        other_evidence_path.write_text(json.dumps(ev), encoding="utf-8")

        r = _run_validator(
            str(other_evidence_path),
            str(self.entry_path),
            str(self.repo_root),
        )
        result = json.loads(r.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["rejected_check"], 11)

    def test_pass_canonical_plans_trust_root(self):
        """Evidence at z-harness/plans/<plan>/archive/<RUN>/... → passes check 11.

        The canonical layout uses plans/ subdirectory under z-harness. The trust-root
        check must accept both legacy (7-part) and canonical (8-part) paths.
        """
        canonical_plan_dir = self.repo_root / "z-harness" / "plans" / "canonical-plan"
        canonical_archive_dir = canonical_plan_dir / "archive" / RUN_ID
        canonical_evidence_dir = canonical_archive_dir / "audit_evidence" / ENTRY_ID
        canonical_evidence_dir.mkdir(parents=True, exist_ok=True)
        canonical_evidence_path = canonical_evidence_dir / "audit_evidence.json"

        verdict_path = canonical_archive_dir / "verdict.md"
        diff_path = canonical_archive_dir / "cumulative.diff"
        verdict_path.write_text(
            f"# Verdict\n\nEntry: {ENTRY_ID}\n\nAll checks PASS.\n",
            encoding="utf-8",
        )
        diff_path.write_text(
            "diff --git a/README.md b/README.md\n"
            "index abc..def 100644\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -1 +1 @@\n"
            "-old badge\n"
            "+new badge\n",
            encoding="utf-8",
        )
        evidence = {
            "schema_version": 1,
            "entry_id": ENTRY_ID,
            "review_verdict_path": str(verdict_path.relative_to(self.repo_root)),
            "review_verdict": "PASS",
            "test_exit_code": 0,
            "diff_artifact_path": str(diff_path.relative_to(self.repo_root)),
            "capture_head": self.ancestor_sha,
            "verify_head": self.descendant_sha,
            "verified_at": "2026-05-29T01:00:00Z",
            "verified_by_run": RUN_ID,
        }
        canonical_evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

        r = _run_validator(
            str(canonical_evidence_path),
            str(self.entry_path),
            str(self.repo_root),
        )
        result = json.loads(r.stdout)
        self.assertTrue(result["passed"], msg=f"Expected pass but got: {result}")
        self.assertEqual(r.returncode, 0)


# ══════════════════════════════════════════════════════════════════════════════
# Output format tests
# ══════════════════════════════════════════════════════════════════════════════

class TestOutputFormat(_GitRepoTestCase):
    def test_pass_output_structure(self):
        """On pass: valid JSON, passed=true, rejected_check=null, reason str, exit 0."""
        result, rc = self._run()
        self.assertIn("passed", result)
        self.assertIn("rejected_check", result)
        self.assertIn("reason", result)
        self.assertTrue(result["passed"])
        self.assertIsNone(result["rejected_check"])
        self.assertIsInstance(result["reason"], str)
        self.assertEqual(rc, 0)

    def test_fail_output_structure(self):
        """On fail: valid JSON, passed=false, rejected_check=int, reason non-empty str, exit 1."""
        self._patch_evidence(schema_version=99)
        result, rc = self._run()
        self.assertFalse(result["passed"])
        self.assertIsInstance(result["rejected_check"], int)
        self.assertIsInstance(result["reason"], str)
        self.assertGreater(len(result["reason"]), 0)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
