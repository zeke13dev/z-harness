# impl-pre-review

> Last updated: 2026-06-19
> Covers source: skills/z-execute/SKILL.md, scripts/audit-preview-misses.sh, agents/pre-reviewer.md, agents/complexity-classifier.md

## Overview

`impl-pre-review` is the opt-in pre-review gate-down for the per-task implement gate in `/z-execute`. It adds a cheap Haiku-tier `pre-reviewer` agent as a first-pass scan before the full external codex reviewer, with the aim of skipping the codex reviewer on clean low-tier tasks. A second, related knob (`runtime.pre_review`) gates a parallel 3-prong pre-review cycle that runs inside `/z-review-all` Phase 3.6; that cycle uses the same `pre-reviewer` agent but is a separate feature with separate config.

**Both features ship inert by default.** `runtime.impl_pre_review` (default `false`) controls the per-task gate-down in `/z-execute`. `runtime.pre_review` (default `false`) controls the Phase 3.6 pre-review cycle in `/z-review-all`. Neither is enabled unless the user sets the corresponding TOML key. The legacy env aliases `Z_HARNESS_IMPL_PRE_REVIEW` and `Z_HARNESS_PRE_REVIEW` are still accepted (transliterated by `config.py export-env`), but the TOML keys are the canonical form.

## Cost-inversion caveat

> **Running Flash/Haiku on every task plus codex on a subset can invert total cost relative to running codex on every task.** Enable only after reviewing `scripts/audit-preview-misses.sh` results.

