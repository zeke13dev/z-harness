#!/usr/bin/env python3
"""
scripts/hang-threshold.py — per-class hang thresholds from metrics.jsonl.

Deterministic (no LLM, no network). Computes, per work class, a hang threshold =
p90 (or p95) of historical `wall_ms` x a safety margin. The scheduled hang-check
(T007) schedules its one-shot at this horizon — past it, work is "probably hung".

Why p90, not the median: classes differ ~20x and within a class p90 is 2-3x the
median, so the median would false-alarm on half of healthy runs (plan F-finding).

Class key is built from fields that ACTUALLY exist per event source (audit F4,
corrected against real data):
  - <kind> with subagent_model -> <kind>:<subagent_model>       (e.g. implement_end:opus)
  - other *_end -> <kind>
Test-noise classes (longrun_end, mytest_end, test-/smoke- runs) are excluded.

Usage:
  hang-threshold.py dump [--metrics FILE]
  hang-threshold.py for --kind implement_end [--model opus] [--metrics FILE]
     -> prints the threshold in whole seconds (global fallback when the class is sparse)

Tuning (env): HANG_PCTILE (default 90), HANG_MARGIN (default 1.5),
              HANG_MIN_SAMPLE (default 5). Global fallback seconds come from
              `config.py get watchdog.stale_secs` (default 300).
"""
import argparse
import json
import math
import os
import subprocess
import sys

NOISE_KINDS = {"longrun_end", "mytest_end"}
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _is_noise(ev):
    if ev.get("kind") in NOISE_KINDS:
        return True
    run = ev.get("run") or ev.get("run_id") or ""
    return run.startswith("test") or run.startswith("smoke")


def class_key(kind, model=None):
    if model:
        return f"{kind}:{model}"
    return kind


def _event_key(ev):
    return class_key(
        ev.get("kind", ""),
        model=ev.get("subagent_model"),
    )


def _resolve_metrics():
    base = os.environ.get("Z_HARNESS_BASE_DIR")
    if not base:
        try:
            base = subprocess.run(
                ["bash", os.path.join(_SCRIPT_DIR, "plan-path.sh"), "base_dir"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except Exception:
            base = ""
    return os.path.join(base, "metrics.jsonl") if base else ""


def _collect(metrics_path):
    buckets = {}
    if not metrics_path or not os.path.exists(metrics_path):
        return buckets
    with open(metrics_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            w = ev.get("wall_ms")
            if not isinstance(w, (int, float)) or w <= 0:
                continue
            if _is_noise(ev):
                continue
            buckets.setdefault(_event_key(ev), []).append(float(w))
    return buckets


def _pctl(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    idx = int(math.ceil(p / 100.0 * len(vals))) - 1
    return vals[max(0, min(len(vals) - 1, idx))]


def _global_fallback_secs():
    try:
        out = subprocess.run(
            ["python3", os.path.join(_SCRIPT_DIR, "config.py"), "get",
             "watchdog.stale_secs"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()
        for line in reversed(out):
            if line.strip().isdigit():
                return int(line.strip())
    except Exception:
        pass
    return 300


def compute(metrics_path, pctile, margin, min_sample):
    buckets = _collect(metrics_path)
    table = {}
    for key, vals in buckets.items():
        if len(vals) < min_sample:
            continue
        p = _pctl(vals, pctile)
        table[key] = {
            "n": len(vals),
            "p_ms": int(p),
            "threshold_secs": int(round(p * margin / 1000.0)),
        }
    return table


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--metrics")
    f = sub.add_parser("for")
    f.add_argument("--kind", required=True)
    f.add_argument("--model")
    f.add_argument("--metrics")
    args = ap.parse_args()

    pctile = int(os.environ.get("HANG_PCTILE", "90"))
    margin = float(os.environ.get("HANG_MARGIN", "1.5"))
    min_sample = int(os.environ.get("HANG_MIN_SAMPLE", "5"))
    metrics_path = args.metrics or _resolve_metrics()
    table = compute(metrics_path, pctile, margin, min_sample)

    if args.cmd == "dump":
        print(json.dumps(table, indent=2, sort_keys=True))
        return 0

    key = class_key(args.kind, model=args.model)
    entry = table.get(key)
    if entry:
        print(entry["threshold_secs"])
    else:
        # Sparse / unknown class -> global fallback (audit F4 min-sample fallback).
        print(_global_fallback_secs())
    return 0


if __name__ == "__main__":
    sys.exit(main())
