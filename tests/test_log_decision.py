"""
Tests for scripts/log-decision.sh

Cases covered:
  emits_user_choice          — emits a well-formed user_choice line into metrics.jsonl
                               and run events.jsonl
  auto_yields_user_override  — chosen != tentative under --kind auto yields user_override
  explicit_kind_overrides    — explicit --kind overrides auto logic
  event_id_formula           — event_id matches e-<sha1(run+question_id+chosen+ts)[:8]>
  silent_no_op               — Z_HARNESS_AXIOM_EXTRACT=0 writes nothing (exit 0)
  payload_required_fields    — payload contains all required fields with
                               decision_key == question_id

HERMETICITY: each test git-inits a fresh tmpdir and runs with cwd set there,
so log-event.sh's `git rev-parse --show-toplevel` returns the temp dir.
The real repo's z-harness/metrics.jsonl is never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "log-decision.sh")


def _git_init_tmpdir(tmp_path: Path) -> None:
    """Initialise a bare git repo in tmp_path so git rev-parse works."""
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    # Create the z-harness dir so log-event.sh can append to metrics.jsonl.
    (tmp_path / "z-harness").mkdir(parents=True, exist_ok=True)
    (tmp_path / "z-harness" / "metrics.jsonl").touch()


def _run_script(
    args: list[str],
    cwd: Path,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Unset any existing AXIOM_EXTRACT override so tests are not affected by the
    # caller's environment.
    env.pop("Z_HARNESS_AXIOM_EXTRACT", None)
    # Pin the artifact base into the per-test tmpdir. The default base is now
    # external (XDG state dir), so without this the emitted events would land in
    # ~/.local/state/z-harness/<repo>-<hash>/metrics.jsonl instead of the
    # tmp/z-harness/metrics.jsonl that _read_metrics reads — breaking both the
    # assertions and the hermeticity claimed in this module's docstring.
    env.setdefault("Z_HARNESS_BASE_DIR", str(Path(cwd) / "z-harness"))
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", _SCRIPT] + args,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )


def _read_metrics(tmp_path: Path) -> list[dict]:
    metrics_file = tmp_path / "z-harness" / "metrics.jsonl"
    lines = metrics_file.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class TestLogDecision(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="test_log_decision_")
        self._tmp_path = Path(self._tmp)
        _git_init_tmpdir(self._tmp_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # emits_user_choice
    # ------------------------------------------------------------------

    def test_emits_user_choice(self):
        """Emits a well-formed user_choice event into metrics.jsonl and events.jsonl."""
        result = _run_script(
            [
                "run-20260529T120000Z",
                "provider_for_task",
                "sonnet",
                "--options", '["haiku","sonnet","opus"]',
                "--source", "z-plan",
                "--kind", "user_choice",
            ],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        events = _read_metrics(self._tmp_path)
        self.assertEqual(len(events), 1)
        ev = events[0]

        # Base fields merged by log-event.sh
        self.assertEqual(ev["kind"], "user_choice")
        self.assertEqual(ev["run"], "run-20260529T120000Z")
        self.assertIn("ts", ev)

        # Payload fields
        self.assertEqual(ev["question_id"], "provider_for_task")
        self.assertEqual(ev["decision_key"], "provider_for_task")
        self.assertEqual(ev["chosen"], "sonnet")
        self.assertEqual(ev["options"], ["haiku", "sonnet", "opus"])
        self.assertEqual(ev["source_command"], "z-plan")
        self.assertRegex(ev["event_id"], r"^e-[0-9a-f]{8}$")

        # Also check events.jsonl for the run
        run_events = (
            self._tmp_path / "z-harness" / "archive" / "run-20260529T120000Z" / "events.jsonl"
        )
        self.assertTrue(run_events.exists(), msg="run events.jsonl should exist")
        run_ev = json.loads(run_events.read_text().strip())
        self.assertEqual(run_ev["kind"], "user_choice")
        self.assertEqual(run_ev["question_id"], "provider_for_task")

    # ------------------------------------------------------------------
    # auto_yields_user_override
    # ------------------------------------------------------------------

    def test_auto_yields_user_override(self):
        """chosen != tentative under --kind auto (default) yields user_override."""
        result = _run_script(
            [
                "run-override",
                "dirty_tree_strategy",
                "stash",
                "--tentative", "abort",
                # no --kind; default is auto
            ],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        events = _read_metrics(self._tmp_path)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["kind"], "user_override")
        self.assertEqual(ev["tentative"], "abort")
        self.assertEqual(ev["chosen"], "stash")

    def test_auto_yields_user_choice_when_matching_tentative(self):
        """chosen == tentative under auto yields user_choice."""
        result = _run_script(
            [
                "run-match",
                "dirty_tree_strategy",
                "abort",
                "--tentative", "abort",
            ],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        events = _read_metrics(self._tmp_path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "user_choice")

    # ------------------------------------------------------------------
    # explicit_kind_overrides
    # ------------------------------------------------------------------

    def test_explicit_kind_overrides_auto(self):
        """Explicit --kind user_override overrides auto even when chosen == tentative."""
        result = _run_script(
            [
                "run-explicit",
                "provider_for_task",
                "haiku",
                "--tentative", "haiku",
                "--kind", "user_override",
            ],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        events = _read_metrics(self._tmp_path)
        self.assertEqual(len(events), 1)
        # Even though chosen == tentative, explicit --kind wins.
        self.assertEqual(events[0]["kind"], "user_override")

    def test_explicit_kind_user_choice(self):
        """Explicit --kind user_choice is honored."""
        result = _run_script(
            [
                "run-explicit2",
                "provider_for_task",
                "opus",
                "--tentative", "sonnet",  # would normally → user_override
                "--kind", "user_choice",
            ],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        events = _read_metrics(self._tmp_path)
        self.assertEqual(events[0]["kind"], "user_choice")

    # ------------------------------------------------------------------
    # event_id_formula
    # ------------------------------------------------------------------

    def test_event_id_formula(self):
        """event_id follows e-<sha1(run+question_id+chosen+ts)[:8]>."""
        result = _run_script(
            [
                "run-formula",
                "provider_for_task",
                "sonnet",
                "--kind", "user_choice",
            ],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        events = _read_metrics(self._tmp_path)
        ev = events[0]

        # Reproduce the formula from the spec.
        ts = ev["ts"]
        run = ev["run"]
        question_id = ev["question_id"]
        chosen = ev["chosen"]
        digest = hashlib.sha1((run + question_id + chosen + ts).encode()).hexdigest()
        expected_event_id = "e-" + digest[:8]

        self.assertEqual(ev["event_id"], expected_event_id)

    def test_event_id_pattern(self):
        """event_id always matches ^e-[0-9a-f]{8}$."""
        import re
        result = _run_script(
            ["run-pat", "q", "chosen", "--kind", "user_choice"],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        ev = _read_metrics(self._tmp_path)[0]
        self.assertRegex(ev["event_id"], r"^e-[0-9a-f]{8}$")

    # ------------------------------------------------------------------
    # silent_no_op
    # ------------------------------------------------------------------

    def test_silent_no_op_when_extract_disabled(self):
        """Z_HARNESS_AXIOM_EXTRACT=0 produces no output and exit 0."""
        result = _run_script(
            ["run-noop", "provider_for_task", "sonnet"],
            cwd=self._tmp_path,
            env_extra={"Z_HARNESS_AXIOM_EXTRACT": "0"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

        # metrics.jsonl must remain empty.
        metrics_file = self._tmp_path / "z-harness" / "metrics.jsonl"
        content = metrics_file.read_text().strip()
        self.assertEqual(content, "", msg="metrics.jsonl should be empty when gated off")

    def test_enabled_when_extract_unset(self):
        """Unset Z_HARNESS_AXIOM_EXTRACT means emit (default on)."""
        env = os.environ.copy()
        env.pop("Z_HARNESS_AXIOM_EXTRACT", None)
        env.setdefault("Z_HARNESS_BASE_DIR", str(self._tmp_path / "z-harness"))
        result = subprocess.run(
            ["bash", _SCRIPT, "run-default", "q", "chosen", "--kind", "user_choice"],
            cwd=str(self._tmp_path),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        events = _read_metrics(self._tmp_path)
        self.assertGreater(len(events), 0)

    # ------------------------------------------------------------------
    # payload_required_fields
    # ------------------------------------------------------------------

    def test_payload_required_fields(self):
        """Payload contains all required fields with decision_key == question_id."""
        result = _run_script(
            [
                "run-fields",
                "my_question",
                "option_a",
                "--options", '["option_a","option_b"]',
                "--tentative", "option_b",
                "--source", "z-execute",
                "--kind", "user_override",
            ],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        ev = _read_metrics(self._tmp_path)[0]

        required = [
            "ts", "run", "kind",
            "question_id", "decision_key", "chosen",
            "options", "tentative", "source_command", "event_id",
        ]
        for field in required:
            self.assertIn(field, ev, msg=f"Missing required field: {field}")

        # decision_key == question_id (the extractor's R8 grouping key)
        self.assertEqual(ev["decision_key"], ev["question_id"])
        self.assertEqual(ev["question_id"], "my_question")

        # options is the array we passed
        self.assertEqual(ev["options"], ["option_a", "option_b"])

        # tentative propagated
        self.assertEqual(ev["tentative"], "option_b")

        # source_command propagated
        self.assertEqual(ev["source_command"], "z-execute")

    def test_options_defaults_to_empty_array(self):
        """--options absent → options field is [] in the payload."""
        result = _run_script(
            ["run-no-opts", "q", "chosen", "--kind", "user_choice"],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        ev = _read_metrics(self._tmp_path)[0]
        self.assertEqual(ev["options"], [])

    def test_tentative_defaults_to_null(self):
        """--tentative absent → tentative field is null in the payload."""
        result = _run_script(
            ["run-no-tent", "q", "chosen", "--kind", "user_choice"],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        ev = _read_metrics(self._tmp_path)[0]
        self.assertIsNone(ev["tentative"])

    def test_source_command_defaults_to_null(self):
        """--source absent → source_command field is null in the payload."""
        result = _run_script(
            ["run-no-src", "q", "chosen", "--kind", "user_choice"],
            cwd=self._tmp_path,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        ev = _read_metrics(self._tmp_path)[0]
        self.assertIsNone(ev["source_command"])


if __name__ == "__main__":
    unittest.main()
