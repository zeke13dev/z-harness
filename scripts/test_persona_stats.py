#!/usr/bin/env python3
"""
test_persona_stats.py — Tests for scripts/persona-stats.py.

Run with:
    python3 scripts/test_persona_stats.py

Builds a self-contained metrics.jsonl fixture in a temp dir (it does NOT read
the live z-harness/metrics.jsonl) and asserts the stratified analysis against
the acceptance criteria for T012:

  - correct stratified table grouped by persona_id × role × complexity_tier;
  - fallback_empty_pool quarantined (separate section, excluded from baseline);
  - incomplete attempts (draw with no outcome) excluded;
  - reviewer rows segmented by reviewer_participant;
  - --json emits valid JSON;
  - delta-vs-boring-anchor computed within the SAME stratum.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "persona_stats", str(SCRIPTS_DIR / "persona-stats.py")
)
persona_stats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(persona_stats)


def _draw(attempt_id, draw_id, persona_id, role, source, task_id="T001"):
    """Build a persona_random_selected line (the draw event)."""
    return {
        "ts": "2026-06-01T00:00:00Z",
        "run": f"tasks/{task_id}",
        "kind": "persona_random_selected",
        "role": role,
        "selected": persona_id,
        "persona_id": persona_id,
        "candidates": [persona_id],
        "draw_id": draw_id,
        "selection_source": source,
        "task_id": task_id,
        "attempt_id": attempt_id,
    }


def _outcome(attempt_id, draw_id, persona_id, role, tier, *, status="done",
             review_cycles=0, retries=0, blocker_count=0, wall_ms=1000,
             diff_size=100, task_id="T001"):
    """Build a persona_attempt_outcome line (the terminal-outcome event)."""
    return {
        "ts": "2026-06-01T00:00:05Z",
        "run": f"tasks/{task_id}",
        "kind": "persona_attempt_outcome",
        "run_id": "run-1",
        "command": "z-implement-all",
        "role": role,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "persona_id": persona_id,
        "draw_id": draw_id,
        "complexity_tier": tier,
        "diff_size": diff_size,
        "review_cycles": review_cycles,
        "retries": retries,
        "blocker_count": blocker_count,
        "wall_ms": wall_ms,
        "status": status,
    }


def _bound_reviewer(attempt_id, draw_id, persona_id, participant, task_id="T001"):
    """Build a persona_bound line for a reviewer arm."""
    return {
        "ts": "2026-06-01T00:00:03Z",
        "run": f"tasks/{task_id}",
        "kind": "persona_bound",
        "run_id": "run-1",
        "command": "z-implement-all",
        "persona": persona_id,
        "persona_id": persona_id,
        "model": "codex",
        "runtime": "codex-cli",
        "source": {"persona": "override", "model": "provider_config", "runtime": "provider_config"},
        "role": "reviewer",
        "task_id": task_id,
        "attempt_id": attempt_id,
        "draw_id": draw_id,
        "reviewer_participant": participant,
    }


class PersonaStatsFixture(unittest.TestCase):
    """Build one comprehensive fixture and assert all acceptance criteria."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.metrics = os.path.join(self.tmp, "metrics.jsonl")
        lines = []

        # --- Stratum: role=implementer, tier=high ---
        # boring-anchor control: 2 attempts, both done, review_cycles 2 and 4
        # (mean 2.0/... ) -> mean review_cycles = 3, wall_ms mean = 2000.
        lines.append(_draw("T001-v1", "d-anchor-1", "boring-anchor", "implementer", "forced_control"))
        lines.append(_outcome("T001-v1", "d-anchor-1", "boring-anchor", "implementer", "high",
                              review_cycles=2, retries=1, blocker_count=1, wall_ms=1000, diff_size=200))
        lines.append(_draw("T002-v1", "d-anchor-2", "boring-anchor", "implementer", "forced_control"))
        lines.append(_outcome("T002-v1", "d-anchor-2", "boring-anchor", "implementer", "high",
                              review_cycles=4, retries=3, blocker_count=3, wall_ms=3000, diff_size=200))

        # spicy-rebel random arm, same stratum: 1 attempt, review_cycles=5,
        # wall_ms=5000. Delta vs control (mean 3 / 2000) => +2.0 / +3000.
        lines.append(_draw("T003-v1", "d-rebel-1", "spicy-rebel", "implementer", "random_role_pool"))
        lines.append(_outcome("T003-v1", "d-rebel-1", "spicy-rebel", "implementer", "high",
                              review_cycles=5, retries=2, blocker_count=2, wall_ms=5000, diff_size=300))

        # --- Different stratum: role=implementer, tier=low ---
        # boring-anchor control here is SEPARATE; spicy-rebel low must delta
        # against the LOW control, not the HIGH one.
        lines.append(_draw("T004-v1", "d-anchor-3", "boring-anchor", "implementer", "forced_control"))
        lines.append(_outcome("T004-v1", "d-anchor-3", "boring-anchor", "implementer", "low",
                              review_cycles=1, retries=0, blocker_count=0, wall_ms=500, diff_size=50))
        lines.append(_draw("T005-v1", "d-rebel-2", "spicy-rebel", "implementer", "random_role_pool"))
        lines.append(_outcome("T005-v1", "d-rebel-2", "spicy-rebel", "implementer", "low",
                              review_cycles=2, retries=0, blocker_count=0, wall_ms=700, diff_size=60,
                              status="unable_to_complete"))

        # --- Incomplete attempt: draw with NO matching outcome -> excluded ---
        lines.append(_draw("T006-v1", "d-incomplete", "spicy-rebel", "implementer", "random_role_pool"))

        # --- QUARANTINE: fallback_empty_pool resolves to boring-anchor but must
        # NOT contaminate the control baseline nor appear in any segment. ---
        lines.append(_draw("T007-v1", "d-fallback", "boring-anchor", "implementer", "fallback_empty_pool"))
        lines.append(_outcome("T007-v1", "d-fallback", "boring-anchor", "implementer", "high",
                              review_cycles=99, retries=99, blocker_count=99, wall_ms=99999, diff_size=999))

        # --- Reviewer arms: two persona_bound for the SAME attempt T001-v1,
        # distinct reviewer_participant -> segmented, not double-counted. ---
        lines.append(_bound_reviewer("T001-v1", "d-rev-base", "boring-anchor-reviewer", "base_codex"))
        lines.append(_bound_reviewer("T001-v1", "d-rev-rand", "spicy-reviewer", "random_arm"))
        # Another attempt with only a base_codex reviewer.
        lines.append(_bound_reviewer("T002-v1", "d-rev-base2", "boring-anchor-reviewer", "base_codex"))

        # --- Noise rows for --min-diff-size: a distinct persona (tiny-typo) in
        # the HIGH stratum with two attempts, one tiny (diff_size=5) and one
        # substantial (diff_size=300). The tiny one is dropped under
        # --min-diff-size 10. Kept on a separate persona so it cannot pollute
        # the spicy-rebel groups used by the other assertions. ---
        lines.append(_draw("T008-v1", "d-tiny", "tiny-typo", "implementer", "random_role_pool"))
        lines.append(_outcome("T008-v1", "d-tiny", "tiny-typo", "implementer", "high",
                              review_cycles=1, retries=0, blocker_count=0, wall_ms=100, diff_size=5))
        lines.append(_draw("T009-v1", "d-big", "tiny-typo", "implementer", "random_role_pool"))
        lines.append(_outcome("T009-v1", "d-big", "tiny-typo", "implementer", "high",
                              review_cycles=1, retries=0, blocker_count=0, wall_ms=100, diff_size=300))

        with open(self.metrics, "w", encoding="utf-8") as fh:
            for obj in lines:
                fh.write(json.dumps(obj) + "\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers --------------------------------------------------------------

    def _report(self, min_diff_size=0):
        return persona_stats.analyze(self.metrics, min_diff_size=min_diff_size)

    def _find_group(self, report, src, persona_id, role, tier):
        for g in report["segments"].get(src, []):
            if (g["persona_id"], g["role"], g["complexity_tier"]) == (persona_id, role, tier):
                return g
        return None

    # -- acceptance criteria --------------------------------------------------

    def test_stratified_grouping(self):
        report = self._report()
        # spicy-rebel appears in TWO strata (high, low) as distinct groups.
        high = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "high")
        low = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "low")
        self.assertIsNotNone(high)
        self.assertIsNotNone(low)
        self.assertEqual(high["n_attempts"], 1)
        self.assertEqual(high["metrics"]["review_cycles"], 5)
        self.assertEqual(low["metrics"]["review_cycles"], 2)

    def test_delta_within_stratum(self):
        report = self._report()
        # No no-persona in this fixture, so boring-anchor is the fallback baseline.
        # HIGH control mean review_cycles = (2+4)/2 = 3; wall_ms = (1000+3000)/2 = 2000.
        # spicy-rebel HIGH review_cycles = 5 -> delta +2; wall_ms 5000 -> +3000.
        high = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "high")
        delta = high["delta_vs_baseline"]
        self.assertIsNotNone(delta)
        self.assertAlmostEqual(delta["review_cycles"], 2.0)
        self.assertAlmostEqual(delta["wall_ms"], 3000.0)
        # baseline_source should be boring-anchor (no-persona absent in this fixture).
        self.assertEqual(high["baseline_source"], "boring-anchor")

        # LOW control review_cycles = 1; spicy-rebel LOW = 2 -> delta +1 (NOT
        # measured against the HIGH control of 3).
        low = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "low")
        self.assertAlmostEqual(low["delta_vs_baseline"]["review_cycles"], 1.0)

        # The control's own group has delta None (it is the baseline).
        ctrl = self._find_group(report, "forced_control", "boring-anchor", "implementer", "high")
        self.assertIsNotNone(ctrl)
        self.assertIsNone(ctrl["delta_vs_baseline"])

    def test_fallback_quarantined_and_excluded_from_baseline(self):
        report = self._report()
        # The fallback row exists in the quarantine section.
        q = report["quarantine_fallback_empty_pool"]
        self.assertEqual(q["n_attempts"], 1)
        self.assertEqual(q["metrics"]["review_cycles"], 99)

        # fallback_empty_pool must NOT appear as a segment.
        self.assertNotIn("fallback_empty_pool", report["segments"])

        # The fallback row resolved to boring-anchor with review_cycles=99 — if
        # it had contaminated the HIGH control baseline, the control mean would
        # be (2+4+99)/3 = 35 and spicy-rebel's delta would be 5-35 = -30.
        # Assert the delta is the clean +2 instead.
        high = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "high")
        self.assertAlmostEqual(high["delta_vs_baseline"]["review_cycles"], 2.0)

    def test_incomplete_attempts_excluded(self):
        report = self._report()
        # T006-v1 is a draw with no outcome. spicy-rebel HIGH should count only
        # the one completed attempt (T003-v1), not the incomplete T006-v1.
        high = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "high")
        self.assertEqual(high["n_attempts"], 1)

    def test_reviewer_segmented_by_participant(self):
        report = self._report()
        reviewer = report["reviewer"]
        self.assertIn("base_codex", reviewer)
        self.assertIn("random_arm", reviewer)
        # base_codex bound on T001-v1 and T002-v1 -> 2 attempts.
        self.assertEqual(reviewer["base_codex"]["n_attempts"], 2)
        # random_arm bound only on T001-v1 -> 1 attempt (not double-counted with
        # base_codex on the same attempt).
        self.assertEqual(reviewer["random_arm"]["n_attempts"], 1)

    def test_min_diff_size_drops_noise(self):
        # tiny-typo HIGH has two attempts (diff_size 5 and 300). With
        # --min-diff-size 10 the tiny one is dropped; only the 300 attempt
        # remains.
        report = self._report(min_diff_size=10)
        high = self._find_group(report, "random_role_pool", "tiny-typo", "implementer", "high")
        self.assertEqual(high["n_attempts"], 1)
        self.assertEqual(high["metrics"]["diff_size"], 300)

        # Without the filter both attempts (diff_size 300 and 5) count.
        report_all = self._report(min_diff_size=0)
        high_all = self._find_group(report_all, "random_role_pool", "tiny-typo", "implementer", "high")
        self.assertEqual(high_all["n_attempts"], 2)

    def test_completion_rate(self):
        report = self._report()
        # spicy-rebel LOW had a single attempt with status=unable_to_complete.
        low = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "low")
        self.assertAlmostEqual(low["completion_rate"], 0.0)
        # boring-anchor HIGH had 2 done -> completion 1.0.
        ctrl = self._find_group(report, "forced_control", "boring-anchor", "implementer", "high")
        self.assertAlmostEqual(ctrl["completion_rate"], 1.0)


