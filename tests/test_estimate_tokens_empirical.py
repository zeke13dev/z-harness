"""
Tests for scripts/estimate-tokens.py — empirical tier (T004).

Covers:
  TEST-003  empirical fires: synthetic metrics with >=2*min_samples completed
            z-research runs → empirical tier in breakdown, confidence:high,
            p50/p90 correct.
  TEST-004  empirical hygiene: fixture mixes in-flight, aborted
            (cost_gate_decision{choice:abandon}), halted, and malformed lines →
            all excluded; p50 computed only from normal completions.
  TEST-008  [audit B1] parent-run rollup: fixture with a parent z-research run +
            child z-map/z-brainstorm sub-runs (carrying parent_run_id/parent_command)
            → parent's empirical total includes child tokens; children are NOT
            double-counted as their own command's samples; static-floor clamp holds
            (undercounted empirical p50 does NOT lower estimated_tokens/range_low
            below the static floor).

HERMETICITY: every test builds a synthetic metrics.jsonl under a fresh tmpdir.
The real metrics.jsonl is never read or written.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(_REPO_ROOT / "scripts" / "estimate-tokens.py")
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_PROFILES_PATH = _SCRIPTS_DIR / "token-cost-profiles.json"

# Load the module directly so we can call internal helpers.
_spec = importlib.util.spec_from_file_location("estimate_tokens", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_estimate = _mod.estimate
_empirical_tier = _mod._empirical_tier
_event_tokens = _mod._event_tokens
_percentile = _mod._percentile


# ---------------------------------------------------------------------------
# Fixture builder helpers
# ---------------------------------------------------------------------------

def _write_metrics(path: Path, events: list[dict]) -> None:
    """Write events as newline-delimited JSON to path."""
    with open(path, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")


def _completed_research_run(
    run_id: str,
    ts_base: str,
    *,
    own_tokens: int = 200000,
    child_tokens: int = 0,
) -> list[dict]:
    """Return a list of events for a normally-completed z-research parent run.

    own_tokens   — tokens attributed to the parent run's own events (split
                   evenly between start and end for simplicity).
    child_tokens — tokens attributed to a child run (z-map) with parent_run_id
                   set to run_id.
    """
    half_own = own_tokens // 2
    events: list[dict] = [
        {
            "run": run_id,
            "kind": "research_run_start",
            "command": "z-research",
            "ts": f"{ts_base}T00:00:00Z",
            "subagent_input_tokens": half_own,
            "subagent_output_tokens": half_own // 2,
        },
        {
            "run": run_id,
            "kind": "research_run_end",
            "command": "z-research",
            "ts": f"{ts_base}T00:30:00Z",
            "status": "ok",
            "subagent_input_tokens": half_own,
            "subagent_output_tokens": half_own // 2,
        },
    ]
    if child_tokens:
        half_child = child_tokens // 2
        child_run = f"{run_id}-child"
        events.extend([
            {
                "run": child_run,
                "kind": "run_start",
                "parent_run_id": run_id,
                "parent_command": "z-research",
                "command": "z-map",
                "ts": f"{ts_base}T00:01:00Z",
                "subagent_input_tokens": half_child,
                "subagent_output_tokens": half_child // 2,
            },
            {
                "run": child_run,
                "kind": "run_end",
                "parent_run_id": run_id,
                "parent_command": "z-research",
                "command": "z-map",
                "ts": f"{ts_base}T00:15:00Z",
                "status": "ok",
                "subagent_input_tokens": half_child,
                "subagent_output_tokens": half_child // 2,
            },
        ])
    return events


# ---------------------------------------------------------------------------
# TEST-003: empirical fires with >=2*min_samples completed runs
# ---------------------------------------------------------------------------

class TestEmpericalFires(unittest.TestCase):
    """TEST-003: empirical tier fires and confidence=high when samples >= 2*min_samples."""

    def _run_estimate(self, metrics_path: Path, command: str = "z-research", min_samples: int = 3):
        return _estimate(
            raw_command=command,
            dispatch_pairs=[],
            profiles_path=_PROFILES_PATH,
            metrics_path=metrics_path,
            tail_lines=2000,
            min_samples=min_samples,
        )

    def test_empirical_tier_fires_with_enough_samples(self):
        """Empirical tier appears in breakdown when >= min_samples completed runs exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            events = []
            # 6 completed runs → 6 samples, min_samples=3, so confidence=high
            for i in range(6):
                own = 2000000 + i * 200000
                events.extend(_completed_research_run(
                    run_id=f"r{i}",
                    ts_base=f"2026-05-0{i+1}",
                    own_tokens=own,
                ))
            _write_metrics(mpath, events)
            result = self._run_estimate(mpath, min_samples=3)

        # Empirical tier present in breakdown
        tier_names = [b["tier"] for b in result["breakdown"]]
        self.assertIn("empirical", tier_names)

        emp = next(b for b in result["breakdown"] if b["tier"] == "empirical")
        self.assertIn("p50", emp)
        self.assertIn("p90", emp)
        self.assertIn("samples", emp)
        self.assertEqual(emp["samples"], 6)

        # confidence=high because samples (6) >= 2*min_samples (6)
        self.assertEqual(result["confidence"], "high")

    def test_p50_p90_correct_for_known_totals(self):
        """p50/p90 match manual computation over the known total set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            # Use exact token values so we know the totals:
            # Each run: own_tokens = X → total = X (start carries X//2 in+out,
            # end carries X//2 in+out; total = X//2*1.5 * 2... let's use a flat
            # subagent_input_tokens assignment instead).
            #
            # Build events manually for precise totals:
            own_per_run = [1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000, 6_000_000]
            events = []
            for i, own in enumerate(own_per_run):
                run = f"precise-r{i}"
                # start: input=own, output=0 → tokens = own
                events.append({
                    "run": run, "kind": "research_run_start", "command": "z-research",
                    "ts": f"2026-05-{i+1:02d}T01:00:00Z",
                    "subagent_input_tokens": own, "subagent_output_tokens": 0,
                })
                # end: input=0, output=0 → tokens = 0
                events.append({
                    "run": run, "kind": "research_run_end", "command": "z-research",
                    "ts": f"2026-05-{i+1:02d}T01:30:00Z",
                    "status": "ok",
                    "subagent_input_tokens": 0, "subagent_output_tokens": 0,
                })
            _write_metrics(mpath, events)
            result = self._run_estimate(mpath, min_samples=3)

        emp = next(b for b in result["breakdown"] if b["tier"] == "empirical")
        # sorted totals = [1M, 2M, 3M, 4M, 5M, 6M]
        # p50: idx = 0.5*5 = 2.5 → 3M*0.5 + 4M*0.5 = 3.5M
        # p90: idx = 0.9*5 = 4.5 → 5M*0.5 + 6M*0.5 = 5.5M
        self.assertEqual(emp["p50"], 3_500_000)
        self.assertEqual(emp["p90"], 5_500_000)
        self.assertEqual(emp["samples"], 6)

    def test_empirical_does_not_fire_below_min_samples(self):
        """Empirical tier does NOT fire when samples < min_samples."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            events = _completed_research_run("r0", "2026-05-01", own_tokens=2_000_000)
            _write_metrics(mpath, events)
            # Only 1 sample, min_samples=3 → empirical should not fire
            result = self._run_estimate(mpath, min_samples=3)

        tier_names = [b["tier"] for b in result["breakdown"]]
        self.assertNotIn("empirical", tier_names)
        # Confidence: static-only → "low"
        self.assertEqual(result["confidence"], "low")

    def test_empirical_confidence_medium_when_samples_lt_2x_min(self):
        """Empirical fires but confidence=medium when min_samples <= samples < 2*min_samples."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            events = []
            for i in range(4):  # 4 samples, min_samples=3, 4 < 6 → medium
                events.extend(_completed_research_run(f"r{i}", f"2026-05-0{i+1}", own_tokens=2_000_000))
            _write_metrics(mpath, events)
            result = self._run_estimate(mpath, min_samples=3)

        tier_names = [b["tier"] for b in result["breakdown"]]
        self.assertIn("empirical", tier_names)
        emp = next(b for b in result["breakdown"] if b["tier"] == "empirical")
        self.assertEqual(emp["samples"], 4)
        self.assertEqual(result["confidence"], "medium")


# ---------------------------------------------------------------------------
# TEST-004: empirical hygiene — excluded run categories
# ---------------------------------------------------------------------------

class TestEmpericalHygiene(unittest.TestCase):
    """TEST-004: in-flight, abandoned, halted, errored, and malformed lines are excluded."""

    def _run_direct(self, metrics_path: Path, command: str = "z-research", min_samples: int = 1):
        return _empirical_tier(command, metrics_path, tail_lines=2000, min_samples=min_samples)

    def test_malformed_json_lines_skipped(self):
        """Malformed JSON lines are skipped; valid events still parsed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            events = _completed_research_run("r0", "2026-05-01", own_tokens=2_000_000)
            with open(mpath, "w") as fh:
                for ev in events:
                    fh.write(json.dumps(ev) + "\n")
                fh.write("NOT_VALID_JSON\n")
                fh.write('{"incomplete":\n')  # also malformed
            result = self._run_direct(mpath, min_samples=1)

        # Should still get 1 sample (from the valid run)
        self.assertIsNotNone(result)
        self.assertEqual(result["samples"], 1)

    def test_abandoned_run_excluded(self):
        """Runs with cost_gate_decision{choice:abandon} are excluded from the sample set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            # 2 good runs + 1 abandoned run
            events = []
            events.extend(_completed_research_run("r0", "2026-05-01", own_tokens=2_000_000))
            events.extend(_completed_research_run("r1", "2026-05-02", own_tokens=3_000_000))
            # Abandoned run
            events.extend([
                {"run": "r-ab", "kind": "research_run_start", "command": "z-research",
                 "ts": "2026-05-03T00:00:00Z", "subagent_input_tokens": 10000, "subagent_output_tokens": 5000},
                {"run": "r-ab", "kind": "cost_gate_decision", "command": "z-research",
                 "ts": "2026-05-03T00:01:00Z", "choice": "abandon"},
            ])
            _write_metrics(mpath, events)
            result = self._run_direct(mpath, min_samples=1)

        self.assertIsNotNone(result)
        # Abandoned run NOT counted: only 2 qualifying samples
        self.assertEqual(result["samples"], 2)

    def test_halted_run_excluded(self):
        """Runs with terminal status=halted are excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            events = []
            events.extend(_completed_research_run("r0", "2026-05-01", own_tokens=2_000_000))
            events.extend(_completed_research_run("r1", "2026-05-02", own_tokens=3_000_000))
            # Halted run
            events.extend([
                {"run": "r-halt", "kind": "research_run_start", "command": "z-research",
                 "ts": "2026-05-03T00:00:00Z", "subagent_input_tokens": 10000, "subagent_output_tokens": 5000},
                {"run": "r-halt", "kind": "research_run_end", "command": "z-research",
                 "ts": "2026-05-03T00:01:00Z", "status": "halted",
                 "subagent_input_tokens": 0, "subagent_output_tokens": 0},
            ])
            _write_metrics(mpath, events)
            result = self._run_direct(mpath, min_samples=1)

        self.assertIsNotNone(result)
        self.assertEqual(result["samples"], 2)

    def test_errored_run_excluded(self):
        """Runs with terminal status=errored are excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            events = []
            events.extend(_completed_research_run("r0", "2026-05-01", own_tokens=2_000_000))
            # Errored run
            events.extend([
                {"run": "r-err", "kind": "research_run_start", "command": "z-research",
                 "ts": "2026-05-02T00:00:00Z", "subagent_input_tokens": 10000, "subagent_output_tokens": 5000},
                {"run": "r-err", "kind": "research_run_end", "command": "z-research",
                 "ts": "2026-05-02T00:01:00Z", "status": "errored",
                 "subagent_input_tokens": 0, "subagent_output_tokens": 0},
            ])
            _write_metrics(mpath, events)
            result = self._run_direct(mpath, min_samples=1)

        self.assertIsNotNone(result)
        self.assertEqual(result["samples"], 1)

    def test_aborted_by_user_excluded(self):
        """Runs with terminal status=aborted_by_user are excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            events = []
            events.extend(_completed_research_run("r0", "2026-05-01", own_tokens=2_000_000))
            # Aborted run
            events.extend([
                {"run": "r-abort", "kind": "research_run_start", "command": "z-research",
                 "ts": "2026-05-02T00:00:00Z", "subagent_input_tokens": 10000, "subagent_output_tokens": 5000},
                {"run": "r-abort", "kind": "research_run_end", "command": "z-research",
                 "ts": "2026-05-02T00:01:00Z", "status": "aborted_by_user",
                 "subagent_input_tokens": 0, "subagent_output_tokens": 0},
            ])
            _write_metrics(mpath, events)
            result = self._run_direct(mpath, min_samples=1)

        self.assertIsNotNone(result)
        self.assertEqual(result["samples"], 1)

    def test_inflight_run_excluded(self):
        """In-flight runs (no terminal event, latest_ts within 5 min of max_ts) are excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            events = []
            events.extend(_completed_research_run("r0", "2026-05-01", own_tokens=2_000_000))
            events.extend(_completed_research_run("r1", "2026-05-02", own_tokens=3_000_000))
            # In-flight run: latest event is 3 min before max_ts (2026-05-03T00:07:00Z)
            # max_ts is determined by the last event overall
            events.extend([
                {"run": "r-inflight", "kind": "research_run_start", "command": "z-research",
                 "ts": "2026-05-03T00:04:00Z",  # 3 min before max_ts → in-flight
                 "subagent_input_tokens": 10000, "subagent_output_tokens": 5000},
                # This is max_ts — a separate completed run sets it later
            ])
            # Add a later event to push max_ts to 2026-05-03T00:07:00Z
            events.append({
                "run": "r-other", "kind": "run_start", "command": "z-plan",
                "ts": "2026-05-03T00:07:00Z",
                "subagent_input_tokens": 1000, "subagent_output_tokens": 500,
            })
            events.append({
                "run": "r-other", "kind": "run_end", "command": "z-plan",
                "ts": "2026-05-03T00:07:30Z", "status": "ok",
                "subagent_input_tokens": 0, "subagent_output_tokens": 0,
            })
            _write_metrics(mpath, events)
            result = self._run_direct(mpath, min_samples=1)

        self.assertIsNotNone(result)
        # In-flight run excluded: only 2 qualifying samples
        self.assertEqual(result["samples"], 2)

    def test_prompt_chars_fallback(self):
        """prompt_chars/response_chars are used when subagent token fields absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            events = [
                {"run": "r0", "kind": "research_run_start", "command": "z-research",
                 "ts": "2026-05-01T00:00:00Z",
                 "prompt_chars": 4000000,  # 4M chars / 4 = 1M tokens
                 "response_chars": 2000000},  # 2M chars / 4 = 500K tokens
                {"run": "r0", "kind": "research_run_end", "command": "z-research",
                 "ts": "2026-05-01T00:30:00Z", "status": "ok",
                 "subagent_input_tokens": 0, "subagent_output_tokens": 0},
            ]
            _write_metrics(mpath, events)
            result = self._run_direct(mpath, min_samples=1)

        self.assertIsNotNone(result)
        self.assertEqual(result["samples"], 1)
        # prompt_chars/4 = 1_000_000, response_chars/4 = 500_000, plus end event 0
        self.assertEqual(result["p50"], 1_500_000)


