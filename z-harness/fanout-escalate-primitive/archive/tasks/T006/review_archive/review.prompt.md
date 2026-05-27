You are reviewing code that Claude just wrote for task T006: Write scripts/scope-probe-calibrate.py framework.

Spec excerpt (scripts/scope-probe-calibrate.py section from fanout-escalate-primitive/SPEC.md):
CLI: `python3 scripts/scope-probe-calibrate.py --archive-root z-harness/archive [--epoch N] [--n-runs 6] [--samples-per-run 3]`.

**Behavior:**
1. Walk `z-harness/*/archive/*/` directories. Pick up to `n_runs` recent runs that have `manifest.json` (skip incomplete runs).
2. For each picked run, extract: `slug`, `topic` (from `events.jsonl` `run_start`), `manifest.json`, `events.jsonl` escalation events.
3. Compute ground-truth `LIGHT|MEDIUM|HEAVY` per the rubric (see [scripts/CALIBRATION.md](../scripts/CALIBRATION.md)).
4. For each run, dispatch `scope-probe` `samples_per_run` times (default 3) via a CLI shim (subprocess; replicate the Agent-dispatch prompt format). Take majority-vote classification as the run's Haiku-classification.
5. Compute confusion matrix: scope-probe-MODE × ground-truth-MODE.
6. Emit `scripts/calibration-epoch-<N>.json`: `{epoch, rubric_version, n_runs, samples_per_run, runs: [{slug, run_id, topic, classified_mode, ground_truth_mode, match}], confusion_matrix, pct_heavy, pct_medium, pct_light}`.
7. Print a tripwire report to stdout:
   - **Tripwire 1** (≥70% MEDIUM): warn if `pct_medium >= 70`.
   - **Tripwire 2** (<20% HEAVY): warn if `pct_heavy < 20`.
   - **Tripwires 3, 4** (synthesis quality, semantic axis): require manual review; flag for human follow-up.

**Exit codes:** 0 if no tripwires fire; 1 if any tripwire fires.

Acceptance criteria:
- CLI flags: --archive-root, --epoch N, --n-runs N, --samples-per-run N.
- Walks z-harness/*/archive/*/ finding runs with manifest.json.
- Implements classify_ground_truth(manifest, events) per CALIBRATION.md.
- Scope-probe dispatch shim stub returning MEDIUM in normal mode; reads JSON fixture in --fixture-mode.
- Confusion matrix + tripwire report.
- Emits scripts/calibration-epoch-<N>.json per SPEC.
- Tripwire 1 (pct_medium >= 70) and Tripwire 2 (pct_heavy < 20) cause exit code 1.

