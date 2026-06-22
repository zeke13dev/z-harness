#!/usr/bin/env python3
"""
test_persona_stats.py — Tests for scripts/persona-stats.py.

Run with:
    python3 scripts/test_persona_stats.py

Builds a self-contained metrics.jsonl fixture in a temp dir (it does NOT read
the live z-harness/metrics.jsonl) and asserts the stratified analysis against
the acceptance criteria for T012, T104, and T107:

  - correct stratified table grouped by persona_id × role × complexity_tier;
  - fallback_empty_pool quarantined (separate section, excluded from baseline);
  - incomplete attempts (draw with no outcome) excluded;
  - reviewer rows segmented by reviewer_participant;
  - --json emits valid JSON;
  - delta-vs-boring-anchor computed within the SAME stratum;
  - unknown-run events excluded by default (T107);
  - --include-unknown-run re-includes them (T107);
  - --since filters events by ts (T107);
  - existing real-run fixtures unchanged by new default filters (T107).
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


def _draw(attempt_id, draw_id, persona_id, role, source, task_id="T001",
          run=None, ts="2026-06-01T00:00:00Z"):
    """Build a persona_random_selected line (the draw event).

    ``run`` defaults to ``"tasks/<task_id>"``; pass ``run="unknown-run"`` to
    simulate ad-hoc dev-noise draws.  ``ts`` defaults to a fixed 2026-06-01
    timestamp.
    """
    return {
        "ts": ts,
        "run": run if run is not None else f"tasks/{task_id}",
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
             diff_size=100, task_id="T001", run=None, ts="2026-06-01T00:00:05Z"):
    """Build a persona_attempt_outcome line (the terminal-outcome event).

    ``run`` defaults to ``"tasks/<task_id>"``; pass ``run="unknown-run"`` to
    simulate dev-noise outcomes.  ``ts`` defaults to a fixed 2026-06-01
    timestamp.
    """
    return {
        "ts": ts,
        "run": run if run is not None else f"tasks/{task_id}",
        "kind": "persona_attempt_outcome",
        "run_id": "run-1",
        "command": "z-execute",
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


def _bound_reviewer(attempt_id, draw_id, persona_id, participant, task_id="T001",
                    run=None, ts="2026-06-01T00:00:03Z"):
    """Build a persona_bound line for a reviewer arm.

    ``run`` defaults to ``"tasks/<task_id>"``.  ``ts`` defaults to a fixed
    2026-06-01 timestamp.
    """
    return {
        "ts": ts,
        "run": run if run is not None else f"tasks/{task_id}",
        "kind": "persona_bound",
        "run_id": "run-1",
        "command": "z-execute",
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


class UnknownRunFilterFixture(unittest.TestCase):
    """T107: unknown-run events excluded by default; re-included with --include-unknown-run.

    Invariant: events with run == "unknown-run" are dev noise and must be
    invisible to the stratified analysis unless the caller explicitly opts in.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.metrics = os.path.join(self.tmp, "metrics.jsonl")
        lines = []

        # Real-run attempt: should always appear regardless of filter.
        lines.append(_draw("REAL-v1", "d-real-1", "boring-anchor", "implementer", "forced_control",
                           task_id="T200"))
        lines.append(_outcome("REAL-v1", "d-real-1", "boring-anchor", "implementer", "high",
                              review_cycles=2, diff_size=200, task_id="T200"))

        # Unknown-run attempt: draw + outcome both carry run="unknown-run".
        lines.append(_draw("UNK-v1", "d-unk-1", "spicy-rebel", "implementer", "random_role_pool",
                           task_id="T200", run="unknown-run"))
        lines.append(_outcome("UNK-v1", "d-unk-1", "spicy-rebel", "implementer", "high",
                              review_cycles=99, diff_size=300, task_id="T200", run="unknown-run"))

        with open(self.metrics, "w", encoding="utf-8") as fh:
            for obj in lines:
                fh.write(json.dumps(obj) + "\n")

        self.script = str(SCRIPTS_DIR / "persona-stats.py")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _report(self, include_unknown_run=False):
        return persona_stats.analyze(
            self.metrics, include_unknown_run=include_unknown_run
        )

    def _find_group(self, report, src, persona_id, role, tier):
        for g in report["segments"].get(src, []):
            if (g["persona_id"], g["role"], g["complexity_tier"]) == (persona_id, role, tier):
                return g
        return None

    def test_unknown_run_excluded_by_default(self):
        """By default, unknown-run events are invisible — spicy-rebel must not appear."""
        report = self._report(include_unknown_run=False)
        # The unknown-run spicy-rebel draw+outcome must be filtered out entirely.
        sr = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "high")
        self.assertIsNone(sr, "unknown-run spicy-rebel must be excluded by default")
        # The real-run boring-anchor must still appear.
        ba = self._find_group(report, "forced_control", "boring-anchor", "implementer", "high")
        self.assertIsNotNone(ba, "real-run boring-anchor must remain visible")

    def test_include_unknown_run_readds_events(self):
        """--include-unknown-run re-adds the dev-noise events."""
        report = self._report(include_unknown_run=True)
        # With the flag, the unknown-run spicy-rebel attempt must appear.
        sr = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "high")
        self.assertIsNotNone(sr, "unknown-run spicy-rebel must appear with --include-unknown-run")
        self.assertEqual(sr["n_attempts"], 1)
        self.assertEqual(sr["metrics"]["review_cycles"], 99)

    def test_real_run_events_unchanged_by_default_filter(self):
        """Default filter must not affect events that have a real run id."""
        # The default (exclude unknown-run) must leave real-run results identical
        # to include_unknown_run=True minus the unknown-run rows.
        report_default = self._report(include_unknown_run=False)
        ba_default = self._find_group(report_default, "forced_control", "boring-anchor", "implementer", "high")
        self.assertIsNotNone(ba_default)
        self.assertEqual(ba_default["n_attempts"], 1)
        self.assertEqual(ba_default["metrics"]["review_cycles"], 2)


