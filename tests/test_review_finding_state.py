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
        explicitly_carried = [
            {
                "id": item["id"],
                "path": item["path"],
                "message": item["message"],
                "severity": item["severity"],
            }
            for item in reversed(first["current_findings"])
        ]
        second = _MOD.transition(
            {
                "task_id": "T002",
                "prior_findings": list(reversed(first["current_findings"])),
                "current_findings": explicitly_carried,
            }
        )
        self.assertEqual(
            [item["id"] for item in first["current_findings"]],
            [item["id"] for item in second["current_findings"]],
        )
        self.assertTrue(all(item["id"].startswith("T002-F") for item in second["current_findings"]))
        self.assertTrue(all(item["disposition"] == "still_open" for item in second["prior_findings"]))

    def test_prior_findings_are_resolved_or_still_open_and_new_regressions_remain(self):
        fixed_id = "T002-F0000000000000001"
        open_id = "T002-F0000000000000002"
        result = _MOD.transition(
            {
                "task_id": "T002",
                "prior_findings": [
                    {"id": fixed_id, "path": "scripts/a.py", "message": "fix me"},
                    {"id": open_id, "path": "scripts/b.py", "message": "keep me"},
                ],
                "current_findings": [
                    {"id": open_id, "path": "scripts/b.py", "message": "keep me"},
                    {"path": "scripts/c.py", "message": "new regression"},
                ],
            }
        )
        dispositions = {item["message"]: item["disposition"] for item in result["prior_findings"]}
        self.assertEqual(dispositions, {"fix me": "resolved", "keep me": "still_open"})
        new = next(item for item in result["current_findings"] if item["message"] == "new regression")
        self.assertEqual(new["disposition"], "new")
        self.assertIn(new["id"], result["artifact_markdown"])

    def test_omitted_identical_current_id_is_new_and_resolves_prior_collision(self):
        first = _MOD.transition(
            {
                "task_id": "T002",
                "prior_findings": [],
                "current_findings": [
                    {"path": "scripts/a.py", "message": "identical", "severity": "major"}
                ],
            }
        )
        prior_id = first["current_findings"][0]["id"]

        second = _MOD.transition(
            {
                "task_id": "T002",
                "prior_findings": first["current_findings"],
                "current_findings": [
                    {"path": "scripts/a.py", "message": "identical", "severity": "major"}
                ],
            }
        )

        self.assertEqual(second["prior_findings"][0]["disposition"], "resolved")
        self.assertEqual(second["prior_findings"][0]["id"], prior_id)
        self.assertEqual(second["current_findings"][0]["disposition"], "new")
        self.assertNotEqual(second["current_findings"][0]["id"], prior_id)
        repeated = _MOD.transition(
            {
                "task_id": "T002",
                "prior_findings": first["current_findings"],
                "current_findings": [
                    {"path": "scripts/a.py", "message": "identical", "severity": "major"}
                ],
            }
        )
        self.assertEqual(second["current_findings"][0]["id"], repeated["current_findings"][0]["id"])

    def test_explicit_prior_id_survives_rewording_and_severity_change(self):
        first = _MOD.transition(
            {
                "task_id": "T-REV-003",
                "prior_findings": [],
                "current_findings": [
                    {"path": "scripts/a.py", "message": "missing guard", "severity": "major"}
                ],
            }
        )
        stable_id = first["current_findings"][0]["id"]
        second = _MOD.transition(
            {
                "task_id": "T-REV-003",
                "prior_findings": first["current_findings"],
                "current_findings": [
                    {
                        "id": stable_id,
                        "path": "scripts/a.py",
                        "message": "guard still permits the invalid transition",
                        "severity": "blocker",
                    }
                ],
            }
        )
        self.assertEqual(second["current_findings"][0]["id"], stable_id)
        self.assertEqual(second["current_findings"][0]["disposition"], "still_open")
        self.assertEqual(second["prior_findings"][0]["disposition"], "still_open")
        self.assertEqual(second["current_findings"][0]["severity"], "blocker")

    def test_unknown_explicit_current_id_fails_closed(self):
        with self.assertRaisesRegex(_MOD.InputError, "not present in prior_findings"):
            _MOD.transition(
                {
                    "task_id": "T-REV-003",
                    "prior_findings": [
                        {"path": "scripts/a.py", "message": "known", "severity": "major"}
                    ],
                    "current_findings": [
                        {
                            "id": "T-REV-003-F0000000000000000",
                            "path": "scripts/a.py",
                            "message": "invented reference",
                            "severity": "major",
                        }
                    ],
                }
            )

    def test_all_prior_severities_are_classified_and_new_findings_need_no_id(self):
        first = _MOD.transition(
            {
                "task_id": "T001",
                "prior_findings": [],
                "current_findings": [
                    {"path": "a.py", "message": "blocker", "severity": "blocker"},
                    {"path": "b.py", "message": "minor", "severity": "minor"},
                    {"path": "c.py", "message": "unspecified"},
                ],
            }
        )
        by_message = {item["message"]: item for item in first["current_findings"]}
        result = _MOD.transition(
            {
                "task_id": "T001",
                "prior_findings": first["current_findings"],
                "current_findings": [
                    {
                        "id": by_message["minor"]["id"],
                        "path": "b.py",
                        "message": "minor reworded",
                        "severity": "major",
                    },
                    {"path": "d.py", "message": "new regression", "severity": "blocker"},
                ],
            }
        )
        prior = {item["message"]: item["disposition"] for item in result["prior_findings"]}
        self.assertEqual(prior, {"blocker": "resolved", "minor": "still_open", "unspecified": "resolved"})
        new = next(item for item in result["current_findings"] if item["message"] == "new regression")
        self.assertEqual(new["disposition"], "new")
        self.assertTrue(new["id"].startswith("T001-F"))

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
        self.assertIn("task_id must match T### or a review-task ID", completed.stderr)

        with self.assertRaises(_MOD.InputError):
            _MOD.transition({"task_id": "T002", "prior_findings": [{"path": "a.py"}], "current_findings": []})


if __name__ == "__main__":
    unittest.main()
