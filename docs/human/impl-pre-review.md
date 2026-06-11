# impl-pre-review

> Last updated: 2026-06-10
> Covers source: commands/z-implement-all.md, scripts/audit-preview-misses.sh, agents/pre-reviewer.md, agents/complexity-classifier.md

## Overview

`impl-pre-review` is the opt-in pre-review gate-down introduced in the `reviewer-cost-telemetry` plan (Change 3). It adds a cheap DeepSeek Flash pre-reviewer tier at the per-task implement gate in `/z-implement-all`, intended to skip the full codex reviewer on clean low-tier tasks.

**This feature ships inert.** The knob `Z_HARNESS_IMPL_PRE_REVIEW` defaults to `0`, and when unset or `0`, execution is byte-identical to today — the entire block is a no-op and falls through directly to the existing codex review. The knob is **undocumented-as-recommended** until `scripts/audit-preview-misses.sh` demonstrates an acceptable Flash false-negative rate on low-tier tasks.

## Cost-inversion caveat

> **Running Flash on every task plus codex on a subset can invert total cost relative to running codex on every task.** Enable only after reviewing `scripts/audit-preview-misses.sh` results. See the evidence gate section below.

Flash has a non-trivial per-call cost. On a plan where most tasks are medium or high tier (not eligible for gate-down), Flash runs on all of them with no savings, while codex runs on the same medium/high tasks as before plus any flagged low-tier tasks. The net effect can be higher total spend than baseline. The Change-1 bloat fix (file-based capture) and the Change-2 cost attribution (subagent telemetry) are the primary cost wins in this plan; Change 3 is a **modest incremental save** that only matters at scale on clean low-tier task sets.

## Key entry points

<!-- AUTO-START: entry-points -->
- `commands/z-implement-all.md:1280` — `Z_HARNESS_IMPL_PRE_REVIEW` block header — knob description, cost-inversion caveat, NO-OP fallthrough guarantee
- `commands/z-implement-all.md:1298` — `if [ "${Z_HARNESS_IMPL_PRE_REVIEW:-0}" = "1" ]` — knob gate; only activates on cycle 1
- `commands/z-implement-all.md:1303` — `Step 6.P1 — Tier-drift re-check` — strips cached `**Complexity:**` stamp; dispatches `complexity-classifier` to derive `LIVE_TIER` from scratch
- `commands/z-implement-all.md:1348` — `Step 6.P2 — Gate-down (low-tier only)` — probes Flash provider availability; dispatches `pre-reviewer`; branches on `FLASH_VERDICT`
- `scripts/audit-preview-misses.sh` — evidence gate — samples low-tier tasks where Flash gated codex out; runs codex anyway; records Flash false-negative rate
- `agents/pre-reviewer.md` — Flash pre-reviewer agent — focused, fast first-pass; emits `**VERDICT:**` line (`CLEAN`, `MAJORS_FOUND`, or `BLOCKERS_FOUND`)
- `agents/complexity-classifier.md` — reused for tier-drift re-check (Step 6.P1)
<!-- AUTO-END: entry-points -->

## Knob: Z_HARNESS_IMPL_PRE_REVIEW

| Property | Value |
|----------|-------|
| Default | `0` (off) |
| Activation | `Z_HARNESS_IMPL_PRE_REVIEW=1` |
| Scope | env-only (not a TOML key) |
| Ships | inert — byte-identical to today when unset or `0` |

When `0` or unset, the two downstream variables are initialized unconditionally before the knob block to ensure the skip-guard and reviewer prompts always read a defined value:

```bash
PRE_REVIEW_GATED_DOWN=0
FLASH_PREPEND=""
```

These initializations are outside the knob block and must not change knob-off behavior.

## Behavior when knob = 1

The gate-down block runs only on cycle 1 (`$CYCLE -eq 1`). On retry cycles (cycle > 1), the full codex reviewer runs unconditionally.

### Step 6.P1 — Tier-drift re-check

Before dispatching the pre-reviewer, re-run `complexity-classifier` on the current task block to detect post-plan-time complexity changes. The cached `**Complexity:**` line is stripped before dispatch so the classifier re-derives the tier from scratch:

```bash
TASK_BLOCK_FOR_DRIFT="$(printf '%s' "$TASK_BLOCK" | grep -v '^\*\*Complexity:\*\*')"
```

If the live tier is higher than the plan-time cached tier (drift-up), emit `tier_drift_detected` and force the full codex review (skip the gate-down shortcut). If no drift-up, proceed to Step 6.P2.

### Step 6.P2 — Gate-down (low-tier only)

Gate-down only applies when `EFFECTIVE_TIER == "low"`. Medium and high tier tasks always go to codex unchanged (Flash may optionally be used to prepend findings, but is not authoritative on these tiers).

**When Flash provider is unavailable** (`resolve-provider.py pre-reviewer` returns empty or `none`): emit `pre_review_skipped {id, reason:"provider_unavailable", tier}` and fall through to codex — fail-safe toward the **more thorough review**.

**When Flash is available**: dispatch `agents/pre-reviewer.md` on the task diff. Parse the `**VERDICT:**` line:

| Verdict | Action |
|---------|--------|
| `CLEAN` | Skip codex. Emit `review_gated_down {id, tier, provider:"flash", cycle}`. Set `BLOCKER_COUNT=0`, `MAJORS_COUNT=0`, `PRE_REVIEW_GATED_DOWN=1`. |
| `MAJORS_FOUND` or `BLOCKERS_FOUND` | Escalate to codex. Set `FLASH_PREPEND` to the Flash findings (prepended to the codex prompt). `PRE_REVIEW_GATED_DOWN=0`. |