class SinceFilterFixture(unittest.TestCase):
    """T107: --since filters events by ts; older events dropped, newer kept.

    Invariant: when --since is set, only events whose ts >= threshold survive
    the filter.  Events with missing/unparseable ts are excluded (conservative).
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.metrics = os.path.join(self.tmp, "metrics.jsonl")
        lines = []

        # OLD attempt: ts 2026-05-01 — before the --since cutoff.
        lines.append(_draw("OLD-v1", "d-old-1", "boring-anchor", "implementer", "forced_control",
                           task_id="T300", ts="2026-05-01T00:00:00Z"))
        lines.append(_outcome("OLD-v1", "d-old-1", "boring-anchor", "implementer", "high",
                              review_cycles=10, diff_size=200, task_id="T300",
                              ts="2026-05-01T00:00:05Z"))

        # NEW attempt: ts 2026-06-15 — on/after the --since cutoff.
        lines.append(_draw("NEW-v1", "d-new-1", "spicy-rebel", "implementer", "random_role_pool",
                           task_id="T300", ts="2026-06-15T00:00:00Z"))
        lines.append(_outcome("NEW-v1", "d-new-1", "spicy-rebel", "implementer", "high",
                              review_cycles=3, diff_size=150, task_id="T300",
                              ts="2026-06-15T00:00:05Z"))

        # MISSING-TS attempt: no ts field — should be excluded when --since set.
        bad_draw = _draw("BAD-v1", "d-bad-1", "boring-anchor", "implementer", "forced_control",
                         task_id="T300")
        bad_draw.pop("ts")
        lines.append(bad_draw)
        bad_outcome = _outcome("BAD-v1", "d-bad-1", "boring-anchor", "implementer", "high",
                               review_cycles=5, diff_size=200, task_id="T300")
        bad_outcome.pop("ts")
        lines.append(bad_outcome)

        with open(self.metrics, "w", encoding="utf-8") as fh:
            for obj in lines:
                fh.write(json.dumps(obj) + "\n")

        self.script = str(SCRIPTS_DIR / "persona-stats.py")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _parse_since(self, s):
        return persona_stats._parse_since(s)

    def _report(self, since=None):
        return persona_stats.analyze(
            self.metrics,
            since=self._parse_since(since) if since else None,
        )

    def _find_group(self, report, src, persona_id, role, tier):
        for g in report["segments"].get(src, []):
            if (g["persona_id"], g["role"], g["complexity_tier"]) == (persona_id, role, tier):
                return g
        return None

    def test_since_drops_older_events(self):
        """Events older than --since cutoff must be dropped."""
        report = self._report(since="2026-06-01")
        # OLD attempt (2026-05-01) must be gone.
        ba = self._find_group(report, "forced_control", "boring-anchor", "implementer", "high")
        self.assertIsNone(ba, "boring-anchor from 2026-05-01 must be excluded by --since 2026-06-01")

    def test_since_keeps_newer_events(self):
        """Events at or after --since cutoff must be retained."""
        report = self._report(since="2026-06-01")
        sr = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "high")
        self.assertIsNotNone(sr, "spicy-rebel from 2026-06-15 must survive --since 2026-06-01")
        self.assertEqual(sr["n_attempts"], 1)
        self.assertEqual(sr["metrics"]["review_cycles"], 3)

    def test_since_excludes_missing_ts_events_conservatively(self):
        """Events with missing ts are excluded when --since is set (conservative)."""
        # Without --since, the missing-ts boring-anchor attempt should appear.
        report_no_since = self._report(since=None)
        # The BAD-v1 attempt has no ts — without --since it passes the filter.
        # It contributes to boring-anchor forced_control HIGH counts.
        # (Also OLD-v1 boring-anchor is in there too without --since.)
        # With --since 2026-06-01: both OLD-v1 AND BAD-v1 must be excluded.
        report_since = self._report(since="2026-06-01")
        ba_since = self._find_group(report_since, "forced_control", "boring-anchor", "implementer", "high")
        # Neither OLD (2026-05-01) nor BAD (no ts) survives the --since filter.
        self.assertIsNone(ba_since, "boring-anchor with missing/old ts must be excluded by --since")

    def test_no_since_includes_all_events(self):
        """Without --since all parseable events (except unknown-run) are kept."""
        report = self._report(since=None)
        # OLD boring-anchor appears.
        ba = self._find_group(report, "forced_control", "boring-anchor", "implementer", "high")
        self.assertIsNotNone(ba, "boring-anchor must appear when no --since is set")
        # OLD + BAD both resolve to boring-anchor forced_control HIGH.
        # We should have 2 attempts (OLD-v1 and BAD-v1 both joined).
        self.assertEqual(ba["n_attempts"], 2)

    def test_since_iso8601_full_timestamp_accepted(self):
        """--since accepts a full ISO8601 timestamp (not just a date)."""
        since_dt = self._parse_since("2026-06-14T23:59:59Z")
        report = persona_stats.analyze(self.metrics, since=since_dt)
        sr = self._find_group(report, "random_role_pool", "spicy-rebel", "implementer", "high")
        self.assertIsNotNone(sr, "spicy-rebel at 2026-06-15 must survive --since 2026-06-14T23:59:59Z")

    def test_since_fractional_seconds_parses(self):
        """_parse_since must accept fractional-seconds ISO8601 (e.g. 2026-06-14T23:59:59.500Z).

        Invariant: a --since value with sub-second precision must parse without
        error and produce the correct UTC-aware datetime.
        Failure class: ValueError raised for a valid fractional-seconds timestamp.
        """
        import datetime as dt_mod
        since_dt = self._parse_since("2026-06-14T23:59:59.500Z")
        self.assertIsNotNone(since_dt)
        self.assertIsNotNone(since_dt.tzinfo, "parsed datetime must be timezone-aware")
        # Verify the fractional second is preserved (500ms = 500000 microseconds).
        self.assertEqual(since_dt.microsecond, 500000)
        # Verify the date/time components.
        self.assertEqual(since_dt.year, 2026)
        self.assertEqual(since_dt.month, 6)
        self.assertEqual(since_dt.day, 14)
        self.assertEqual(since_dt.hour, 23)
        self.assertEqual(since_dt.minute, 59)
        self.assertEqual(since_dt.second, 59)

    def test_fractional_seconds_event_ts_included_and_excluded(self):
        """Event ts with fractional seconds is correctly compared against --since.

        Invariant: _parse_event_ts must parse "2026-06-02T00:05:24.123Z" and the
        event must be included when since <= ts and excluded when since > ts.
        Failure class: fractional-seconds event ts returns None from _parse_event_ts,
        causing conservative exclusion even when the event should be included.
        """
        # Write a fixture with a fractional-seconds event ts.
        import tempfile, os, json as _json
        tmp = tempfile.mkdtemp()
        try:
            metrics = os.path.join(tmp, "frac_metrics.jsonl")
            frac_ts_draw = "2026-06-02T00:05:24.123Z"
            frac_ts_outcome = "2026-06-02T00:05:25.456Z"
            lines = [
                _draw("FRAC-v1", "d-frac-1", "spicy-rebel", "implementer",
                      "random_role_pool", task_id="T999", ts=frac_ts_draw),
                _outcome("FRAC-v1", "d-frac-1", "spicy-rebel", "implementer", "high",
                         review_cycles=7, diff_size=200, task_id="T999",
                         ts=frac_ts_outcome),
            ]
            with open(metrics, "w", encoding="utf-8") as fh:
                for obj in lines:
                    fh.write(_json.dumps(obj) + "\n")

            # _parse_event_ts must not return None for a fractional-seconds string.
            parsed_ts = persona_stats._parse_event_ts(frac_ts_draw)
            self.assertIsNotNone(parsed_ts,
                                 "_parse_event_ts must parse fractional-seconds ts, not return None")
            self.assertIsNotNone(parsed_ts.tzinfo, "parsed event ts must be timezone-aware")

            # With --since before the event, it must be INCLUDED.
            since_before = self._parse_since("2026-06-01T00:00:00Z")
            report_incl = persona_stats.analyze(metrics, since=since_before)
            sr_incl = None
            for g in report_incl["segments"].get("random_role_pool", []):
                if g["persona_id"] == "spicy-rebel":
                    sr_incl = g
                    break
            self.assertIsNotNone(sr_incl,
                                 "fractional-seconds event must be included when since < ts")
            self.assertEqual(sr_incl["n_attempts"], 1)

            # With --since after the event, it must be EXCLUDED.
            since_after = self._parse_since("2026-06-03T00:00:00Z")
            report_excl = persona_stats.analyze(metrics, since=since_after)
            sr_excl = None
            for g in report_excl["segments"].get("random_role_pool", []):
                if g["persona_id"] == "spicy-rebel":
                    sr_excl = g
                    break
            self.assertIsNone(sr_excl,
                              "fractional-seconds event must be excluded when since > ts")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class SinceCLIFixture(unittest.TestCase):
    """T107: CLI --since and --include-unknown-run flags work end-to-end."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.metrics = os.path.join(self.tmp, "metrics.jsonl")
        lines = [
            # Real-run event with a real ts.
            _draw("CLI-v1", "d-cli-1", "boring-anchor", "implementer", "forced_control",
                  ts="2026-06-10T00:00:00Z"),
            _outcome("CLI-v1", "d-cli-1", "boring-anchor", "implementer", "high",
                     review_cycles=2, ts="2026-06-10T00:00:05Z"),
            # unknown-run event.
            _draw("CLI-unk", "d-cli-unk", "spicy-rebel", "implementer", "random_role_pool",
                  run="unknown-run", ts="2026-06-10T00:00:00Z"),
            _outcome("CLI-unk", "d-cli-unk", "spicy-rebel", "implementer", "high",
                     review_cycles=7, run="unknown-run", ts="2026-06-10T00:00:05Z"),
        ]
        with open(self.metrics, "w", encoding="utf-8") as fh:
            for obj in lines:
                fh.write(json.dumps(obj) + "\n")
        self.script = str(SCRIPTS_DIR / "persona-stats.py")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cli_include_unknown_run_flag(self):
        """--include-unknown-run via CLI causes unknown-run draws to appear."""
        # Default: unknown-run hidden.
        proc_default = subprocess.run(
            [sys.executable, self.script, "--metrics", self.metrics, "--json"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc_default.returncode, 0, proc_default.stderr)
        parsed_default = json.loads(proc_default.stdout)
        # spicy-rebel should not appear in default mode.
        all_persona_ids = [
            g["persona_id"]
            for groups in parsed_default["segments"].values()
            for g in groups
        ]
        self.assertNotIn("spicy-rebel", all_persona_ids,
                         "spicy-rebel (unknown-run) must be absent by default")

        # With --include-unknown-run: spicy-rebel must appear.
        proc_incl = subprocess.run(
            [sys.executable, self.script, "--metrics", self.metrics,
             "--json", "--include-unknown-run"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc_incl.returncode, 0, proc_incl.stderr)
        parsed_incl = json.loads(proc_incl.stdout)
        all_persona_ids_incl = [
            g["persona_id"]
            for groups in parsed_incl["segments"].values()
            for g in groups
        ]
        self.assertIn("spicy-rebel", all_persona_ids_incl,
                      "spicy-rebel (unknown-run) must appear with --include-unknown-run")

    def test_cli_since_flag(self):
        """--since via CLI filters events by date."""
        # Events are at 2026-06-10; --since 2026-06-11 should exclude them.
        proc = subprocess.run(
            [sys.executable, self.script, "--metrics", self.metrics,
             "--json", "--since", "2026-06-11"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        parsed = json.loads(proc.stdout)
        all_persona_ids = [
            g["persona_id"]
            for groups in parsed["segments"].values()
            for g in groups
        ]
        self.assertEqual(all_persona_ids, [],
                         "All events are before 2026-06-11 cutoff; segments must be empty")

    def test_cli_since_invalid_value_errors(self):
        """--since with an unparseable value exits with return code 1."""
        proc = subprocess.run(
            [sys.executable, self.script, "--metrics", self.metrics,
             "--json", "--since", "not-a-date"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not parseable", proc.stderr)

    def test_cli_since_fractional_seconds_accepted(self):
        """--since with a fractional-seconds ISO8601 value must not error (exit 0).

        Invariant: the CLI must parse a fractional-seconds --since value and
        apply it as a filter.
        Failure class: exit code 1 with "not parseable" when the --since value
        contains sub-second precision.
        """
        # Events in this fixture are at 2026-06-10; --since with fractional
        # seconds just before midnight 2026-06-11 should exclude them.
        proc = subprocess.run(
            [sys.executable, self.script, "--metrics", self.metrics,
             "--json", "--since", "2026-06-10T23:59:59.999Z"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0,
                         f"--since with fractional seconds must not error; stderr: {proc.stderr}")
        parsed = json.loads(proc.stdout)
        # All events are at 2026-06-10T00:00:00Z / T00:00:05Z, before the cutoff.
        all_persona_ids = [
            g["persona_id"]
            for groups in parsed["segments"].values()
            for g in groups
        ]
        self.assertEqual(all_persona_ids, [],
                         "All events are before the fractional-seconds since cutoff")


if __name__ == "__main__":
    unittest.main()
