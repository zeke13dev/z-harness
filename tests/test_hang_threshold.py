#!/usr/bin/env python3
"""Tests for scripts/hang-threshold.py — per-class hang-threshold estimator.

Hermetic: synthetic metrics.jsonl fixtures, no network, no live state.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "scripts", "hang-threshold.py")


def _metrics(events):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return path


def _run(args, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([sys.executable, SCRIPT] + args,
                          capture_output=True, text=True, timeout=15, env=e)


class TestHangThreshold(unittest.TestCase):
    def test_p90_times_margin(self):
        # 10 implement_end:opus samples 1000..10000ms; p90 = 9000ms; margin 1.5 -> 13.5s
        evs = [{"kind": "implement_end", "subagent_model": "opus",
                "wall_ms": i * 1000} for i in range(1, 11)]
        mp = _metrics(evs)
        try:
            out = _run(["dump", "--metrics", mp],
                       env={"HANG_PCTILE": "90", "HANG_MARGIN": "1.5",
                            "HANG_MIN_SAMPLE": "5"})
            table = json.loads(out.stdout)
            self.assertIn("implement_end:opus", table)
            self.assertEqual(table["implement_end:opus"]["n"], 10)
            self.assertEqual(table["implement_end:opus"]["p_ms"], 9000)
            self.assertEqual(table["implement_end:opus"]["threshold_secs"], 14)  # round(13.5)
        finally:
            os.unlink(mp)

    def test_persona_keyed_by_role_and_tier(self):
        evs = [{"kind": "persona_attempt_outcome", "role": "implementer",
                "complexity_tier": "medium", "wall_ms": 5000} for _ in range(6)]
        mp = _metrics(evs)
        try:
            out = _run(["dump", "--metrics", mp], env={"HANG_MIN_SAMPLE": "5"})
            table = json.loads(out.stdout)
            self.assertIn("agent:implementer/medium", table)
        finally:
            os.unlink(mp)

    def test_min_sample_excludes_sparse_class(self):
        evs = [{"kind": "review_end", "wall_ms": 1000} for _ in range(3)]
        mp = _metrics(evs)
        try:
            out = _run(["dump", "--metrics", mp], env={"HANG_MIN_SAMPLE": "5"})
            table = json.loads(out.stdout)
            self.assertNotIn("review_end", table)
        finally:
            os.unlink(mp)

    def test_noise_kinds_excluded(self):
        evs = [{"kind": "longrun_end", "wall_ms": 93600000} for _ in range(10)]
        evs += [{"kind": "mytest_end", "wall_ms": 300} for _ in range(10)]
        evs += [{"kind": "implement_end", "run": "test-foo", "wall_ms": 5000}
                for _ in range(10)]
        mp = _metrics(evs)
        try:
            out = _run(["dump", "--metrics", mp], env={"HANG_MIN_SAMPLE": "5"})
            table = json.loads(out.stdout)
            self.assertEqual(table, {})  # all excluded
        finally:
            os.unlink(mp)

    def test_for_known_class_prints_threshold(self):
        evs = [{"kind": "review_end", "wall_ms": 2000} for _ in range(8)]
        mp = _metrics(evs)
        try:
            out = _run(["for", "--kind", "review_end", "--metrics", mp],
                       env={"HANG_MIN_SAMPLE": "5", "HANG_MARGIN": "1.0",
                            "HANG_PCTILE": "90"})
            self.assertEqual(out.stdout.strip(), "2")  # 2000ms * 1.0 -> 2s
        finally:
            os.unlink(mp)

    def test_for_unknown_class_uses_global_fallback(self):
        mp = _metrics([{"kind": "review_end", "wall_ms": 2000}])  # too few
        try:
            out = _run(["for", "--kind", "nonexistent_kind", "--metrics", mp])
            val = out.stdout.strip()
            self.assertTrue(val.isdigit(), f"expected an integer fallback, got {val!r}")
            self.assertGreater(int(val), 0)
        finally:
            os.unlink(mp)


if __name__ == "__main__":
    unittest.main()