### Telemetry events

| Event | When |
|-------|------|
| `tier_drift_detected` | Drift-up detected in Step 6.P1; `cached_tier`, `live_tier`, `action:"force_codex"` |
| `pre_review_skipped` | Flash provider unavailable; `reason:"provider_unavailable"`, `tier` |
| `review_gated_down` | Flash returned CLEAN; codex skipped; `id`, `tier`, `provider:"flash"`, `cycle` |

## Evidence gate

`scripts/audit-preview-misses.sh` is the evidence gate for this feature. It samples low-tier tasks from historical runs where Flash gated codex out, then runs codex retroactively on the same diffs and records disagreements (cases where codex would have returned FAIL but Flash returned CLEAN). The resulting false-negative rate determines whether the knob is safe to recommend.

The knob is **undocumented-as-recommended** and should not be enabled in production until this audit shows an acceptable miss rate. SPEC.md explicitly states that Change 3 is a **modest incremental save** — the medium/high spend reduction and the Change-1 bloat fix dominate the cost story.

## Invariants

- `Z_HARNESS_IMPL_PRE_REVIEW=0` (default): entire block is a NO-OP; byte-identical to today.
- Gate-down only runs on cycle 1; retry cycles always use the full codex reviewer.
- Flash provider unavailable → fail-safe toward the more thorough review (codex runs); never silently skip.
- Tier-drift re-check strips the cached `**Complexity:**` stamp before dispatching the classifier (prevents heuristic #1 from returning the cached tier unchanged).
- Medium/high tier tasks are never gated down by Flash; Flash may prepend findings but is not authoritative.
- `PRE_REVIEW_GATED_DOWN` and `FLASH_PREPEND` are always initialized before the knob block; downstream code never reads undefined variables on the knob-off path.

## Two-variable gate-down design: GATE_DOWN vs GATED_DOWN

The gate-down logic uses **two distinct shell variables** whose names differ by a single letter. This is an intentional design — they represent separate pipeline stages — but the one-letter difference is a known footgun. **Do not unify them into one variable.**

| Variable | Stage | Meaning |
|---|---|---|
| `PRE_REVIEW_GATE_DOWN` | Set in **Step 6.P1** | *Intermediate eligibility flag.* `1` = task is tentatively eligible for the Flash shortcut (no drift-up detected); `0` = drift-up forces codex (skip the shortcut entirely). |
| `PRE_REVIEW_GATED_DOWN` | Set in **Step 6.P2** | *Final decision flag.* `1` = Flash returned CLEAN on a low-tier eligible task so codex is **skipped**; `0` = Flash flagged issues or task was not eligible. This is the variable the downstream skip-guard reads. |

**Flow:**

```
P1: complexity-classifier re-runs → drift-up? → PRE_REVIEW_GATE_DOWN=0 (skip shortcut)
                                   → no drift? → PRE_REVIEW_GATE_DOWN=1 (eligible)

P2: only runs when PRE_REVIEW_GATE_DOWN=1 AND EFFECTIVE_TIER=="low"
    → Flash CLEAN      → PRE_REVIEW_GATED_DOWN=1  (codex skipped)
    → Flash MAJORS/BLOCKERS → PRE_REVIEW_GATED_DOWN=0 (escalate to codex)

downstream guard: if [ "${PRE_REVIEW_GATED_DOWN:-0}" -ne 1 ]; then  <run codex>  fi
```

`PRE_REVIEW_GATED_DOWN` is initialized to `0` unconditionally before the knob block, so the downstream guard always reads a defined value regardless of whether the knob is enabled.

**Footgun note:** `GATE_DOWN` (no "D") is the eligibility flag; `GATED_DOWN` (with "D") is the skip decision. Searching for one and editing the other is a silent bug — both variables must remain distinct.

## Edge cases / gotchas

- The cost-inversion risk is real: Flash on all tasks + codex on a subset can exceed the cost of codex-on-all when most tasks are medium/high tier or when Flash call cost is non-trivial. Run the audit before enabling.
- `complexity-classifier` heuristic #1 returns the user-authored tier if `**Complexity:** ...` is present in the input — stripping the line is mandatory for drift detection to work.
- Flash verdict parsing (`FLASH_VERDICT`) uses `grep -o 'VERDICT:[[:space:]]*[A-Z_]*'`; any `**VERDICT:**` label format deviating from this pattern will yield an empty verdict and fall through to codex (safe default).
- The `pre-reviewer` agent is told `tier: low` in its prompt; it should focus on quick blockers/majors only, not nitpicks.
- `FLASH_PREPEND` is injected into the codex reviewer prompt when Flash flags issues; the codex reviewer is not constrained by Flash's findings — it may agree, disagree, or find additional issues.
- **`PRE_REVIEW_GATE_DOWN` vs `PRE_REVIEW_GATED_DOWN`** — names differ by one letter ("GATE" vs "GATED"); they serve different pipeline stages and must not be conflated (see "Two-variable gate-down design" section above).

## See also

- `commands/z-implement-all.md:1280` — full knob block prose and code.
- `scripts/audit-preview-misses.sh` — evidence gate script.
- `agents/pre-reviewer.md` — Flash pre-reviewer agent definition.
- `agents/complexity-classifier.md` — tier classifier reused for drift re-check.
- `docs/human/subagent-telemetry.md` — `pre-reviewer` dispatch is logged via `log-subagent.sh`.
- `docs/human/config.md` — env-only knobs section (this knob is not a TOML key).
