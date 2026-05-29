"""
tests/test_followup_confirm_audit_e2e.py — end-to-end regression tests for the
audit-confirm path (H1 fix).

Before the T002 fix, z-followup-confirm passed the WHOLE view file path to
sink-audit-validate.py instead of extracting the single entry JSON first.
sink-audit-validate.py calls entry.get("id") which returns None on the view
object ({"entries": {...}}) → check 3 always fails → audit-confirmed path-to-done
never worked.

The fix: extract the single entry object from the view and write it to a temp file,
THEN pass that temp file to sink-audit-validate.py.

These tests drive the REAL subprocess invocation of sink-audit-validate.py to verify
it receives a single-entry JSON (not the whole view).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_VALIDATE = str(REPO_ROOT / "scripts" / "sink-audit-validate.py")


def _run_validate(
    evidence_path: str,
    entry_path: str,
    repo_root: str | None = None,
) -> subprocess.CompletedProcess:
    """Invoke sink-audit-validate.py as a real subprocess."""
    cmd = [sys.executable, AUDIT_VALIDATE, evidence_path, entry_path]
    if repo_root is not None:
        cmd.append(repo_root)
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_entry_json(entry_id: str, cited_paths: list[str] | None = None) -> dict:
    return {
        "id": entry_id,
        "schema_version": 1,
        "status": "verify",
        "priority": "P2",
        "name": "test followup",
        "recommended_command": "/z-do-test",
        "cited_paths": cited_paths or [],
    }


def _make_view_json(entry_id: str, entry: dict) -> dict:
    """Return a view-file object wrapping the entry (the wrong format H1 passed)."""
    return {"entries": {entry_id: entry}}


class TestAuditValidateReceivesSingleEntry(unittest.TestCase):
    """Verify sink-audit-validate.py behaves correctly given a single-entry JSON.

    The critical H1 invariant: the validator must receive a single entry dict
    (with 'id' at top level) — NOT the whole view {"entries": {...}}.

    Failure class (H1 regression): passing the view file path causes entry.get("id")
    to return None, which makes check 3 (entry_id match) always fail.
    """

    def test_single_entry_check3_passes_entry_id(self):
        """Passing a single-entry JSON lets check 3 (entry_id match) see the correct id.

        Invariant: validator receives entry with 'id' at top level.
        Failure class (H1): validator receives the view dict which has no 'id' key
        → check 3 always rejects with 'entry_id mismatch: evidence has X, entry has None'.
        """
        entry_id = "20260101T120000Z-audit-e2e"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)

            # Create a minimal entry JSON (single entry object — correct format)
            entry = _make_entry_json(entry_id, cited_paths=["sentinel.txt"])
            entry_path = td_path / "entry.json"
            entry_path.write_text(json.dumps(entry), encoding="utf-8")

            # Build a minimal valid audit evidence (we expect checks 1-3 to reach
            # check 3; if entry_id matches, check 3 passes)
            evidence = {
                "schema_version": 1,
                "entry_id": entry_id,
                "review_verdict": "PASS",
                "test_exit_code": 0,
                "capture_head": "abc123",
                "verify_head": "abc123",
                "verified_by_run": "run-001",
                "review_verdict_path": "nonexistent-verdict.md",
                "diff_artifact_path": "nonexistent-diff.txt",
            }
            evidence_path = td_path / "audit_evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            result = _run_validate(str(evidence_path), str(entry_path), str(td_path))
            # The validator will fail at some later check (check 4: paths don't exist,
            # check 7: git merge-base, etc.) but MUST NOT fail at check 3 (entry_id mismatch).
            # The key assertion: check 3 must NOT be the rejection check.
            data = json.loads(result.stdout)
            self.assertNotEqual(
                data.get("rejected_check"), 3,
                f"check 3 (entry_id match) must pass when a single-entry JSON is provided. "
                f"H1 regression: passing the view file causes entry_id=None → check 3 fails. "
                f"result={data}",
            )

    def test_view_file_fails_check3_entry_id_is_none(self):
        """Passing the WHOLE view file to the validator causes check 3 to fail.

        This is the NEGATIVE CONTROL: this is exactly the H1 bug.
        The view object {'entries': {...}} has no 'id' key → check 3 always rejects.
        """
        entry_id = "20260101T120000Z-audit-e2e-view-bug"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)

            entry = _make_entry_json(entry_id)
            view = _make_view_json(entry_id, entry)

            # Write the WHOLE view file (wrong format — this is the H1 bug)
            view_path = td_path / "index.view.json"
            view_path.write_text(json.dumps(view), encoding="utf-8")

            evidence = {
                "schema_version": 1,
                "entry_id": entry_id,
                "review_verdict": "PASS",
                "test_exit_code": 0,
                "capture_head": "abc123",
                "verify_head": "abc123",
                "verified_by_run": "run-001",
                "review_verdict_path": "nonexistent.md",
                "diff_artifact_path": "nonexistent.txt",
            }
            evidence_path = td_path / "audit_evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            # Pass the view_path (wrong — the whole view file) as the entry argument
            result = _run_validate(str(evidence_path), str(view_path), str(td_path))
            data = json.loads(result.stdout)

            # The view file has no 'id' key → check 3 must fail with entry_id mismatch
            self.assertFalse(data["passed"], "passing the view file must fail validation")
            self.assertEqual(
                data.get("rejected_check"), 3,
                f"Passing the view file (the H1 bug) must fail at check 3 "
                f"(entry_id: evidence has {entry_id!r}, view has None). "
                f"result={data}",
            )

    def test_single_entry_passes_check1_and_check2(self):
        """A single-entry JSON with correct schema_version must clear checks 1 and 2.

        Confirms the validator can progress past the file-exists and schema_version checks.
        """
        entry_id = "20260101T120000Z-audit-checks-1-2"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)

            entry = _make_entry_json(entry_id)
            entry_path = td_path / "entry.json"
            entry_path.write_text(json.dumps(entry), encoding="utf-8")

            evidence = {
                "schema_version": 1,
                "entry_id": entry_id,
                # Minimal fields — we only care about checks 1+2 being cleared here
                "review_verdict": "PASS",
                "test_exit_code": 0,
                "capture_head": "abc123",
                "verify_head": "abc123",
                "verified_by_run": "run-001",
                "review_verdict_path": "nonexistent.md",
                "diff_artifact_path": "nonexistent.txt",
            }
            evidence_path = td_path / "audit_evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            result = _run_validate(str(evidence_path), str(entry_path), str(td_path))
            data = json.loads(result.stdout)

            # Must not fail at check 1 (file not found) or check 2 (schema_version)
            rejected = data.get("rejected_check")
            self.assertNotIn(
                rejected, (1, 2),
                f"Checks 1 and 2 must pass for a valid single-entry JSON with schema_version=1. "
                f"result={data}",
            )


class TestAuditValidateEntryExtraction(unittest.TestCase):
    """Test the extraction pattern: view → single entry → validator.

    This simulates what z-followup-confirm.md must do after the H1 fix:
    extract the entry from the view, write it to a temp file, pass that to validator.
    """

    def test_extracted_entry_passes_check3(self):
        """An entry extracted from the view and written to a temp file passes check 3.

        This simulates the corrected z-followup-confirm flow:
          1. Load index.view.json
          2. Extract entry by entry_id
          3. Write single entry to a temp file
          4. Pass temp file to sink-audit-validate.py
        """
        entry_id = "20260101T120000Z-extracted-entry"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)

            # Build the view (what z-followup-confirm reads)
            entry = _make_entry_json(entry_id, cited_paths=["sentinel.txt"])
            view = _make_view_json(entry_id, entry)
            view_path = td_path / "index.view.json"
            view_path.write_text(json.dumps(view), encoding="utf-8")

            # Simulate the H1 fix: extract the entry from the view into a temp file
            view_data = json.loads(view_path.read_text(encoding="utf-8"))
            extracted_entry = view_data["entries"][entry_id]
            temp_entry_path = td_path / "entry_extracted.json"
            temp_entry_path.write_text(json.dumps(extracted_entry), encoding="utf-8")

            evidence = {
                "schema_version": 1,
                "entry_id": entry_id,
                "review_verdict": "PASS",
                "test_exit_code": 0,
                "capture_head": "abc123",
                "verify_head": "abc123",
                "verified_by_run": "run-001",
                "review_verdict_path": "nonexistent.md",
                "diff_artifact_path": "nonexistent.txt",
            }
            evidence_path = td_path / "audit_evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            result = _run_validate(str(evidence_path), str(temp_entry_path), str(td_path))
            data = json.loads(result.stdout)

            # Check 3 must pass (entry_id matched)
            self.assertNotEqual(
                data.get("rejected_check"), 3,
                f"Extracted single-entry must pass check 3 (entry_id match). "
                f"result={data}",
            )

    def test_validator_cli_accepts_two_positional_args(self):
        """sink-audit-validate.py must exit 2 when called with < 2 positional args.

        This confirms the CLI interface: argv[1]=evidence_path, argv[2]=entry_path.
        """
        # Zero args — must exit 2 (usage error)
        result = subprocess.run(
            [sys.executable, AUDIT_VALIDATE],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode, 2,
            f"Calling validator with no args must exit 2 (usage). "
            f"stderr={result.stderr!r}",
        )

    def test_validator_missing_entry_file_fails_check1(self):
        """Passing a nonexistent entry file must fail at check 1."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)

            evidence = {"schema_version": 1, "entry_id": "xxx"}
            evidence_path = td_path / "evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            nonexistent_entry = str(td_path / "does_not_exist.json")
            result = _run_validate(str(evidence_path), nonexistent_entry, str(td_path))
            data = json.loads(result.stdout)

            self.assertFalse(data["passed"])
            self.assertEqual(data.get("rejected_check"), 1,
                             f"Missing entry file must fail at check 1; got {data}")


if __name__ == "__main__":
    unittest.main()