class NoPersonaBaselineFixture(unittest.TestCase):
    """T104 acceptance criteria: no-persona as primary delta baseline.

    Builds a fixture where BOTH no-persona and boring-anchor are present within
    the same stratum, plus a separate stratum with only boring-anchor (to verify
    the fallback path), plus the usual fallback_empty_pool quarantine row.

    Assertions:
      - delta is computed vs no-persona within stratum (primary null baseline).
      - boring-anchor reported as a secondary arm (has its own group entry).
      - no-persona NOT quarantined (appears in segments, not only in quarantine).
      - boring-anchor delta is also vs no-persona when no-persona is present.
      - fallback_empty_pool still quarantined (unchanged behavior).
      - In a stratum with only boring-anchor (no no-persona), delta falls back
        to boring-anchor as baseline.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.metrics = os.path.join(self.tmp, "metrics.jsonl")
        lines = []

        # === Stratum: role=implementer, tier=high ===
        # no-persona (primary null baseline): 2 attempts, review_cycles 2 and 4
        # -> mean review_cycles = 3.0, wall_ms mean = (1000+3000)/2 = 2000.
        lines.append(_draw("NP-v1", "d-np-1", "no-persona", "implementer", "random_role_pool"))
        lines.append(_outcome("NP-v1", "d-np-1", "no-persona", "implementer", "high",
                              review_cycles=2, retries=0, blocker_count=0, wall_ms=1000,
                              diff_size=200))
        lines.append(_draw("NP-v2", "d-np-2", "no-persona", "implementer", "random_role_pool"))
        lines.append(_outcome("NP-v2", "d-np-2", "no-persona", "implementer", "high",
                              review_cycles=4, retries=0, blocker_count=0, wall_ms=3000,
                              diff_size=200))

        # boring-anchor (secondary bland control): 1 attempt, review_cycles=10.
        # With no-persona as primary baseline: delta = 10 - 3 = +7 (not zero).
        lines.append(_draw("BA-v1", "d-ba-1", "boring-anchor", "implementer", "forced_control"))
        lines.append(_outcome("BA-v1", "d-ba-1", "boring-anchor", "implementer", "high",
                              review_cycles=10, retries=0, blocker_count=0, wall_ms=8000,
                              diff_size=200))

        # spicy-rebel: 1 attempt, review_cycles=7. Delta vs no-persona = 7-3 = +4.
        lines.append(_draw("SR-v1", "d-sr-1", "spicy-rebel", "implementer", "random_role_pool"))
        lines.append(_outcome("SR-v1", "d-sr-1", "spicy-rebel", "implementer", "high",
                              review_cycles=7, retries=0, blocker_count=0, wall_ms=5000,
                              diff_size=300))

        # === Stratum: role=implementer, tier=low ===
        # Only boring-anchor exists here (no no-persona). Delta for other arms
        # should fall back to boring-anchor as baseline.
        lines.append(_draw("BA-low-v1", "d-ba-low", "boring-anchor", "implementer", "forced_control"))
        lines.append(_outcome("BA-low-v1", "d-ba-low", "boring-anchor", "implementer", "low",
                              review_cycles=1, retries=0, blocker_count=0, wall_ms=500,
                              diff_size=50))
        lines.append(_draw("SR-low-v1", "d-sr-low", "spicy-rebel", "implementer", "random_role_pool"))
        lines.append(_outcome("SR-low-v1", "d-sr-low", "spicy-rebel", "implementer", "low",
                              review_cycles=3, retries=0, blocker_count=0, wall_ms=900,
                              diff_size=60))

        # === QUARANTINE: fallback_empty_pool — unchanged behavior ===
        lines.append(_draw("FB-v1", "d-fb-1", "boring-anchor", "implementer", "fallback_empty_pool"))
        lines.append(_outcome("FB-v1", "d-fb-1", "boring-anchor", "implementer", "high",
                              review_cycles=99, retries=99, blocker_count=99, wall_ms=99999,
                              diff_size=999))

        with open(self.metrics, "w", encoding="utf-8") as fh:
            for obj in lines:
                fh.write(json.dumps(obj) + "\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _report(self, min_diff_size=0):
        return persona_stats.analyze(self.metrics, min_diff_size=min_diff_size)

    def _find_group(self, report, src, persona_id, role, tier):
        for g in report["segments"].get(src, []):
            if (g["persona_id"], g["role"], g["complexity_tier"]) == (persona_id, role, tier):
                return g
        return None

    def test_delta_computed_vs_no_persona_within_stratum(self):
        """Delta for spicy-rebel HIGH is vs no-persona (primary null), not boring-anchor."""
        report = self._report()
        # no-persona HIGH mean review_cycles = (2+4)/2 = 3.
        # spicy-rebel HIGH review_cycles = 7 -> delta = +4.0
        sr = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "high")
        self.assertIsNotNone(sr, "spicy-rebel HIGH group must exist")
        self.assertEqual(sr["baseline_source"], "no-persona")
        self.assertIsNotNone(sr["delta_vs_baseline"])
        self.assertAlmostEqual(sr["delta_vs_baseline"]["review_cycles"], 4.0)

    def test_boring_anchor_reported_as_secondary_arm(self):
        """boring-anchor appears as its own segment group (not quarantined).

        Its delta is also vs no-persona (since no-persona exists in that stratum),
        confirming boring-anchor is just another tracked arm.
        """
        report = self._report()
        ba = self._find_group(report, "forced_control", "boring-anchor", "implementer", "high")
        self.assertIsNotNone(ba, "boring-anchor HIGH group must appear as a tracked arm")
        self.assertEqual(ba["n_attempts"], 1)
        # boring-anchor is NOT its own baseline in this stratum (no-persona is primary),
        # so it gets a delta: 10 - 3 = +7.
        self.assertEqual(ba["baseline_source"], "no-persona")
        self.assertIsNotNone(ba["delta_vs_baseline"])
        self.assertAlmostEqual(ba["delta_vs_baseline"]["review_cycles"], 7.0)

    def test_no_persona_not_quarantined(self):
        """no-persona must appear in segments (as a tracked arm), not only in quarantine."""
        report = self._report()
        # Must appear in segments.
        np_group = self._find_group(report, "random_role_pool", "no-persona", "implementer", "high")
        self.assertIsNotNone(np_group, "no-persona HIGH must appear as a tracked arm in segments")
        self.assertEqual(np_group["n_attempts"], 2)
        # no-persona IS the primary baseline so its own delta_vs_baseline is None.
        self.assertIsNone(np_group["delta_vs_baseline"])
        # Must NOT appear in quarantine section.
        q = report["quarantine_fallback_empty_pool"]
        # Quarantine has only the fallback row (review_cycles=99), not no-persona rows.
        self.assertEqual(q["n_attempts"], 1)
        self.assertEqual(q["metrics"]["review_cycles"], 99)

    def test_fallback_still_quarantined(self):
        """fallback_empty_pool quarantine behavior is unchanged."""
        report = self._report()
        q = report["quarantine_fallback_empty_pool"]
        self.assertEqual(q["n_attempts"], 1)
        self.assertEqual(q["metrics"]["review_cycles"], 99)
        self.assertNotIn("fallback_empty_pool", report["segments"])
        # Quarantine must NOT bleed into no-persona baseline.
        # If fallback contaminated no-persona, mean review_cycles would be
        # (2+4+99)/3 = 35; spicy-rebel delta would be 7-35 = -28 (not +4).
        sr = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "high")
        self.assertAlmostEqual(sr["delta_vs_baseline"]["review_cycles"], 4.0)

    def test_boring_anchor_fallback_when_no_persona_absent(self):
        """In a stratum with no no-persona samples, boring-anchor is the baseline."""
        report = self._report()
        # LOW stratum: only boring-anchor exists, no no-persona.
        # spicy-rebel LOW review_cycles=3, boring-anchor LOW=1 -> delta=+2.
        sr_low = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "low")
        self.assertIsNotNone(sr_low, "spicy-rebel LOW group must exist")
        self.assertEqual(sr_low["baseline_source"], "boring-anchor")
        self.assertAlmostEqual(sr_low["delta_vs_baseline"]["review_cycles"], 2.0)
        # boring-anchor LOW is its own baseline in this stratum, so delta is None.
        ba_low = self._find_group(report, "forced_control", "boring-anchor", "implementer", "low")
        self.assertIsNotNone(ba_low)
        self.assertIsNone(ba_low["delta_vs_baseline"])


class PersonaStatsCLI(unittest.TestCase):
    """Exercise the CLI surface: --json validity and read-only behavior."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.metrics = os.path.join(self.tmp, "metrics.jsonl")
        lines = [
            _draw("A-v1", "dA", "boring-anchor", "implementer", "forced_control"),
            _outcome("A-v1", "dA", "boring-anchor", "implementer", "high", review_cycles=2),
            _draw("B-v1", "dB", "spicy-rebel", "implementer", "random_role_pool"),
            _outcome("B-v1", "dB", "spicy-rebel", "implementer", "high", review_cycles=4),
        ]
        with open(self.metrics, "w", encoding="utf-8") as fh:
            for obj in lines:
                fh.write(json.dumps(obj) + "\n")
        self.script = str(SCRIPTS_DIR / "persona-stats.py")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_json_flag_emits_valid_json(self):
        proc = subprocess.run(
            [sys.executable, self.script, "--metrics", self.metrics, "--json"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        parsed = json.loads(proc.stdout)  # raises if invalid JSON
        self.assertIn("segments", parsed)
        self.assertIn("quarantine_fallback_empty_pool", parsed)
        self.assertIn("reviewer", parsed)

    def test_table_output_runs(self):
        proc = subprocess.run(
            [sys.executable, self.script, "--metrics", self.metrics],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PERSONA-STATS", proc.stdout)
        self.assertIn("QUARANTINE", proc.stdout)

    def test_read_only_does_not_modify_metrics(self):
        before = Path(self.metrics).read_bytes()
        mtime_before = os.path.getmtime(self.metrics)
        entries_before = set(os.listdir(self.tmp))
        subprocess.run(
            [sys.executable, self.script, "--metrics", self.metrics, "--json"],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(Path(self.metrics).read_bytes(), before)
        self.assertEqual(os.path.getmtime(self.metrics), mtime_before)
        self.assertEqual(set(os.listdir(self.tmp)), entries_before)

    def test_missing_metrics_file_errors(self):
        proc = subprocess.run(
            [sys.executable, self.script, "--metrics", os.path.join(self.tmp, "nope.jsonl"), "--json"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()