# ---------------------------------------------------------------------------
# TEST-008: parent-run rollup + static-floor clamp
# ---------------------------------------------------------------------------

class TestParentRunRollup(unittest.TestCase):
    """TEST-008: parent-run rollup, no double-counting, static-floor clamp."""

    def test_child_tokens_included_in_parent_bucket(self):
        """Parent run's empirical total includes tokens from child runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"

            # 3 parent z-research runs, each with a z-map child run and a z-brainstorm child run
            events = []
            for i in range(3):
                run_p = f"parent-{i}"
                run_c_map = f"child-map-{i}"
                run_c_bst = f"child-bst-{i}"
                parent_own = 100_000
                map_tokens = 1_000_000
                bst_tokens = 500_000
                ts_date = f"2026-05-{i+1:02d}"

                # Parent own events
                events.extend([
                    {"run": run_p, "kind": "research_run_start", "command": "z-research",
                     "ts": f"{ts_date}T00:00:00Z",
                     "subagent_input_tokens": parent_own // 2, "subagent_output_tokens": parent_own // 4},
                    {"run": run_p, "kind": "research_run_end", "command": "z-research",
                     "ts": f"{ts_date}T01:00:00Z", "status": "ok",
                     "subagent_input_tokens": parent_own // 4, "subagent_output_tokens": parent_own // 8},
                ])
                # Child z-map events
                events.extend([
                    {"run": run_c_map, "kind": "run_start", "parent_run_id": run_p,
                     "parent_command": "z-research", "command": "z-map",
                     "ts": f"{ts_date}T00:05:00Z",
                     "subagent_input_tokens": map_tokens // 2, "subagent_output_tokens": map_tokens // 4},
                    {"run": run_c_map, "kind": "run_end", "parent_run_id": run_p,
                     "parent_command": "z-research", "command": "z-map",
                     "ts": f"{ts_date}T00:30:00Z", "status": "ok",
                     "subagent_input_tokens": map_tokens // 4, "subagent_output_tokens": map_tokens // 8},
                ])
                # Child z-brainstorm events
                events.extend([
                    {"run": run_c_bst, "kind": "brainstorm_run_start", "parent_run_id": run_p,
                     "parent_command": "z-research", "command": "z-brainstorm",
                     "ts": f"{ts_date}T00:35:00Z",
                     "subagent_input_tokens": bst_tokens // 2, "subagent_output_tokens": bst_tokens // 4},
                    {"run": run_c_bst, "kind": "brainstorm_run_end", "parent_run_id": run_p,
                     "parent_command": "z-research", "command": "z-brainstorm",
                     "ts": f"{ts_date}T00:50:00Z", "status": "ok",
                     "subagent_input_tokens": bst_tokens // 4, "subagent_output_tokens": bst_tokens // 8},
                ])

            _write_metrics(mpath, events)

            result = _empirical_tier("z-research", mpath, tail_lines=2000, min_samples=1)

        self.assertIsNotNone(result)
        self.assertEqual(result["samples"], 3)

        # Each parent bucket total:
        # parent_own events: 100K//2 + 100K//4 + 100K//4 + 100K//8 = 50K+25K+25K+12.5K = 112500
        # map child events: 1M//2 + 1M//4 + 1M//4 + 1M//8 = 500K+250K+250K+125K = 1125000
        # bst child events: 500K//2 + 500K//4 + 500K//4 + 500K//8 = 250K+125K+125K+62.5K = 562500
        # total per parent = 112500 + 1125000 + 562500 = 1800000
        expected_total = 1_800_000
        self.assertEqual(result["p50"], expected_total)  # all 3 runs same total → p50 = median

    def test_child_runs_not_double_counted_for_their_own_command(self):
        """Child z-brainstorm/z-map runs with parent_run_id do NOT appear as standalone samples."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"

            # 3 parent z-research runs, each with a z-brainstorm child
            # Also 1 standalone z-brainstorm run (no parent_run_id)
            events = []
            for i in range(3):
                run_p = f"parent-{i}"
                run_c = f"child-bst-{i}"
                ts_date = f"2026-05-{i+1:02d}"
                events.extend([
                    {"run": run_p, "kind": "research_run_start", "command": "z-research",
                     "ts": f"{ts_date}T00:00:00Z",
                     "subagent_input_tokens": 100_000, "subagent_output_tokens": 50_000},
                    {"run": run_c, "kind": "brainstorm_run_start", "parent_run_id": run_p,
                     "parent_command": "z-research", "command": "z-brainstorm",
                     "ts": f"{ts_date}T00:05:00Z",
                     "subagent_input_tokens": 500_000, "subagent_output_tokens": 200_000},
                    {"run": run_c, "kind": "brainstorm_run_end", "parent_run_id": run_p,
                     "parent_command": "z-research", "command": "z-brainstorm",
                     "ts": f"{ts_date}T00:20:00Z", "status": "ok",
                     "subagent_input_tokens": 100_000, "subagent_output_tokens": 50_000},
                    {"run": run_p, "kind": "research_run_end", "command": "z-research",
                     "ts": f"{ts_date}T00:25:00Z", "status": "ok",
                     "subagent_input_tokens": 50_000, "subagent_output_tokens": 20_000},
                ])

            # Standalone z-brainstorm run
            events.extend([
                {"run": "standalone-bst", "kind": "brainstorm_run_start", "command": "z-brainstorm",
                 "ts": "2026-05-10T00:00:00Z",
                 "subagent_input_tokens": 80_000, "subagent_output_tokens": 30_000},
                {"run": "standalone-bst", "kind": "brainstorm_run_end", "command": "z-brainstorm",
                 "ts": "2026-05-10T00:10:00Z", "status": "ok",
                 "subagent_input_tokens": 20_000, "subagent_output_tokens": 10_000},
            ])

            _write_metrics(mpath, events)

            bst_result = _empirical_tier("z-brainstorm", mpath, tail_lines=2000, min_samples=1)

        # Only the standalone brainstorm should count as a z-brainstorm sample.
        # The 3 child brainstorm runs are attributed to their parent (z-research) bucket.
        self.assertIsNotNone(bst_result)
        self.assertEqual(bst_result["samples"], 1,
                         "Child brainstorm runs must NOT be double-counted as z-brainstorm samples")

    def test_static_floor_clamp_prevents_undercount(self):
        """Empirical p50 below static floor does NOT lower estimated_tokens or range_low."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"

            # z-research static_low = 3_000_000; create runs with very small token totals
            events = []
            for i in range(3):
                run = f"tiny-r{i}"
                ts_date = f"2026-05-{i+1:02d}"
                events.extend([
                    {"run": run, "kind": "research_run_start", "command": "z-research",
                     "ts": f"{ts_date}T00:00:00Z",
                     "subagent_input_tokens": 10_000, "subagent_output_tokens": 5_000},
                    {"run": run, "kind": "research_run_end", "command": "z-research",
                     "ts": f"{ts_date}T00:30:00Z", "status": "ok",
                     "subagent_input_tokens": 0, "subagent_output_tokens": 0},
                ])
            _write_metrics(mpath, events)

            result = _estimate(
                raw_command="z-research",
                dispatch_pairs=[],
                profiles_path=_PROFILES_PATH,
                metrics_path=mpath,
                tail_lines=2000,
                min_samples=1,
            )

        emp = next((b for b in result["breakdown"] if b["tier"] == "empirical"), None)
        self.assertIsNotNone(emp, "Empirical tier should fire with 3 samples")

        # Empirical p50 should be tiny (15K)
        self.assertLess(emp["p50"], 100_000)

        # But estimated_tokens must be clamped to static_low (3_000_000)
        self.assertEqual(result["estimated_tokens"], 3_000_000,
                         "estimated_tokens must not drop below static floor")
        # range_low must remain at static_low (3_000_000)
        self.assertEqual(result["range_low"], 3_000_000,
                         "range_low must not drop below static floor")

    def test_empirical_widens_upward_when_above_floor(self):
        """Empirical p50 above static floor correctly widens estimated_tokens upward."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            # z-research static_low = 3M; use runs that sum to > 3M
            for_tokens = [4_000_000, 5_000_000, 6_000_000]
            events = []
            for i, tok in enumerate(for_tokens):
                run = f"big-r{i}"
                ts_date = f"2026-05-{i+1:02d}"
                events.extend([
                    {"run": run, "kind": "research_run_start", "command": "z-research",
                     "ts": f"{ts_date}T00:00:00Z",
                     "subagent_input_tokens": tok, "subagent_output_tokens": 0},
                    {"run": run, "kind": "research_run_end", "command": "z-research",
                     "ts": f"{ts_date}T00:30:00Z", "status": "ok",
                     "subagent_input_tokens": 0, "subagent_output_tokens": 0},
                ])
            _write_metrics(mpath, events)

            result = _estimate(
                raw_command="z-research",
                dispatch_pairs=[],
                profiles_path=_PROFILES_PATH,
                metrics_path=mpath,
                tail_lines=2000,
                min_samples=1,
            )

        # p50 of [4M, 5M, 6M] = 5M (median)
        # 5M > static_low (3M), so estimated_tokens = 5M
        self.assertEqual(result["estimated_tokens"], 5_000_000)
        # range_low stays at static floor
        self.assertEqual(result["range_low"], 3_000_000)

    def test_empirical_p90_above_static_high_widens_range_high(self):
        """range_high = max(static_high, empirical_p90) — widens upward when needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            # z-research static_high = 6M; use runs yielding p90 > 6M
            for_tokens = [4_000_000, 5_000_000, 10_000_000]
            events = []
            for i, tok in enumerate(for_tokens):
                run = f"huge-r{i}"
                ts_date = f"2026-05-{i+1:02d}"
                events.extend([
                    {"run": run, "kind": "research_run_start", "command": "z-research",
                     "ts": f"{ts_date}T00:00:00Z",
                     "subagent_input_tokens": tok, "subagent_output_tokens": 0},
                    {"run": run, "kind": "research_run_end", "command": "z-research",
                     "ts": f"{ts_date}T00:30:00Z", "status": "ok",
                     "subagent_input_tokens": 0, "subagent_output_tokens": 0},
                ])
            _write_metrics(mpath, events)

            result = _estimate(
                raw_command="z-research",
                dispatch_pairs=[],
                profiles_path=_PROFILES_PATH,
                metrics_path=mpath,
                tail_lines=2000,
                min_samples=1,
            )

        # sorted totals = [4M, 5M, 10M]
        # p90: idx = 0.9*2 = 1.8 → 5M*0.2 + 10M*0.8 = 1M + 8M = 9M
        # range_high = max(6M, 9M) = 9M
        self.assertEqual(result["range_high"], 9_000_000)

    def test_kind_inference_attribution(self):
        """Command attributed correctly via _KIND_TO_COMMAND when 'command' field absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mpath = Path(tmpdir) / "metrics.jsonl"
            # Use legacy events without 'command' field — only kind
            events = [
                {"run": "r0", "kind": "research_run_start",
                 "ts": "2026-05-01T00:00:00Z",
                 "subagent_input_tokens": 2_000_000, "subagent_output_tokens": 500_000},
                {"run": "r0", "kind": "research_run_end",
                 "ts": "2026-05-01T01:00:00Z", "status": "ok",
                 "subagent_input_tokens": 0, "subagent_output_tokens": 0},
            ]
            _write_metrics(mpath, events)
            result = _empirical_tier("z-research", mpath, tail_lines=2000, min_samples=1)

        self.assertIsNotNone(result, "Kind-based inference should attribute run to z-research")
        self.assertEqual(result["samples"], 1)


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
