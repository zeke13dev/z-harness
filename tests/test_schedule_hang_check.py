#!/usr/bin/env python3
"""Tests for scripts/schedule-hang-check.sh (T008).

--print is fully deterministic; --self-test is tolerant of environments where
launchd is unavailable (prints SKIP). Uses a temp LaunchAgents dir so it never
touches the real ~/Library/LaunchAgents.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from runtime import release_surface

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "schedule-hang-check.sh")


def _run(args):
    env = dict(os.environ)
    env["SCHEDULE_HANG_AGENTS_DIR"] = tempfile.mkdtemp(prefix="zh-agents-")
    return subprocess.run(["bash", SCRIPT] + args,
                          capture_output=True, text=True, timeout=30, env=env)


class TestSchedule(unittest.TestCase):
    def test_prod_execute_explicitly_disables_watchdog_dispatch(self):
        skill = Path(ROOT, "skills", "z-execute", "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Production watchdog posture", skill)
        self.assertNotIn("scripts/schedule-hang-check.sh", skill)
        self.assertNotIn("scripts/hang-threshold.py", skill)
        self.assertTrue(release_surface.path_excluded_from_prod("scripts/schedule-hang-check.sh"))
        self.assertTrue(release_surface.path_excluded_from_prod("scripts/hang-check.sh"))

    def test_print_emits_valid_plan(self):
        p = _run(["--run", "20260621T000000Z-x", "--threshold-secs", "600", "--print"])
        self.assertEqual(p.returncode, 0)
        out = p.stdout
        self.assertIn("hang-check.sh", out)
        self.assertIn("--run", out)
        self.assertIn("20260621T000000Z-x", out)
        self.assertIn("--threshold-secs 600", out)
        self.assertIn("StartCalendarInterval", out)
        # self-removing one-shot
        self.assertIn("bootout", out)
        self.assertIn("rm -f", out)

    def test_print_default_delay_is_threshold(self):
        p = _run(["--run", "r", "--threshold-secs", "300", "--print"])
        self.assertEqual(p.returncode, 0)
        self.assertIn("StartCalendarInterval", p.stdout)

    def test_missing_run_is_arg_error(self):
        p = _run(["--threshold-secs", "300"])
        self.assertEqual(p.returncode, 2)

    def test_missing_threshold_is_arg_error(self):
        p = _run(["--run", "r"])
        self.assertEqual(p.returncode, 2)

    def test_default_label_uses_valid_run_id(self):
        p = _run(["--run", "weird.run_id-01", "--threshold-secs", "300", "--print"])
        self.assertEqual(p.returncode, 0)
        self.assertIn("com.zharness.hangcheck.weird.run_id-01", p.stdout)

    def test_self_test_passes_or_skips(self):
        p = _run(["--self-test"])
        self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
        self.assertTrue("PASS" in p.stdout or "SKIP" in p.stdout,
                        msg=f"unexpected self-test output: {p.stdout!r}")


if __name__ == "__main__":
    unittest.main()
