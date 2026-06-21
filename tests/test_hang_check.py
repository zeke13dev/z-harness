#!/usr/bin/env python3
"""Tests for scripts/hang-check.sh — one-shot scheduled hang detector (T007).

Hermetic: builds a temp z-harness base with archive/<run>/events.jsonl, mocks the
notify script, points liveness at the fixture via Z_HARNESS_BASE_DIR.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANG_CHECK = os.path.join(ROOT, "scripts", "hang-check.sh")


def _ts(secs_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=secs_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


class TestHangCheck(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="zh-hangtest-")
        self.run = "20260621T000000Z-hangtest"
        self.run_dir = os.path.join(self.base, "archive", self.run)
        os.makedirs(self.run_dir)
        # notify mock: appends a line each time it is called
        self.notify_log = os.path.join(self.base, "notify.log")
        self.notify_mock = os.path.join(self.base, "notify-mock.sh")
        with open(self.notify_mock, "w") as fh:
            fh.write(f'#!/bin/sh\necho called >> "{self.notify_log}"\n')
        os.chmod(self.notify_mock, 0o755)

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def _write_events(self, events):
        with open(os.path.join(self.run_dir, "events.jsonl"), "w") as fh:
            for e in events:
                fh.write(json.dumps(e) + "\n")

    def _run(self, threshold=300, reason="testreason"):
        env = dict(os.environ)
        env["Z_HARNESS_BASE_DIR"] = self.base
        env["Z_HARNESS_PLAN_DIR"] = self.base
        env["HANG_NOTIFY_SCRIPT"] = self.notify_mock
        return subprocess.run(
            ["bash", HANG_CHECK, "--run", self.run,
             "--threshold-secs", str(threshold), "--reason", reason],
            capture_output=True, text=True, timeout=20, env=env)

    def test_stall_detected_and_notified(self):
        # review_start 1000s ago, no matching review_end -> hung past 300s
        self._write_events([
            {"ts": _ts(1000), "run": self.run, "kind": "review_start", "id": "T1"},
        ])
        p = self._run(threshold=300)
        self.assertEqual(p.returncode, 0)
        self.assertIn("HANG", p.stdout)
        self.assertTrue(os.path.exists(self.notify_log), "notify should have fired")

    def test_healthy_run_silent(self):
        # matched start/end -> not hung
        self._write_events([
            {"ts": _ts(1000), "run": self.run, "kind": "review_start", "id": "T1"},
            {"ts": _ts(900), "run": self.run, "kind": "review_end", "id": "T1"},
        ])
        p = self._run(threshold=300)
        self.assertEqual(p.returncode, 0)
        self.assertNotIn("HANG", p.stdout)
        self.assertFalse(os.path.exists(self.notify_log))

    def test_under_threshold_silent(self):
        # start only 10s ago, threshold 300 -> not yet hung
        self._write_events([
            {"ts": _ts(10), "run": self.run, "kind": "review_start", "id": "T1"},
        ])
        p = self._run(threshold=300)
        self.assertEqual(p.returncode, 0)
        self.assertNotIn("HANG", p.stdout)

    def test_notify_once_dedup(self):
        self._write_events([
            {"ts": _ts(1000), "run": self.run, "kind": "review_start", "id": "T1"},
        ])
        self._run(threshold=300, reason="dup")
        self._run(threshold=300, reason="dup")  # second time: marker suppresses notify
        with open(self.notify_log) as fh:
            calls = [l for l in fh if l.strip()]
        self.assertEqual(len(calls), 1, "notify should fire exactly once per reason")

    def test_missing_run_never_fails(self):
        env = dict(os.environ)
        env["Z_HARNESS_BASE_DIR"] = self.base
        p = subprocess.run(["bash", HANG_CHECK, "--threshold-secs", "300"],
                           capture_output=True, text=True, timeout=20, env=env)
        self.assertEqual(p.returncode, 0)  # never fail loudly


if __name__ == "__main__":
    unittest.main()
