---
rubric_version: 1
applies_to: scope-probe-calibrate.py
---

# Calibration Rubric — scope-probe-calibrate.py

This file is the **human-readable canonical reference** for the ground-truth classification rubric used by `scripts/scope-probe-calibrate.py`. The actual Python implementation lives in that script; this document defines the contract the implementation must satisfy. Whenever the implementation and this document conflict, this document wins — update the implementation.

## Function Spec

```python
def classify_ground_truth(manifest: dict, events: list[dict]) -> str:
    """Returns 'LIGHT' | 'MEDIUM' | 'HEAVY' from a historical run's artifacts.

    Rule (rubric_version 1):
      - HEAVY if events contains any escalation_* event OR manifest.tasks_total >= 16.
      - LIGHT if manifest.tasks_total <= 5 AND tasks_complexity.high == 0
              AND no plan_route_decision event.
      - MEDIUM otherwise.
    Tie-break: if signals disagree, prefer escalation event > tasks_complexity > tasks_total.
    """
```

## Rule Detail

### HEAVY

A run is classified **HEAVY** if either of the following is true:

1. `events` contains at least one event whose `type` field starts with `escalation_` (e.g. `escalation_mid_flight`, `escalation_architect_bail`).
2. `manifest.tasks_total >= 16` — the plan contained 16 or more tasks, indicating broad scope that typically warrants fanout.

Either condition alone is sufficient to classify HEAVY.

### LIGHT

A run is classified **LIGHT** only when **all three** of the following hold:

1. `manifest.tasks_total <= 5` — a small, narrowly scoped plan.
2. `manifest.tasks_complexity.high == 0` — no high-complexity tasks present.
3. `events` contains no `plan_route_decision` event — the planning router did not invoke a scope-widening path.

All three must be satisfied simultaneously. A run satisfying the HEAVY rule is never classified LIGHT regardless of the LIGHT conditions.

### MEDIUM

Everything that is neither HEAVY nor LIGHT.

## Tie-break: Signal Priority

When signals point in different directions (e.g. a run has `tasks_total >= 16` but also `tasks_complexity.high == 0` and no escalation events), use this priority order:

1. **Escalation event** — highest priority. Any `escalation_*` event → HEAVY, overrides all other signals.
2. **tasks_complexity** — `tasks_complexity.high > 0` prevents LIGHT classification even when `tasks_total <= 5`.
3. **tasks_total** — lowest priority among the three signals. Satisfying only `tasks_total <= 5` alone is not sufficient for LIGHT.

## Calibration Epoch Versioning

- Each calibration run emits a `scripts/calibration-epoch-<N>.json` artifact.
- Epoch files are **append-only**; they are never modified after creation.
- **A `rubric_version` bump invalidates all prior calibration epoch trend comparisons.** After a bump, the new epoch series begins fresh. Do not draw trend lines across epochs with different `rubric_version` values.
- When incrementing `rubric_version`, update this document's frontmatter, add a bump log entry in the section below, and re-run the calibration harness from epoch 1 under the new version.

## Rubric Version Bump Log

| rubric_version | Date       | Summary of change |
|---------------|------------|-------------------|
| 1             | 2026-05-26 | Initial rubric. HEAVY on escalation_* or tasks_total >= 16; LIGHT on tasks_total <= 5 AND complexity.high == 0 AND no plan_route_decision. |

## Manifest Shape Reference

The `manifest` argument is the parsed content of a run's `manifest.json`. Relevant fields for rubric_version 1:

```json
{
  "tasks_total": 12,
  "tasks_complexity": {
    "low": 4,
    "medium": 6,
    "high": 2
  }
}
```

## Events Shape Reference

The `events` argument is the parsed list of JSON objects from a run's `events.jsonl`. Each object has at minimum a `type` field. Example escalation event:

```json
{"type": "escalation_mid_flight", "ts": "2026-05-27T18:00:00Z", "payload": {}}
```

The rubric checks the `type` field via prefix match (`startswith("escalation_")`); the specific escalation subtype is not significant for classification purposes.
