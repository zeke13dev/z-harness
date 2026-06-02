#!/usr/bin/env python3
"""persona-stats.py — Stratified read-only analysis of persona-rotation telemetry.

Usage:
    python3 scripts/persona-stats.py [--metrics PATH] [--json] [--min-diff-size N]

Reads the repo-wide aggregate event log (z-harness/metrics.jsonl by default),
joins persona draw events (``persona_random_selected``, including the
``forced_control`` arm) to per-attempt terminal-outcome events
(``persona_attempt_outcome``) by ``attempt_id`` (with ``draw_id`` as a secondary
join key), and reports outcome metrics grouped by
``persona_id × role × complexity_tier``.

For each group it also reports the delta of each metric versus the PRIMARY
baseline WITHIN THE SAME stratum (same ``role`` × ``complexity_tier``). The
baseline resolution order is:

  1. ``no-persona`` (primary null baseline, true null) within the stratum.
  2. ``boring-anchor`` (secondary bland control) within the stratum, if no
     ``no-persona`` samples exist.
  3. ``None`` — raw metrics reported without a delta if neither exists.

Both ``no-persona`` and ``boring-anchor`` appear as their own tracked arms in
every section; neither is quarantined. Every section is segmented by
``selection_source``.

``fallback_empty_pool`` draws are QUARANTINED: they are reported in a separate
section and are never folded into any persona's stats or into either baseline.
Draws with no matching ``persona_attempt_outcome`` (incomplete attempts) are
excluded entirely.

Reviewer rows are derived from ``persona_bound`` events and segmented by
``reviewer_participant`` (base_codex vs random_arm).

This tool is strictly READ-ONLY — it never writes any file.

Flags:
    --metrics PATH      Path to the metrics.jsonl aggregate (default: the
                        repo-wide z-harness/metrics.jsonl).
    --json              Emit machine-readable JSON instead of a table.
    --min-diff-size N   Drop attempts whose diff_size is below N lines (treats
                        trivial diffs as noise). Default 0 (keep everything).
"""

import argparse
import json
import os
import sys

NO_PERSONA = "no-persona"       # primary null baseline (true null, empty prefix)
CONTROL_PERSONA = "boring-anchor"  # secondary bland control
FALLBACK_SOURCE = "fallback_empty_pool"

# Numeric outcome metrics carried by persona_attempt_outcome that we aggregate
# (mean) per group and delta against the control within the stratum.
NUMERIC_METRICS = ("review_cycles", "retries", "blocker_count", "wall_ms", "diff_size")

DRAW_KIND = "persona_random_selected"
OUTCOME_KIND = "persona_attempt_outcome"
BOUND_KIND = "persona_bound"