Haiku has a non-trivial per-call cost. On a plan where most tasks are medium or high tier (not eligible for gate-down), Haiku runs on all of them with no savings, while codex runs on the same medium/high tasks as before plus any flagged low-tier tasks. The net effect can be higher total spend than baseline. The `impl_pre_review` knob is **undocumented-as-recommended** until `scripts/audit-preview-misses.sh` demonstrates acceptable Flash false-negative rate on low-tier tasks.

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-execute/SKILL.md:1951` — `runtime.impl_pre_review` block header — knob description, cost-inversion caveat, NO-OP fallthrough guarantee
- `skills/z-execute/SKILL.md:1969` — `if config.py get runtime.impl_pre_review == "true" && CYCLE==1` — outer knob gate; also checks `CYCLE -eq 1`
- `skills/z-execute/SKILL.md:1974` — Step 6.P1 — Tier-drift re-check — strips cached `**Complexity:**` stamp; dispatches `complexity-classifier` for `LIVE_TIER`
- `skills/z-execute/SKILL.md:2019` — Step 6.P2 — Gate-down (low-tier only) — probes Flash provider; dispatches `pre-reviewer` in `final-review-prong-a` mode; branches on `FLASH_VERDICT`
- `skills/z-execute/SKILL.md:2098` — Step 6.P3 — Medium/high advisory — Flash runs advisory-only (no gate authority); `FLASH_PREPEND` set if useful
- `commands/z-review-all.md:267` — Phase 3.6 — Pre-review cycle (opt-in via `runtime.pre_review`) — 3 parallel `pre-reviewer` dispatches before Phase 4 consultants
- `scripts/audit-preview-misses.sh:1` — evidence gate — samples `review_gated_down` events; re-runs codex; reports Flash false-negative rate
- `agents/pre-reviewer.md:1` — `pre-reviewer` agent — 4 modes: `final-review-prong-a`, `final-review-prong-b`, `final-review-quality`, `plan-audit`; emits `**VERDICT:**` line
- `agents/complexity-classifier.md:1` — `complexity-classifier` — reused in Step 6.P1 for tier-drift re-check
<!-- AUTO-END: entry-points -->

## Knob: runtime.impl_pre_review (per-task gate-down)

| Property | Value |
|----------|-------|
| TOML key | `runtime.impl_pre_review` |
| Default | `false` (off) |
| Legacy env alias | `Z_HARNESS_IMPL_PRE_REVIEW` (transliterated by `config.py export-env`) |
| Scope | TOML config + legacy env alias |
| Ships | inert — byte-identical to today when `false` |

Before the knob block, two downstream variables are initialized unconditionally:

```bash
PRE_REVIEW_GATED_DOWN=0
FLASH_PREPEND=""
```

These ensure the skip-guard and reviewer prompts always read a defined value even on the knob-off path.

## Knob: runtime.pre_review (/z-review-all pre-review cycle)

| Property | Value |
|----------|-------|
| TOML key | `runtime.pre_review` |
| Default | `false` (off) |
| Legacy env alias | `Z_HARNESS_PRE_REVIEW` |
| Scope | TOML config + legacy env alias |

When enabled, `/z-review-all` Phase 3.6 spawns 3 `pre-reviewer` agents in parallel on the cumulative diff before dispatching the Phase 4 production-grade consultants. Results are fed as additional context into the consultant prompts. This is distinct from the per-task gate-down (`impl_pre_review`) and never skips any reviewer — it only prepends pre-findings.

## Pre-reviewer agent modes

The `pre-reviewer` agent is not a single-purpose tool. It operates in four named modes passed in the `MODE:` field of its prompt:

| Mode | Focus |
|------|-------|
| `final-review-prong-a` | Implementation drift — files that changed wrong, missing changes, stale references |
| `final-review-prong-b` | Spec gaps — edge cases the spec missed, wrong decisions |
| `final-review-quality` | Code quality — defensive bloat, premature abstraction, DRY/KISS/SOLID violations |
| `plan-audit` | Plan review — reference errors, design issues, logic flaws in plan artifacts |

In the `/z-execute` gate-down path (Step 6.P2), mode is `final-review-prong-a`. In `/z-review-all` Phase 3.6, three parallel dispatches use `final-review-prong-a`, `final-review-prong-b`, and `final-review-quality` respectively.

## Behavior when impl_pre_review = true

The gate-down block runs only on `CYCLE == 1`. Retry cycles always go directly to the full codex reviewer.

### Step 6.P1 — Tier-drift re-check

Strip the cached `**Complexity:**` line from the task block, then dispatch `complexity-classifier` to derive `LIVE_TIER` from scratch:

```bash
TASK_BLOCK_FOR_DRIFT="$(printf '%s' "$TASK_BLOCK" | grep -v '^\*\*Complexity:\*\*')"
```

Compare `LIVE_TIER` rank against `COMPLEXITY_TIER` (plan-time cached stamp):

- **Drift-up** (`LIVE_RANK > CACHED_RANK`): emit `tier_drift_detected`, set `EFFECTIVE_TIER` to live tier, set `PRE_REVIEW_GATE_DOWN=0` (skip Flash shortcut; force codex).
- **No drift**: set `EFFECTIVE_TIER` to cached tier, set `PRE_REVIEW_GATE_DOWN=1` (tentatively eligible).

### Step 6.P2 — Gate-down (low-tier only)

Runs only when `PRE_REVIEW_GATE_DOWN=1` AND `EFFECTIVE_TIER == "low"`.

1. Probe `resolve-provider.py pre-reviewer`. If unavailable, emit `pre_review_skipped {reason:"provider_unavailable"}` and fall through to codex.
2. If available, dispatch `pre-reviewer` in `final-review-prong-a` mode on the task diff.
3. Parse `FLASH_VERDICT` from the `**VERDICT:**` line.

| Verdict | Action |
|---------|--------|
| `CLEAN` | Emit `review_gated_down`. Set `BLOCKER_COUNT=0`, `MAJORS_COUNT=0`, `PRE_REVIEW_GATED_DOWN=1`. Codex skipped. |
| `MAJORS_FOUND` or `BLOCKERS_FOUND` | Set `FLASH_PREPEND` to the Flash findings. Escalate to codex with findings prepended. `PRE_REVIEW_GATED_DOWN=0`. |
| Empty/malformed | Falls through to codex (safe default). |

### Step 6.P3 — Medium/high advisory (no gate authority)

When `EFFECTIVE_TIER` is `medium` or `high` and Flash is available, optionally dispatch pre-reviewer to prepend findings to the codex prompt. `PRE_REVIEW_GATED_DOWN` stays `0` — Flash is never authoritative at these tiers.

### Telemetry events

| Event | When |
|-------|------|
| `tier_drift_detected` | Drift-up in Step 6.P1; `cached_tier`, `live_tier`, `action:"force_codex"` |
| `pre_review_skipped` | Flash provider unavailable; `reason:"provider_unavailable"`, `tier` |
| `review_gated_down` | Flash returned CLEAN; codex skipped; `id`, `tier`, `provider:"flash"`, `cycle` |

## Evidence gate

`scripts/audit-preview-misses.sh` is the evidence gate. Options:

- `--slug <slug>` — scope to a specific plan
- `--metrics <path>` — explicit `metrics.jsonl` path (default: auto-resolved via `plan-path.sh`)
- `--sample N` — limit to N gated events
- `--report <path>` — write report to file
- `--demo` — inject a synthetic `review_gated_down` event for flow testing

The script is **read-only**: it never mutates TASKS.md, plan state, or the event stream. It samples `review_gated_down` events, re-runs the codex reviewer on archived diffs, and reports the Flash false-negative rate. Threshold: miss rate ≤ 10% triggers a "consider enabling" recommendation.

## Two-variable gate-down design: GATE_DOWN vs GATED_DOWN

**Two distinct shell variables whose names differ by one letter.** Do not unify them.

| Variable | Stage | Meaning |
|---|---|---|
| `PRE_REVIEW_GATE_DOWN` | Set in Step 6.P1 | Eligibility flag: `1` = no drift-up, eligible for Flash shortcut |
| `PRE_REVIEW_GATED_DOWN` | Set in Step 6.P2 | Skip decision: `1` = Flash returned CLEAN, codex skipped |

```
P1: classifier → drift-up? → PRE_REVIEW_GATE_DOWN=0 (force codex)
                 no drift?  → PRE_REVIEW_GATE_DOWN=1 (eligible)

