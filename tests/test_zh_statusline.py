#!/usr/bin/env python3
"""Tests for scripts/zh-statusline.py — the statusLine HUD renderer.

Hermetic: synthetic stdin + synthetic transcript fixtures; no live registry, no
network. Covers the plan acceptance set: in-flight detection, completed-detection,
malformed transcript, no-run base tier, and graceful degradation.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "scripts", "zh-statusline.py")

_ANSI = re.compile(r"\033\[[0-9;]*m")


def _strip(s):
    return _ANSI.sub("", s)


def _run(stdin_obj):
    """Run the statusline with a given stdin payload; return (rc, plain_stdout)."""
    proc = subprocess.run(
        [sys.executable, SCRIPT],
        input=json.dumps(stdin_obj), capture_output=True, text=True, timeout=15,
    )
    return proc.returncode, _strip(proc.stdout).strip()


def _transcript(*events):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return path


def _assistant_tooluse(tid, ts, name="Agent", subagent_type="reviewer"):
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": tid, "name": name,
                 "input": {"subagent_type": subagent_type, "description": "x",
                           "prompt": "y"}}]}}


def _user_result(tid):
    return {"type": "user",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid}]}}


BASE_STDIN = {
    "cwd": "/tmp/nonexistent-repo-xyz",
    "session_id": "sess-test",
    "model": {"display_name": "Opus"},
    "context_window": {"used_percentage": 41},
    "cost": {"total_cost_usd": 0.1234},
}


class TestBaseTier(unittest.TestCase):
    def test_no_run_base_tier(self):
        rc, out = _run(BASE_STDIN)
        self.assertEqual(rc, 0)
        self.assertIn("Opus", out)
        self.assertIn("ctx 41%", out)
        self.assertIn("$0.12", out)
        self.assertNotIn(">", out)  # no in-flight indicator

    def test_empty_stdin(self):
        proc = subprocess.run([sys.executable, SCRIPT], input="",
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.strip())  # never blank

    def test_malformed_stdin(self):
        proc = subprocess.run([sys.executable, SCRIPT], input="{not json",
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.strip())

    def test_missing_model_defaults(self):
        rc, out = _run({"cwd": "/tmp/x"})
        self.assertEqual(rc, 0)
        self.assertIn("claude", out)


class TestInflightDetection(unittest.TestCase):
    def test_inflight_subagent_shown(self):
        # tool_use with no matching result -> in-flight
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(seconds=38)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z")
        tx = _transcript(_assistant_tooluse("toolu_1", ts, subagent_type="reviewer"))
        try:
            stdin = dict(BASE_STDIN, transcript_path=tx)
            rc, out = _run(stdin)
            self.assertEqual(rc, 0)
            self.assertIn("reviewer", out)
            self.assertIn(">", out)
            self.assertRegex(out, r"reviewer \d+s")
        finally:
            os.unlink(tx)

    def test_completed_subagent_not_shown(self):
        ts = "2026-06-21T18:00:00.000Z"
        tx = _transcript(_assistant_tooluse("toolu_2", ts),
                         _user_result("toolu_2"))
        try:
            rc, out = _run(dict(BASE_STDIN, transcript_path=tx))
            self.assertEqual(rc, 0)
            self.assertNotIn(">", out)
        finally:
            os.unlink(tx)

    def test_malformed_transcript_degrades(self):
        fd, tx = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as fh:
            fh.write("not json at all\n{also bad\n")
        try:
            rc, out = _run(dict(BASE_STDIN, transcript_path=tx))
            self.assertEqual(rc, 0)
            self.assertIn("Opus", out)  # base tier still renders
            self.assertNotIn(">", out)
        finally:
            os.unlink(tx)

    def test_missing_transcript_path(self):
        rc, out = _run(dict(BASE_STDIN, transcript_path="/no/such/file.jsonl"))
        self.assertEqual(rc, 0)
        self.assertIn("Opus", out)

    def test_second_of_two_agents_inflight(self):
        # first agent completed, second in-flight -> show only the second
        ts1 = "2026-06-21T18:00:00.000Z"
        from datetime import datetime, timezone, timedelta
        ts2 = (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z")
        tx = _transcript(
            _assistant_tooluse("toolu_a", ts1, subagent_type="doc-fetcher"),
            _user_result("toolu_a"),
            _assistant_tooluse("toolu_b", ts2, subagent_type="implementer"),
        )
        try:
            rc, out = _run(dict(BASE_STDIN, transcript_path=tx))
            self.assertEqual(rc, 0)
            self.assertIn("implementer", out)
            self.assertNotIn("doc-fetcher", out)
        finally:
            os.unlink(tx)


if __name__ == "__main__":
    unittest.main()
