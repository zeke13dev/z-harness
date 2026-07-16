"""Tests for deterministic retry-review finding-state transitions."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "review-finding-state.py"


def _module():
    spec = importlib.util.spec_from_file_location("review_finding_state", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_MOD = _module()


class TestReviewFindingState(unittest.TestCase):
    def test_identity_is_task_local_and_stable_across_reordering(self):
        first = _MOD.transition(
            {
                "task_id": "T002",
                "prior_findings": [],
                "current_findings": [
                    {"path": "scripts/a.py", "message": "missing guard", "severity": "high"},
                    {"path": "tests/a.py", "message": "missing regression test"},
                ],
            }
        )
        second = _MOD.transition(
            {
                "task_id": "T002",
                "prior_findings": list(reversed(first["current_findings"])),
                "current_findings": list(reversed(first["current_findings"])),
            }
        )
        self.assertEqual(
            [item["id"] for item in first["current_findings"]],
            [item["id"] for item in second["current_findings"]],
        )
        self.assertTrue(all(item["id"].startswith("T002-F") for item in second["current_findings"]))
        self.assertTrue(all(item["disposition"] == "still_open" for item in second["prior_findings"]))

    def test_prior_findings_are_resolved_or_still_open_and_new_regressions_remain(self):
        result = _MOD.transition(
            {
                "task_id": "T002",
                "prior_findings": [
                    {"path": "scripts/a.py", "message": "fix me"},
                    {"path": "scripts/b.py", "message": "keep me"},
                ],
                "current_findings": [
                    {"path": "scripts/b.py", "message": "keep me"},
                    {"path": "scripts/c.py", "message": "new regression"},
                ],
            }
        )
        dispositions = {item["message"]: item["disposition"] for item in result["prior_findings"]}
        self.assertEqual(dispositions, {"fix me": "resolved", "keep me": "still_open"})
        new = next(item for item in result["current_findings"] if item["message"] == "new regression")
        self.assertEqual(new["disposition"], "new")
        self.assertIn(new["id"], result["artifact_markdown"])

    def test_aggregate_review_preservation_is_explicit(self):
        result = _MOD.transition({"task_id": "T002", "prior_findings": [], "current_findings": []})
        self.assertEqual(result["aggregate_review"]["decision"], "unchanged")
        self.assertTrue(result["aggregate_review"]["preserved"])
        self.assertIn("Aggregate review: preserved", result["artifact_markdown"])

    def test_malformed_input_fails_closed(self):
        completed = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input=json.dumps({"task_id": "not-a-task", "prior_findings": [], "current_findings": []}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("task_id must match T###", completed.stderr)

        with self.assertRaises(_MOD.InputError):
            _MOD.transition({"task_id": "T002", "prior_findings": [{"path": "a.py"}], "current_findings": []})


if __name__ == "__main__":
    unittest.main()
