# Calibration Epoch 1 Signoff — fanout-escalate-primitive v1a

**Date:** 2026-05-26
**Epoch:** 1
**Rubric version:** 1
**Evaluator:** T015 (automated + manual assessment)

---

## 1. Calibration Data Summary

Source: `scripts/calibration-epoch-1.json`

| Run slug | Run ID | Classified | Ground truth | Match |
|---|---|---|---|---|
| fanout-escalate-primitive | 20260527T175422Z | MEDIUM | MEDIUM | YES |
| z-harness-config-toml | 20260527T170933Z | MEDIUM | MEDIUM | YES |
| postmortem-memory-nudge | 20260527T045853Z | MEDIUM | LIGHT | NO |

**Confusion matrix (rows = ground truth, cols = classified):**

|  | LIGHT | MEDIUM | HEAVY |
|---|---|---|---|
| **LIGHT** | 0 | 1 | 0 |
| **MEDIUM** | 0 | 2 | 0 |
| **HEAVY** | 0 | 0 | 0 |

**Summary statistics:**
- n_runs: 3
- pct_heavy: 0.0%
- pct_medium: 66.7%
- pct_light: 33.3% (all ground-truth LIGHT; none classified correctly)

**Overall accuracy:** 2/3 = 66.7%

**Mis-classification analysis:** One sample (postmortem-memory-nudge) was ground-truth LIGHT but classified MEDIUM. The stub always emits MEDIUM, so this is expected. The mis-classification does not cluster on a threshold boundary — it is a structural artifact of the stub returning MEDIUM unconditionally in non-fixture mode.

---

## 2. Automated Tripwire Status

The calibration rubric defines four falsifiability tripwires. Status against epoch 1 data:

| Tripwire | Condition | Status | Interpretation |
|---|---|---|---|
| T1 — Accuracy floor | accuracy >= 0.60 on n >= 5 samples | **NOT EVALUABLE** — only 3 samples | Need >= 5 samples for meaningful accuracy claim |
| T2 — HEAVY classification rate | pct_heavy >= 20% on a known-HEAVY corpus | **FIRES** (pct_heavy = 0.0%) | Structural consequence of stub always returning MEDIUM; not a real failure of the scope-probe hypothesis |
| T3 — LIGHT over-classification | pct_light <= 50% | PASS (33.3%) | Vacuous pass — all LIGHT is mis-classified as MEDIUM, so pct_light from the classifier is 0% |
| T4 — Fixture parity | fixture-mode runs match expected outputs | PASS (fixtures pass by construction) | Fixture path is separate from live dispatch; fixture tests still valid |

**Honest interpretation of T2 firing:** The stub (`scripts/scope-probe-calibrate.py`) is an explicit v1a placeholder that returns MEDIUM in all non-fixture cases (per T006 design). Tripwire 2 firing is a direct structural consequence of this stub — it is NOT evidence that the scope-probe agent would fail to classify HEAVY topics. The stub does not invoke the scope-probe agent at all. T2 will only provide meaningful signal once the real Haiku-dispatched scope-probe agent is in the dispatcher loop.

---

## 3. Manual Gate A — Synthesis Quality on One HEAVY Run

**STATUS: cannot_conduct**

**Reason:** The stub dispatcher does not produce HEAVY classifications. No HEAVY runs were generated during epoch 1. Without a HEAVY classification, no fan-out sub-runs are dispatched, and no reconciler output exists to evaluate for synthesis quality.

**Unblocking condition:** Gate A can only be conducted once the real scope-probe agent (in non-stub mode) classifies at least one real invocation as HEAVY and a reconciler run completes. The most likely candidate is running `/z-audit` on a known-HEAVY target such as the qt-bot trader directory.

---

## 4. Manual Gate B — Semantic vs Structural Axis (REASON_CODES tally)

**STATUS: cannot_conduct**

**Reason:** The stub dispatcher does not emit `REASON_CODES` per the scope-probe output contract. REASON_CODES are populated by the real scope-probe agent's seam-counting logic (Steps 3–5 of the agent procedure in SPEC.md). With the stub in place, REASON_CODES fields are absent from all epoch 1 samples.

**What would be tallied:** Once real runs are available, the axis would be: structural codes (e.g. `many_subdirs`, `named_cluster_match`, `distinct_entry_points`) vs semantic/confidence codes (e.g. `low_confidence`, `no_evidence`, `topic_ambiguous`). A healthy calibration would show structural codes dominating HEAVY classifications and low-confidence codes dominating LIGHT or MEDIUM edge cases.

**Unblocking condition:** Same as Gate A — first real HEAVY dispatch providing REASON_CODES data.

---

## 5. Threshold Tuning

**Status: not applicable**

The scope-probe agent uses seam-count thresholds to decide LIGHT / MEDIUM / HEAVY. These thresholds cannot be meaningfully tuned against stub data because:

1. The stub does not exercise the seam-counting logic.
2. All epoch 1 outputs are MEDIUM regardless of input characteristics.
3. There is no distribution of threshold-boundary cases to analyze.

Threshold tuning is deferred to epoch 2, which requires real Haiku-dispatched scope-probe data.

---

## 6. Verdict

```
v1a SHIPPED, v1b GATED on first real-world HEAVY run providing calibration signal
```

**Rationale:**

v1a infrastructure is fully shipped:

- `agents/scope-probe.md` — Haiku subagent with hybrid output contract, seam-counting procedure, and SCOPE.json schema
- `agents/scope-reconciler-audit.md` and `agents/scope-reconciler-brainstorm.md` — Sonnet reconciler agents for HEAVY fan-out synthesis
- `commands/z-audit.md` and `commands/z-brainstorm.md` — Phase 0 integrations calling scope-probe
- `scripts/scope-probe-calibrate.py` — calibration harness with versioned rubric (`scripts/CALIBRATION.md`)
- `scripts/calibration-epoch-1.json` — baseline epoch with fixture-mode validation
- Host integrations, docs, and schema definitions are all in place

v1b (deletions of existing escalation chains) remains explicitly gated because the falsifiability tripwires — which exist precisely to protect against premature deletion — cannot fire meaningfully until real HEAVY data exists. Deleting existing fallback chains before the replacement mechanism is validated against real-world HEAVY workloads would be unsafe.

---

## 7. Recommended Next Steps

1. **Trigger a real HEAVY run:** Run `/z-audit` on a known-HEAVY target — the qt-bot trader directory is the recommended candidate given its size and known structural complexity. This will produce the first non-stub calibration sample with real REASON_CODES and a real HEAVY/MEDIUM/LIGHT classification.

2. **Run epoch 2:** After at least one real HEAVY run, re-run `scripts/scope-probe-calibrate.py` with the new archive entry included. Epoch 2 should have n >= 5 samples (mix of prior archive slugs + new real run) to make T1 evaluable.

3. **Conduct Gate A and Gate B:** Once epoch 2 has a HEAVY sample, conduct Gate A (review reconciler synthesis quality) and Gate B (tally REASON_CODES structural vs semantic split).

4. **Tune thresholds if needed:** If epoch 2 shows boundary misclassifications (HEAVY mis-classified as MEDIUM or vice versa), adjust seam-count thresholds in `agents/scope-probe.md` and re-run.

5. **Greenlight v1b:** If Gates A and B pass and tripwires T1 and T2 both pass in epoch 2, proceed to v1b (deletion of existing escalation chains per SPEC.md Non-goals section).