Diff (primary artifact):
```
diff --git a/scripts/scope-probe-calibrate.py b/scripts/scope-probe-calibrate.py
new file mode 100644
index 0000000..4286c30
--- /dev/null
+++ b/scripts/scope-probe-calibrate.py
@@ -0,0 +1,508 @@
+#!/usr/bin/env python3
+"""
+Calibration harness for scope-probe classifier.
+
+Usage:
+    python3 scripts/scope-probe-calibrate.py \
+        --archive-root z-harness \
+        [--epoch N] \
+        [--n-runs 6] \
+        [--samples-per-run 3] \
+        [--fixture-mode <fixture-file.json>]
+
+Walks z-harness/*/archive/*/ looking for runs with manifest.json, computes
+ground-truth classifications per CALIBRATION.md rubric (rubric_version 1),
+dispatches scope-probe N times per run (or reads a fixture in --fixture-mode),
+and emits scripts/calibration-epoch-<N>.json.
+
+Exit codes:
+  0 — no tripwires fired
+  1 — at least one tripwire fired
+"""
+
+from __future__ import annotations
+
+import argparse
+import json
+import os
+import sys
+from pathlib import Path
+from typing import Optional
+
+
+# ---------------------------------------------------------------------------
+# Ground-truth classification (rubric_version 1, per scripts/CALIBRATION.md)
+# ---------------------------------------------------------------------------
+
+def classify_ground_truth(manifest: dict, events: list[dict]) -> str:
+    """Returns 'LIGHT' | 'MEDIUM' | 'HEAVY' from a historical run's artifacts.
+
+    Rule (rubric_version 1):
+      - HEAVY if events contains any escalation_* event OR manifest.tasks_total >= 16.
+      - LIGHT if manifest.tasks_total <= 5 AND tasks_complexity.high == 0
+              AND no plan_route_decision event.
+      - MEDIUM otherwise.
+    Tie-break: if signals disagree, prefer escalation event > tasks_complexity > tasks_total.
+    """
+    tasks_total: int = manifest.get("tasks_total", 0)
+    tasks_complexity: dict = manifest.get("tasks_complexity", {})
+    high_count: int = tasks_complexity.get("high", 0)
+
+    has_escalation = any(
+        str(e.get("type", e.get("kind", ""))).startswith("escalation_")
+        for e in events
+    )
+    has_plan_route = any(
+        str(e.get("type", e.get("kind", ""))) == "plan_route_decision"
+        for e in events
+    )
+
+    # HEAVY: escalation event (highest priority) OR large plan
+    if has_escalation or tasks_total >= 16:
+        return "HEAVY"
+
+    # LIGHT: small, no high-complexity tasks, no route decision
+    if tasks_total <= 5 and high_count == 0 and not has_plan_route:
+        return "LIGHT"
+
+    return "MEDIUM"
+
+
+# ---------------------------------------------------------------------------
+# Archive walking
+# ---------------------------------------------------------------------------
+
+def load_events(run_dir: Path) -> list[dict]:
+    """Parse events.jsonl; return list of event dicts (skip malformed lines)."""
+    events_path = run_dir / "events.jsonl"
+    if not events_path.exists():
+        return []
+    events: list[dict] = []
+    with events_path.open(encoding="utf-8") as fh:
+        for line in fh:
+            line = line.strip()
+            if not line:
+                continue
+            try:
+                events.append(json.loads(line))
+            except json.JSONDecodeError:
+                pass  # skip malformed lines
+    return events
+
+
+def extract_topic(events: list[dict]) -> str:
+    """Extract topic/task text from run_start event."""
+    for event in events:
+        kind = event.get("kind") or event.get("type") or ""
+        if kind == "run_start":
+            return str(event.get("task", ""))
+    return ""
+
+
+def discover_runs(archive_root: Path, n_runs: int) -> list[dict]:
+    """
+    Walk archive_root/*/archive/*/ and collect up to n_runs recent runs
+    that have manifest.json. Returns list of run info dicts.
+    """
+    run_infos: list[dict] = []
+
+    # Search both slug-level dirs and nested plans/ style dirs
+    for slug_dir in sorted(archive_root.iterdir()):
+        if not slug_dir.is_dir():
+            continue
+        archive_dir = slug_dir / "archive"
+        if not archive_dir.is_dir():
+            continue
+        for run_dir in sorted(archive_dir.iterdir(), reverse=True):
+            if not run_dir.is_dir():
+                continue
+            manifest_path = run_dir / "manifest.json"
+            if not manifest_path.exists():
+                continue
+            try:
+                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
+            except (json.JSONDecodeError, OSError):
+                continue
+            events = load_events(run_dir)
+            run_infos.append({
+                "slug": slug_dir.name,
+                "run_id": run_dir.name,
+                "run_dir": run_dir,
+                "manifest": manifest,
+                "events": events,
+                "topic": extract_topic(events),
+            })
+
+    # Sort by run_id (ISO timestamp prefix) descending, then cap at n_runs
+    run_infos.sort(key=lambda r: r["run_id"], reverse=True)
+    return run_infos[:n_runs]
+
+
+# ---------------------------------------------------------------------------
+# Scope-probe dispatch shim
+# ---------------------------------------------------------------------------
+
+def dispatch_scope_probe_fixture(
+    fixture_path: Path,
+    run_info: dict,
+    sample_index: int,
+) -> str:
+    """
+    Fixture-mode shim: reads a JSON fixture file and returns the MODE
+    for the given run/sample. The fixture file format is either:
+      - A flat dict {run_id -> mode_str} — same mode for all samples.
+      - A nested dict {run_id -> [mode_str, ...]} — per-sample modes (index wrapped).
+      - A single string "LIGHT"|"MEDIUM"|"HEAVY" applied to all runs.
+    Returns one of "LIGHT", "MEDIUM", "HEAVY".
+    """
+    try:
+        data = json.loads(fixture_path.read_text(encoding="utf-8"))
+    except (json.JSONDecodeError, OSError) as exc:
+        raise SystemExit(f"ERROR: cannot read fixture file {fixture_path}: {exc}") from exc
+
+    run_id = run_info["run_id"]
+
+    if isinstance(data, str):
+        return _validate_mode(data)
+
+    if isinstance(data, dict):
+        value = data.get(run_id)
+        if value is None:
+            # Fallback: return MEDIUM when run not in fixture
+            return "MEDIUM"
+        if isinstance(value, list):
+            idx = sample_index % len(value)
+            return _validate_mode(value[idx])
+        return _validate_mode(str(value))
+
+    return "MEDIUM"
+
+
+def _validate_mode(mode: str) -> str:
+    """Return mode if valid; fall back to MEDIUM."""
+    if mode.upper() in ("LIGHT", "MEDIUM", "HEAVY"):
+        return mode.upper()
+    return "MEDIUM"
+
+
+def dispatch_scope_probe_stub(run_info: dict, sample_index: int) -> str:
+    """
+    Normal-mode stub: placeholder that always returns MEDIUM.
+
+    T009/T010 will integrate scope-probe into z-audit/z-brainstorm hosts.
+    T014 will be the first real calibration run that dispatches scope-probe
+    as a subprocess. Until then this stub allows end-to-end harness runs.
+    """
+    return "MEDIUM"
+
+
+def dispatch_scope_probe(
+    run_info: dict,
+    sample_index: int,
+    fixture_path: Optional[Path],
+) -> str:
+    """Route to fixture shim or normal stub based on fixture_path."""
+    if fixture_path is not None:
+        return dispatch_scope_probe_fixture(fixture_path, run_info, sample_index)
+    return dispatch_scope_probe_stub(run_info, sample_index)
+
+
+# ---------------------------------------------------------------------------
+# Majority vote
+# ---------------------------------------------------------------------------
+
+def majority_vote(votes: list[str]) -> str:
+    """Return the mode with the most votes; MEDIUM on tie."""
+    counts: dict[str, int] = {"LIGHT": 0, "MEDIUM": 0, "HEAVY": 0}
+    for v in votes:
+        counts[v] = counts.get(v, 0) + 1
+    return max(counts, key=lambda k: (counts[k], k == "MEDIUM"))
+
+
+# ---------------------------------------------------------------------------
+# Confusion matrix + tripwire report
+# ---------------------------------------------------------------------------
+
+def build_confusion_matrix(run_results: list[dict]) -> dict:
+    """
+    Build confusion matrix: classified_mode × ground_truth_mode.
+    Keys are dicts where outer key = probe classification, inner key = ground truth.
+    """
+    modes = ["LIGHT", "MEDIUM", "HEAVY"]
+    matrix: dict[str, dict[str, int]] = {m: {n: 0 for n in modes} for m in modes}
+    for r in run_results:
+        classified = r["classified_mode"]
+        truth = r["ground_truth_mode"]
+        if classified in matrix and truth in matrix[classified]:
+            matrix[classified][truth] += 1
+    return matrix
+
+
+def compute_percentages(run_results: list[dict]) -> dict[str, float]:
+    """Compute pct_light, pct_medium, pct_heavy from ground-truth labels."""
+    total = len(run_results)
+    if total == 0:
+        return {"pct_light": 0.0, "pct_medium": 0.0, "pct_heavy": 0.0}
+    counts: dict[str, int] = {"LIGHT": 0, "MEDIUM": 0, "HEAVY": 0}
+    for r in run_results:
+        truth = r["ground_truth_mode"]
+        counts[truth] = counts.get(truth, 0) + 1
+    return {
+        "pct_light": round(counts["LIGHT"] / total * 100, 1),
+        "pct_medium": round(counts["MEDIUM"] / total * 100, 1),
+        "pct_heavy": round(counts["HEAVY"] / total * 100, 1),
+    }
+
+
+def print_tripwire_report(
+    run_results: list[dict],
+    confusion_matrix: dict,
+    pcts: dict[str, float],
+) -> bool:
+    """
+    Print confusion matrix + tripwire report to stdout.
+    Returns True if any tripwire fired (exit code 1 signal).
+    """
+    tripwire_fired = False
+
+    print("\n=== Confusion Matrix (classified → ground truth) ===")
+    print(f"{'':10s} {'LIGHT':>8s} {'MEDIUM':>8s} {'HEAVY':>8s}")
+    for classified in ("LIGHT", "MEDIUM", "HEAVY"):
+        row = confusion_matrix[classified]
+        print(
+            f"  {classified:<8s} {row['LIGHT']:>8d} {row['MEDIUM']:>8d} {row['HEAVY']:>8d}"
+        )
+
+    total = len(run_results)
+    matches = sum(1 for r in run_results if r["match"])
+    pct_correct = round(matches / total * 100, 1) if total else 0.0
+
+    print(f"\nTotal runs evaluated: {total}")
+    print(f"Correct classifications: {matches}/{total} ({pct_correct}%)")
+    print(
+        f"Ground-truth distribution: "
+        f"LIGHT={pcts['pct_light']}% MEDIUM={pcts['pct_medium']}% HEAVY={pcts['pct_heavy']}%"
+    )
+
+    print("\n=== Tripwire Report ===")
+
+    # Tripwire 1: >= 70% MEDIUM (probe is under-discriminating)
+    if pcts["pct_medium"] >= 70:
+        print(
+            f"  [FIRE] Tripwire 1: pct_medium={pcts['pct_medium']}% >= 70% — "
+            "probe is collapsing too many runs to MEDIUM. "
+            "Review rubric thresholds or probe heuristics."
+        )
+        tripwire_fired = True
+    else:
+        print(f"  [ok]   Tripwire 1: pct_medium={pcts['pct_medium']}% (threshold: >= 70%)")
+
+    # Tripwire 2: < 20% HEAVY (not enough fanout signal detected)
+    if pcts["pct_heavy"] < 20:
+        print(
+            f"  [FIRE] Tripwire 2: pct_heavy={pcts['pct_heavy']}% < 20% — "
+            "probe is under-classifying HEAVY runs. "
+            "Review escalation event detection or tasks_total threshold."
+        )
+        tripwire_fired = True
+    else:
+        print(f"  [ok]   Tripwire 2: pct_heavy={pcts['pct_heavy']}% (threshold: < 20%)")
+
+    # Tripwire 3: synthesis quality (manual review — flagged for human follow-up)
+    print(
+        "  [manual] Tripwire 3 (synthesis quality): requires manual review of "
+        "per-chunk reconciler output. Flag for human follow-up."
+    )
+
+    # Tripwire 4: semantic axis correctness (manual review)
+    print(
+        "  [manual] Tripwire 4 (semantic axis correctness): requires manual review "
+        "of chosen axis vs expected axis per run. Flag for human follow-up."
+    )
+
+    return tripwire_fired
+
+
+# ---------------------------------------------------------------------------
+# Epoch JSON emission
+# ---------------------------------------------------------------------------
+
+def emit_epoch_json(
+    epoch: int,
+    n_runs: int,
+    samples_per_run: int,
+    run_results: list[dict],
+    confusion_matrix: dict,
+    pcts: dict[str, float],
+    scripts_dir: Path,
+) -> Path:
+    """Write scripts/calibration-epoch-<N>.json and return the path."""
+    payload = {
+        "epoch": epoch,
+        "rubric_version": 1,
+        "n_runs": n_runs,
+        "samples_per_run": samples_per_run,
+        "runs": [
+            {
+                "slug": r["slug"],
+                "run_id": r["run_id"],
+                "topic": r["topic"],
+                "classified_mode": r["classified_mode"],
+                "ground_truth_mode": r["ground_truth_mode"],
+                "match": r["match"],
+            }
+            for r in run_results
+        ],
+        "confusion_matrix": confusion_matrix,
+        "pct_heavy": pcts["pct_heavy"],
+        "pct_medium": pcts["pct_medium"],
+        "pct_light": pcts["pct_light"],
+    }
+
+    out_path = scripts_dir / f"calibration-epoch-{epoch}.json"
+    # Atomic write via temp file
+    tmp_path = out_path.with_suffix(".json.tmp")
+    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
+    tmp_path.replace(out_path)
+    return out_path
+
+
+# ---------------------------------------------------------------------------
+# CLI
+# ---------------------------------------------------------------------------
+
+def main() -> None:
+    parser = argparse.ArgumentParser(
+        description=(
+            "Calibration harness for scope-probe classifier. "
+            "Walks archive runs, classifies ground truth, dispatches probe, "
+            "emits calibration-epoch-<N>.json."
+        )
+    )
+    parser.add_argument(
+        "--archive-root",
+        required=True,
+        metavar="PATH",
+        help="Root directory to walk for slug archives (e.g. z-harness).",
+    )
+    parser.add_argument(
+        "--epoch",
+        type=int,
+        default=1,
+        metavar="N",
+        help="Calibration epoch number (default: 1). Appended to output filename.",
+    )
+    parser.add_argument(
+        "--n-runs",
+        type=int,
+        default=6,
+        metavar="N",
+        help="Maximum number of archive runs to evaluate (default: 6).",
+    )
+    parser.add_argument(
+        "--samples-per-run",
+        type=int,
+        default=3,
+        metavar="N",
+        help="Number of scope-probe dispatches per run for majority vote (default: 3).",
+    )
+    parser.add_argument(
+        "--fixture-mode",
+        metavar="FIXTURE_FILE",
+        default=None,
+        help=(
+            "Path to a JSON fixture file. When set, the scope-probe dispatch shim "
+            "reads probe results from the fixture instead of calling scope-probe. "
+            "For unit tests (T007)."
+        ),
+    )
+    args = parser.parse_args()
+
+    archive_root = Path(args.archive_root).expanduser().resolve()
+    if not archive_root.is_dir():
+        print(f"ERROR: --archive-root {archive_root} is not a directory.", file=sys.stderr)
+        sys.exit(1)
+
+    fixture_path: Optional[Path] = None
+    if args.fixture_mode is not None:
+        fixture_path = Path(args.fixture_mode).expanduser().resolve()
+        if not fixture_path.exists():
+            print(
+                f"ERROR: --fixture-mode file {fixture_path} not found.", file=sys.stderr
+            )
+            sys.exit(1)
+
+    # Resolve scripts/ directory relative to this script's location
+    scripts_dir = Path(__file__).parent.resolve()
+
+    print(f"Calibration harness — epoch {args.epoch}")
+    print(f"Archive root: {archive_root}")
+    print(f"n_runs={args.n_runs}, samples_per_run={args.samples_per_run}")
+    if fixture_path:
+        print(f"Fixture mode: {fixture_path}")
+    print()
+
+    # Discover runs
+    runs = discover_runs(archive_root, args.n_runs)
+    if not runs:
+        print("No runs with manifest.json found. Nothing to calibrate.", file=sys.stderr)
+        sys.exit(0)
+
+    print(f"Found {len(runs)} run(s) to evaluate:")
+    for r in runs:
+        print(f"  {r['run_id']} (slug={r['slug']})")
+    print()
+
+    # Classify each run
+    run_results: list[dict] = []
+    for run_info in runs:
+        # Ground truth
+        gt = classify_ground_truth(run_info["manifest"], run_info["events"])
+
+        # Majority-vote probe classification
+        votes: list[str] = []
+        for i in range(args.samples_per_run):
+            vote = dispatch_scope_probe(run_info, i, fixture_path)
+            votes.append(vote)
+        classified = majority_vote(votes)
+
+        run_results.append({
+            "slug": run_info["slug"],
+            "run_id": run_info["run_id"],
+            "topic": run_info["topic"],
+            "classified_mode": classified,
+            "ground_truth_mode": gt,
+            "match": classified == gt,
+            "votes": votes,
+        })
+        print(
+            f"  {run_info['run_id']}: ground_truth={gt}, classified={classified}, "
+            f"votes={votes}, match={classified == gt}"
+        )
+
+    print()
+
+    # Confusion matrix + percentages
+    confusion_matrix = build_confusion_matrix(run_results)
+    pcts = compute_percentages(run_results)
+
+    # Print tripwire report
+    tripwire_fired = print_tripwire_report(run_results, confusion_matrix, pcts)
+
+    # Emit epoch JSON
+    out_path = emit_epoch_json(
+        epoch=args.epoch,
+        n_runs=len(run_results),
+        samples_per_run=args.samples_per_run,
+        run_results=run_results,
+        confusion_matrix=confusion_matrix,
+        pcts=pcts,
+        scripts_dir=scripts_dir,
+    )
+    print(f"\nEmitted: {out_path}")
+
+    sys.exit(1 if tripwire_fired else 0)
+
+
+if __name__ == "__main__":
+    main()
```

Calibration rubric (scripts/CALIBRATION.md):
Rule (rubric_version 1):
  - HEAVY if events contains any escalation_* event OR manifest.tasks_total >= 16.
  - LIGHT if manifest.tasks_total <= 5 AND tasks_complexity.high == 0 AND no plan_route_decision event.
  - MEDIUM otherwise.

Scrutinize this code rigorously. Claude is prone to over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

**OUTPUT BUDGET — respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).
