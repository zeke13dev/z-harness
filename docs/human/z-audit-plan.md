# z-audit-plan

> Last updated: 2026-06-24
> Covers source: skills/z-audit-plan/SKILL.md, docs/human/z-audit-plan.md

## Overview

`/z-audit-plan` audits a plan before implementation. It collects reality-check findings, design/style findings, and adversarial consultant findings, applies a one-reason-this-might-be-wrong pushback pass, writes `PLAN_AUDIT_REPORT.md`, and then runs Phase 5 continuation logic.

The command is read-only with respect to code. Plan corrections happen via `/z-amend` or by the user replanning; audit itself does not edit production code.

## Phase 4 — Class tagging

Every surviving report finding must include `**Class:**` immediately after `**Severity:**`. Audit-plan findings use only:

| Class | Meaning |
|---|---|
| `spec_gap` | Factual/mechanical issue in plan artifacts: wrong path, symbol, table, config value, criterion, or naming. |
| `premise_failure` | Viability/design concern: wrong approach, scale issue, flawed assumption, or materially better path. |

Class, not severity, is the discriminator. `correction` and `approach` are prose glosses only.

## Phase 5 continuation

Phase 5 first heartbeats the plan claim, then resolves `workflow.audit_to_amend` and maps the resolver envelope with `scripts/amend-gate-decision.py`:

- `halt`: emit `audit_halt`, jump to run-brief halt finalize, exit.
- `auto_split`: extract report findings by Class; auto-amend `spec_gap` findings via `/z-amend --skip-user-gate`; batch all INTENT-mode corrections into one amend call, or one per finding in legacy mode; skip completed `[x]` task references; render `premise_failure` concerns with `amendment-brief.py`.
- `force_ask`: no longer opens a popup. It emits a prose alignment summary and records `force_ask_prose` for run-brief outcome.

Run-brief finalization now owns the user-facing completion text and next-step recommendation before `plan_audit_end` is logged.

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-audit-plan/SKILL.md:511` — Class tagging — assigns canonical Class to every surviving finding.
- `skills/z-audit-plan/SKILL.md:557` — per-finding format — requires `**Class:**` immediately after `**Severity:**`.
- `skills/z-audit-plan/SKILL.md:596` — Phase 5 gate decision — calls `config.py resolve-question` then `amend-gate-decision.py`.
- `skills/z-audit-plan/SKILL.md:621` — halt branch — emits `audit_halt` and uses Run Brief halt finalize.
- `skills/z-audit-plan/SKILL.md:631` — auto_split branch — extracts by Class, auto-amends spec_gap, renders premise_failure.
- `skills/z-audit-plan/SKILL.md:661` — target-mode aware auto-amend — INTENT batches all corrections; legacy amends per finding.
- `skills/z-audit-plan/SKILL.md:778` — force_ask prose branch — conversational summary instead of popup.
- `skills/z-audit-plan/SKILL.md:807` — Run Brief finalize — sets outcome/next/approach before `plan_audit_end`.
- `skills/z-audit-plan/SKILL.md:863` — `plan_audit_end` — completion telemetry event.
<!-- AUTO-END: entry-points -->

## Invariants

- Audit-plan is read-only for production code.
- Every surviving finding has a Class field.
- Audit-plan Class values are restricted to `spec_gap` and `premise_failure`.
- Completed `[x]` task references are skipped during auto_split amend extraction.
- INTENT-mode auto_split batches all spec_gap corrections into one `/z-amend` call.
- `force_ask` is now prose alignment, not AskUserQuestion.
- Run Brief finalize is the single user-facing completion surface.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-audit-plan.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