P2 (only when GATE_DOWN=1 AND low-tier):
    Flash CLEAN        → PRE_REVIEW_GATED_DOWN=1 (codex skipped)
    Flash MAJORS/BLOCK → PRE_REVIEW_GATED_DOWN=0 (escalate to codex)

downstream guard: if [ "${PRE_REVIEW_GATED_DOWN:-0}" -ne 1 ]; then <run codex> fi
```

## Invariants

- `runtime.impl_pre_review=false` (default): entire block is a NO-OP; byte-identical to today.
- Gate-down only runs on cycle 1; retry cycles always use the full codex reviewer.
- Flash provider unavailable → fail-safe toward the more thorough review (codex runs); never silently skip.
- Tier-drift re-check strips the cached `**Complexity:**` stamp before dispatching the classifier.
- Medium/high tier tasks are never gated down by Flash; Flash may prepend findings but is not authoritative.
- `PRE_REVIEW_GATED_DOWN` and `FLASH_PREPEND` are always initialized before the knob block.
- `PRE_REVIEW_GATE_DOWN` (eligibility, set in P1) and `PRE_REVIEW_GATED_DOWN` (skip decision, set in P2) are two DISTINCT variables — must never be unified; downstream skip-guard reads only `GATED_DOWN`.
- `runtime.pre_review` and `runtime.impl_pre_review` are independent knobs; enabling one does not enable the other.

## Edge cases / gotchas

- Cost-inversion risk: Haiku on all tasks + codex on a subset can exceed codex-on-all when most tasks are medium/high. Run the audit before enabling.
- `complexity-classifier` heuristic #1 returns the user-authored tier if `**Complexity:**` is present — stripping the line is mandatory for drift detection.
- Flash verdict parsing uses `grep -o 'VERDICT:[[:space:]]*[A-Z_]*'`; format deviations yield empty verdict and fall through to codex (safe).
- `pre-reviewer` operates in `final-review-prong-a` mode in the gate-down path — correctness and spec drift focus. It is not a generic CLEAN/FAIL oracle.
- `FLASH_PREPEND` is injected into the codex prompt; codex is not constrained by Flash's findings.
- `Z_HARNESS_IMPL_PRE_REVIEW` is now a legacy env alias (not the primary form); prefer `runtime.impl_pre_review = true` in `config.toml`.
- `models.pre_reviewer` in config.toml pins the model for the `pre-reviewer` role (default empty = resolved via providers.json).
- **`PRE_REVIEW_GATE_DOWN` vs `PRE_REVIEW_GATED_DOWN`** — names differ by one letter ("GATE" vs "GATED"); they serve different pipeline stages; editing one while intending the other is a silent bug.

## See also

- `skills/z-execute/SKILL.md:1951` — full knob block.
- `commands/z-review-all.md:267` — Phase 3.6 pre-review cycle (separate knob: `runtime.pre_review`).
- `scripts/audit-preview-misses.sh` — evidence gate script.
- `agents/pre-reviewer.md` — pre-reviewer agent definition (4 modes).
- `agents/complexity-classifier.md` — tier classifier reused for drift re-check.
- `docs/human/subagent-telemetry.md` — `pre-reviewer` dispatch logged via `log-subagent.sh`.
- `docs/human/config.md` — `runtime.impl_pre_review`, `runtime.pre_review`, `models.pre_reviewer` TOML keys.