def _repo_root():
    """Return the repository root (directory containing scripts/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_metrics_path():
    """Resolve the repo-wide aggregate metrics.jsonl path.

    Honors Z_HARNESS_BASE_DIR (where log-event.sh writes the aggregate) when
    set; otherwise falls back to <repo>/z-harness/metrics.jsonl.
    """
    base = os.environ.get("Z_HARNESS_BASE_DIR")
    if base:
        return os.path.join(base, "metrics.jsonl")
    return os.path.join(_repo_root(), "z-harness", "metrics.jsonl")


def load_events(path):
    """Read a JSONL file into a list of dicts.

    Lines that are blank or not valid JSON objects are skipped (the aggregate
    log is append-only and may contain partial trailing writes).
    """
    events = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                events.append(obj)
    return events


def _join_key(event):
    """Return (attempt_id, draw_id) join keys for an event, or None if absent.

    attempt_id is the primary join key; draw_id is the secondary key. An empty
    string is treated as missing (the orchestrator exports "" when a key is
    unavailable).
    """
    attempt = event.get("attempt_id") or None
    draw = event.get("draw_id") or None
    return attempt, draw


def join_attempts(events):
    """Join draw events to outcome events.

    Returns a list of joined attempt records, each a dict with the draw's
    selection_source/persona_id/role plus the outcome's metrics. An attempt is
    included only if BOTH a draw event and a matching outcome event exist
    (incomplete attempts — draw with no outcome — are dropped).

    Primary join is by attempt_id; draw_id is used as a secondary fallback when
    attempt_id is missing on one side.
    """
    draws_by_attempt = {}
    draws_by_drawid = {}
    for ev in events:
        if ev.get("kind") != DRAW_KIND:
            continue
        attempt, draw = _join_key(ev)
        if attempt is not None:
            draws_by_attempt[attempt] = ev
        if draw is not None:
            draws_by_drawid.setdefault(draw, ev)

    joined = []
    for ev in events:
        if ev.get("kind") != OUTCOME_KIND:
            continue
        attempt, draw = _join_key(ev)
        draw_ev = None
        if attempt is not None and attempt in draws_by_attempt:
            draw_ev = draws_by_attempt[attempt]
        elif draw is not None and draw in draws_by_drawid:
            draw_ev = draws_by_drawid[draw]
        if draw_ev is None:
            # Outcome with no matching draw — cannot attribute a selection
            # source; skip (defensive; the orchestrator always logs the draw
            # first).
            continue

        record = {
            "attempt_id": attempt,
            "draw_id": draw if draw is not None else draw_ev.get("draw_id"),
            # selection_source and the persona/role come from the DRAW so the
            # quarantine + control attribution match how the draw was made.
            "selection_source": draw_ev.get("selection_source"),
            "persona_id": draw_ev.get("persona_id") or draw_ev.get("selected"),
            "role": ev.get("role") or draw_ev.get("role"),
            "complexity_tier": ev.get("complexity_tier", ""),
            "status": ev.get("status"),
        }
        for metric in NUMERIC_METRICS:
            val = ev.get(metric)
            record[metric] = val if isinstance(val, (int, float)) else None
        joined.append(record)
    return joined


def _stratum_key(record):
    """(role, complexity_tier) — the stratum within which deltas are computed."""
    return (record.get("role") or "", record.get("complexity_tier") or "")


def _group_key(record):
    """(persona_id, role, complexity_tier) — the reporting group."""
    return (
        record.get("persona_id") or "",
        record.get("role") or "",
        record.get("complexity_tier") or "",
    )


def _aggregate(records):
    """Aggregate a list of joined attempt records into a metrics summary."""
    n = len(records)
    summary = {"n_attempts": n, "status_counts": {}, "metrics": {}}
    for r in records:
        st = r.get("status") or "unknown"
        summary["status_counts"][st] = summary["status_counts"].get(st, 0) + 1
    # completion rate = fraction of attempts whose terminal status is "done".
    done = summary["status_counts"].get("done", 0)
    summary["completion_rate"] = (done / n) if n else 0.0
    for metric in NUMERIC_METRICS:
        vals = [r[metric] for r in records if r.get(metric) is not None]
        summary["metrics"][metric] = (sum(vals) / len(vals)) if vals else None
    return summary


def build_report(joined, min_diff_size=0):
    """Build the full stratified report from joined attempt records.

    Returns a dict with three top-level keys:
      - "segments": per selection_source (excluding fallback) → list of groups,
        each carrying its own aggregate metrics AND a delta-vs-baseline computed
        within the group's stratum. ``baseline_source`` indicates which arm was
        used (``"no-persona"``, ``"boring-anchor"``, or ``None``).
      - "quarantine": fallback_empty_pool aggregate (never folded elsewhere).
      - "reviewer": reviewer attempts segmented by reviewer_participant.

    Baseline resolution order per stratum:
      1. no-persona (primary null baseline).
      2. boring-anchor (secondary bland control), if no no-persona samples exist.
      3. None — raw metrics reported without a delta if neither exists.

    Both no-persona and boring-anchor are tracked as normal arms and appear in
    their own segment groups. fallback_empty_pool rows never enter any baseline.
    """
    # --min-diff-size noise filter: drop attempts below the threshold. A None
    # diff_size is treated as 0 (no diff recorded → trivial).
    filtered = [
        r for r in joined
        if (r.get("diff_size") or 0) >= min_diff_size
    ]

    # Partition fallback (quarantine) from the analyzable population.
    fallback = [r for r in filtered if r.get("selection_source") == FALLBACK_SOURCE]
    analyzable = [r for r in filtered if r.get("selection_source") != FALLBACK_SOURCE]

    # Primary baseline: no-persona rows per stratum, from analyzable population only.
    no_persona_by_stratum = {}
    no_persona_strata = {}
    for r in analyzable:
        if r.get("persona_id") == NO_PERSONA:
            no_persona_strata.setdefault(_stratum_key(r), []).append(r)
    for stratum, recs in no_persona_strata.items():
        no_persona_by_stratum[stratum] = _aggregate(recs)

    # Secondary baseline: boring-anchor rows per stratum, from analyzable population only.
    # A fallback row that resolves to boring-anchor must NOT contaminate the baseline.
    boring_anchor_by_stratum = {}
    boring_anchor_strata = {}
    for r in analyzable:
        if r.get("persona_id") == CONTROL_PERSONA:
            boring_anchor_strata.setdefault(_stratum_key(r), []).append(r)
    for stratum, recs in boring_anchor_strata.items():
        boring_anchor_by_stratum[stratum] = _aggregate(recs)

    # Group every analyzable record by selection_source → group key.
    segments = {}
    for r in analyzable:
        src = r.get("selection_source") or "unknown"
        segments.setdefault(src, {}).setdefault(_group_key(r), []).append(r)

    out_segments = {}
    for src, groups in segments.items():
        out_groups = []
        for gkey, recs in sorted(groups.items()):
            persona_id, role, tier = gkey
            agg = _aggregate(recs)
            stratum = (role, tier)
            # Resolve baseline: no-persona first, boring-anchor second, none last.
            if no_persona_by_stratum.get(stratum) is not None:
                baseline = no_persona_by_stratum[stratum]
                baseline_source = NO_PERSONA
            elif boring_anchor_by_stratum.get(stratum) is not None:
                baseline = boring_anchor_by_stratum[stratum]
                baseline_source = CONTROL_PERSONA
            else:
                baseline = None
                baseline_source = None
            delta = _compute_delta(agg, baseline, persona_id, baseline_source)
            out_groups.append({
                "persona_id": persona_id,
                "role": role,
                "complexity_tier": tier,
                "n_attempts": agg["n_attempts"],
                "completion_rate": agg["completion_rate"],
                "status_counts": agg["status_counts"],
                "metrics": agg["metrics"],
                "baseline_source": baseline_source,
                "delta_vs_baseline": delta,
            })
        out_segments[src] = out_groups

    quarantine_agg = _aggregate(fallback) if fallback else {
        "n_attempts": 0, "status_counts": {}, "completion_rate": 0.0,
        "metrics": {m: None for m in NUMERIC_METRICS},
    }

    return {
        "segments": out_segments,
        "quarantine_fallback_empty_pool": quarantine_agg,
        "reviewer": None,  # populated by build_reviewer_report
    }


def _compute_delta(agg, baseline, persona_id, baseline_source):
    """Per-metric delta (group mean − baseline mean) within the stratum.

    Returns None when this group IS the baseline arm, when there is no baseline
    in the stratum, or for metrics the baseline lacks. completion_rate delta is
    also included.

    ``baseline_source`` is the persona_id of the arm used as baseline
    (``"no-persona"`` or ``"boring-anchor"``), used to suppress delta for the
    arm that is its own baseline.
    """
    if baseline is None:
        return None
    # The baseline arm reports delta=None (it IS the baseline).
    if persona_id == baseline_source:
        return None
    delta = {}
    for metric in NUMERIC_METRICS:
        g = agg["metrics"].get(metric)
        b = baseline["metrics"].get(metric)
        delta[metric] = (g - b) if (g is not None and b is not None) else None
    delta["completion_rate"] = agg["completion_rate"] - baseline["completion_rate"]
    return delta


def build_reviewer_report(events, joined, min_diff_size=0):
    """Segment reviewer attempts by reviewer_participant (base_codex/random_arm).

    Reviewer attribution lives on persona_bound events (which carry
    reviewer_participant + attempt_id), while the outcome metrics live on the
    attempt's single persona_attempt_outcome. We map each reviewer
    persona_bound to its attempt's joined outcome record by attempt_id (draw_id
    secondary), then aggregate per participant. fallback_empty_pool attempts are
    quarantined out here too.
    """
    # Index joined outcome records by attempt_id and draw_id for lookup.
    by_attempt = {}
    by_draw = {}
    for r in joined:
        if r.get("attempt_id"):
            by_attempt[r["attempt_id"]] = r
        if r.get("draw_id"):
            by_draw.setdefault(r["draw_id"], r)

    # Collect reviewer bindings (one per (attempt_id, participant)). Dedup so a
    # re-emitted persona_bound for the same attempt+participant counts once.
    seen = set()
    by_participant = {}
    for ev in events:
        if ev.get("kind") != BOUND_KIND:
            continue
        participant = ev.get("reviewer_participant")
        if participant is None:
            continue  # not a reviewer binding
        attempt = ev.get("attempt_id") or None
        draw = ev.get("draw_id") or None
        outcome = None
        if attempt is not None and attempt in by_attempt:
            outcome = by_attempt[attempt]
        elif draw is not None and draw in by_draw:
            outcome = by_draw[draw]
        if outcome is None:
            continue  # reviewer arm with no completed attempt → incomplete
        if outcome.get("selection_source") == FALLBACK_SOURCE:
            continue  # quarantined attempt — never folded into reviewer stats
        if (outcome.get("diff_size") or 0) < min_diff_size:
            continue  # noise filter consistent with the main report
        dedup = (attempt or draw, participant)
        if dedup in seen:
            continue
        seen.add(dedup)
        by_participant.setdefault(participant, []).append(outcome)

    report = {}
    for participant, recs in sorted(by_participant.items()):
        report[participant] = _aggregate(recs)
    return report


def _fmt_metric(val):
    if val is None:
        return "-"
    if isinstance(val, float):
        return f"{val:.2f}"
    return str(val)


def _fmt_delta(val):
    if val is None:
        return "-"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}"


def render_table(report):
    """Render the report as a human-readable text table."""
    lines = []
    lines.append("PERSONA-STATS — stratified outcome analysis")
    lines.append("=" * 60)

    segments = report["segments"]
    if not segments:
        lines.append("(no completed attempts to report)")
    for src in sorted(segments):
        lines.append("")
        lines.append(f"## selection_source = {src}")
        groups = segments[src]
        if not groups:
            lines.append("  (none)")
            continue
        header = (
            f"  {'persona_id':<20} {'role':<12} {'tier':<8} "
            f"{'n':>3} {'compl':>6} "
            + " ".join(f"{m:>11}" for m in NUMERIC_METRICS)
        )
        lines.append(header)
        for g in groups:
            row = (
                f"  {g['persona_id']:<20} {g['role']:<12} "
                f"{(g['complexity_tier'] or '-'):<8} "
                f"{g['n_attempts']:>3} {g['completion_rate']:>6.2f} "
                + " ".join(f"{_fmt_metric(g['metrics'].get(m)):>11}" for m in NUMERIC_METRICS)
            )
            lines.append(row)
            delta = g.get("delta_vs_baseline")
            if delta is not None:
                bsrc = g.get("baseline_source") or "baseline"
                drow = (
                    f"  {'  Δ vs ' + bsrc:<20} {'':<12} {'':<8} "
                    f"{'':>3} {_fmt_delta(delta.get('completion_rate')):>6} "
                    + " ".join(f"{_fmt_delta(delta.get(m)):>11}" for m in NUMERIC_METRICS)
                )
                lines.append(drow)

    # Reviewer section.
    lines.append("")
    lines.append("## reviewer (segmented by reviewer_participant)")
    reviewer = report.get("reviewer") or {}
    if not reviewer:
        lines.append("  (no reviewer attempts)")
    else:
        for participant in sorted(reviewer):
            agg = reviewer[participant]
            lines.append(
                f"  {participant:<14} n={agg['n_attempts']:<3} "
                f"compl={agg['completion_rate']:.2f} "
                + " ".join(f"{m}={_fmt_metric(agg['metrics'].get(m))}" for m in NUMERIC_METRICS)
            )

    # Quarantine section — always separate, never folded above.
    lines.append("")
    lines.append("## QUARANTINE — fallback_empty_pool (excluded from all stats above)")
    q = report["quarantine_fallback_empty_pool"]
    lines.append(
        f"  n={q['n_attempts']} compl={q['completion_rate']:.2f} "
        + " ".join(f"{m}={_fmt_metric(q['metrics'].get(m))}" for m in NUMERIC_METRICS)
    )

    return "\n".join(lines)


def analyze(metrics_path, min_diff_size=0):
    """Top-level: load, join, and build the full report dict."""
    events = load_events(metrics_path)
    joined = join_attempts(events)
    report = build_report(joined, min_diff_size=min_diff_size)
    report["reviewer"] = build_reviewer_report(events, joined, min_diff_size=min_diff_size)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Stratified read-only analysis of persona-rotation telemetry."
    )
    parser.add_argument(
        "--metrics",
        default=None,
        help="Path to metrics.jsonl (default: repo-wide z-harness/metrics.jsonl).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a table.",
    )
    parser.add_argument(
        "--min-diff-size",
        type=int,
        default=0,
        metavar="N",
        help="Drop attempts whose diff_size is below N lines (noise filter).",
    )
    args = parser.parse_args(argv)

    metrics_path = args.metrics or _default_metrics_path()
    if not os.path.exists(metrics_path):
        print(f"persona-stats: metrics file not found: {metrics_path}", file=sys.stderr)
        return 1

    report = analyze(metrics_path, min_diff_size=args.min_diff_size)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_table(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
