# z-audit-plan

> Last updated: 2026-06-19
> Covers source: commands/z-audit-plan.md

## Overview

`/z-audit-plan` is a structured, pre-implementation plan audit pipeline. It audits a plan's
artifacts (SPEC.md, PLAN.md, TASKS.md) before execution by running a multi-phase review:
reality-check of references against the codebase, best-practices and design audit, and an
adversarial cross-LLM review. The pipeline emits `PLAN_AUDIT_REPORT.md` and then gates on a
default-amend continuation path (Phase 5).

The command is **read-only**: it never edits active codebase files. Plan adjustments happen later
via `/z-amend` (spec_gap corrections) or `/z-plan` (premise_failure re-plan) based on the report.

## Phase pipeline

| Phase | Name | Key output |
|-------|------|------------|
| 0 | Setup | Slug resolution, claim acquire, registry register |
| 1 | Reality Check | Reference verification — stale paths, wrong symbols, naming drift |
| 2 | Best Practices & Design Audit | SOLID/DRY violations, style, security |
| 2.5 | Pre-review (opt-in) | Optional self-reviewer pass |
| 3 | Adversarial Cross-LLM Review | Two consultant subagents, adversarial challenge |
| 4 | Merge and Synthesize | Class-tagged PLAN_AUDIT_REPORT.md |
| 5 | Gate & Action | Default-amend continuation (auto_split / force_ask / halt) |
| 9 | Elevation Proposer | Preference elevation check |

## Phase 4 — Class tagging

After the One-Reason-This-Might-Be-Wrong gate in Phase 4, every surviving finding is tagged with a
canonical `**Class:**` field using the enum from `z-review-all.md:716`. For audit-plan, only two
values apply:

| Class | Meaning |
|-------|---------|
| `spec_gap` | Factual/mechanical error: wrong path, wrong symbol, malformed criterion, naming drift. The plan states something incorrect. |
| `premise_failure` | Viability/design concern: won't scale, wrong library, foundational assumption is flawed. The plan is internally consistent but the approach is questionable. |

The discriminator is **Class, not severity**. A BLOCKER can be either `spec_gap` or
`premise_failure`. `correction` and `approach` are human-readable glosses only — never use them as
`Class` values in PLAN_AUDIT_REPORT.md.

Per-finding format in PLAN_AUDIT_REPORT.md:

```markdown
- **Severity:** MAJOR
- **Class:** spec_gap
- **Location:** SPEC.md §2
- **Finding:** description
- **Recommendation:** action
```

## Phase 5 — Default-amend continuation

Phase 5 implements the default-amend path. The orchestrator:

1. Calls `config.py resolve-question workflow.audit_to_amend` to get the resolver envelope.
2. Pipes the envelope to `scripts/amend-gate-decision.py` to get a gate token.
3. Dispatches on the gate token:

### `auto_split` (default for fresh users)

No popup. The orchestrator splits findings by Class:

- **`spec_gap` findings** → auto-amend via `/z-amend --skip-user-gate`. For an INTENT-mode target
  plan, ALL spec_gap corrections are batched into ONE `/z-amend` call (single contract re-freeze).
  For a legacy-mode target, one `/z-amend` per finding is used. Completed (`[x]`) tasks are skipped.
- **`premise_failure` findings** → rendered as prose brief via `scripts/amendment-brief.py` and
  presented conversationally. The user replies to decide whether to rework, proceed, or re-plan.

The `auto_split` path emits an `audit_auto_split` telemetry event recording the counts.

### `force_ask`

The 3-way AskUserQuestion popup is presented (legacy path, unchanged):
- **Amend Plan (Run z-amend)** — trigger interactive `/z-amend`
- **Proceed as-is** — acknowledge findings as acceptable tradeoffs
- **Reject & Re-plan** — discard plan artifacts and rerun `/z-plan`

This path fires only when `amend-gate-decision.py` returns `force_ask` (i.e. an explicit user
preference stored in config or memory requests interactive input).

### `halt`

Abort immediately. No amend, no popup.

## workflow.audit_to_amend — source-keyed semantics

This config key is the force-ask override. The effective behavior depends on the **resolver
source** (where the preference came from), not just the stored value:

| Source | Effective gate |
|--------|---------------|
| `none` (no preference stored anywhere) | `auto_split` — new default for fresh users |
| `config` or `memory` with `ask` or `prefill` value | `force_ask` — honours explicit preference for interaction |
| Any source with `halt` / `stop` value | `halt` — abort immediately |
| `skip` / `amend` from any source | `auto_split` — user configured auto-amend |

Setting `workflow.audit_to_amend = ask` in `config.toml` or a routing-preference memory entry
explicitly opts back into the 3-way popup for every audit run.

## INTENT-mode vs legacy-mode awareness

Phase 5 auto-amend is target-mode-aware:

- **INTENT-mode target**: all `spec_gap` corrections are batched into **one `/z-amend` call** to
  avoid N contract re-opens for N trivial fixes (each re-freeze invalidates TASKS.md).
- **Legacy-mode target**: one `/z-amend --skip-user-gate` per finding is used.

## Key entry points

<!-- AUTO-START: entry-points -->
- `commands/z-audit-plan.md:1` — command definition — role, read-only constraint, argument parsing
- `commands/z-audit-plan.md:427` — Phase 4 — merge/synthesize; Class tagging; PLAN_AUDIT_REPORT.md format with **Class:** field
- `commands/z-audit-plan.md:501` — per-finding format — Severity + Class fields required on every surviving finding
- `commands/z-audit-plan.md:516` — Phase 5 — gate resolution via amend-gate-decision.py; auto_split / force_ask / halt dispatch
- `commands/z-audit-plan.md:554` — Phase 5 resolver call — config.py resolve-question + amend-gate-decision.py pipeline
- `commands/z-audit-plan.md:575` — auto_split branch — target-mode-aware /z-amend + amendment-brief.py render
- `commands/z-audit-plan.md:638` — audit_auto_split telemetry event
- `commands/z-audit-plan.md:645` — force_ask branch — 3-way popup (fires only on explicit preference)
- `commands/z-audit-plan.md:765` — Phase 9 — elevation proposer
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `config.py resolve-question workflow.audit_to_amend` — resolver envelope consumed by Phase 5 to
  determine gate token.
- `scripts/amend-gate-decision.py` — maps resolver envelope to `auto_split | force_ask | halt`.
- `scripts/amendment-brief.py` — shared renderer called on the `auto_split` path to present the
  brief conversationally.
- `/z-amend --skip-user-gate` — invoked by Phase 5 auto_split path to apply spec_gap corrections.
- `/z-review-all` — shares the same Class enum and the same amendment-brief.py renderer.
- `scripts/run-brief.sh` + `scripts/render-run-brief.py` — Phase 5 populates the run-brief
  pipeline with outcome/next/approach sections.

## Telemetry events

| Event | Phase | Payload fields |
|-------|-------|---------------|
| `plan_audit_end` | 5 (after gate) | `status`, `findings`, `blockers`, `majors` |
| `audit_auto_split` | 5 (auto_split path) | `corrections_auto_amended`, `approach_concerns_surfaced`, `target_mode` |
