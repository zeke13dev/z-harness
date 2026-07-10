# attend

> Last updated: 2026-07-09
> Covers source: skills/z-attend/SKILL.md, scripts/chain-runner.sh, scripts/config.py, scripts/lint-halt-categories.sh, scripts/surface-shortcut.sh, scripts/write-handoff.sh, docs/schemas/handoff.schema.json

## Overview

`/z-attend` is the middle gear between fully unattended `/z-overnight` (halts everything for later resume) and manual one-command-at-a-time operation. It auto-advances through a configured command chain while the user is present, auto-answers only mechanical "proceed?" gates, asks inline for the four substantive gate categories, and yields at declared context boundaries so the user can `/clear` and resume safely via a hardened `handoff.json` predicate.

The default preset is `attend-full`: `plan, audit, test, implement-all, review-all` (full-build plus an `audit` step after `plan`). `scripts/chain-runner.sh` owns sequencing/state/cursor mechanics and is shared with `/z-overnight`; `skills/z-attend/SKILL.md` owns gate policy (the category posture) and the resume protocol — policy and mechanics are deliberately split (Invariant 2 in the skill's own operating rules).

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-attend/SKILL.md:55` — fail-safe category rule — unknown/untagged question IDs resolve to `ask`, never `mechanical_proceed`.
- `skills/z-attend/SKILL.md:137` — `attend_resume` predicate extraction — resume refuses handoffs without the protocol-1.1 predicate.
- `skills/z-attend/SKILL.md:157` — HEAD mismatch guard (R1) — emits `attend_resume_halt`, hard-halts unless the user accepts the new base.
- `skills/z-attend/SKILL.md:286` — attend-state path — `$BASE/archive/$RUN_ID/attend-state.json` (run-scoped, never `overnight-state.json`).
- `skills/z-attend/SKILL.md:295` — preflight gate-lint — lists uncategorized chain gates before the first step (advisory only).
- `skills/z-attend/SKILL.md:468` — risk-outcome halt (Step 2.7) — emits `attend_risk_halt` on a reviewer blocker or audit reject; asks `{fix-retry, abort, continue-anyway}`.
- `scripts/chain-runner.sh:94` — `cmd_steps` — emits `name:yield_after` lines for a preset; the sole authority for chain composition.
- `scripts/chain-runner.sh:87` — `_yield_after` — true only for `plan` and `implement-all`.
- `scripts/chain-runner.sh:283` — `cmd_new_run_id` — C14 archive set-difference identifying a step's sub-run, excluding `*-overnight-*`.
- `scripts/config.py:519` — `HALT_CATEGORY_ENUM` — canonical category enum `{decision, risk, shortcut, archiving, mechanical_proceed}`.
- `scripts/config.py:2014` — `cmd_resolve_halt_category` — returns the registered category for a question id, or `ask` for unknown/untagged.
- `scripts/write-handoff.sh:259` — protocol-1.1 `attend_resume` writer — validates all five attend env vars are non-empty before embedding the predicate.
- `docs/schemas/handoff.schema.json:69` — `attend_resume` schema — optional object, all five fields `minLength: 1`.
<!-- AUTO-END: entry-points -->

## Gate taxonomy

`config.py resolve-halt-category <question_id>` returns one of `decision`, `risk`, `shortcut`, `archiving`, `mechanical_proceed`, or `ask`. Unknown or untagged IDs resolve to `ask` — never to mechanical auto-proceed (HARD INVARIANT 1, fail-safe).

| Category | Attend behavior |
|---|---|
| `mechanical_proceed` | Auto-answer with the question's skill default; log `attend_gate_auto`. |
| `decision`, `risk`, `shortcut`, `archiving` | Surface inline via `AskUserQuestion`; log `attend_gate_asked`. |
| `ask` / unknown | Fail-safe surface inline; never auto-skip. |

`lint-halt-categories.sh --check-chain <preset>` runs once before the first step (Phase 1, preflight) and lists uncategorized reachable gates. It is advisory only: the chain still runs, and any uncategorized gate simply surfaces inline (`ask`) at runtime.

A second gate-adjacent mechanism, `surface-shortcut.sh`, fires once pre-loop (Step 2.0) when the resolved chain omits an `audit` step: it emits `shortcut_proposed` and returns exit code `1` as the deterministic "surface a `category=shortcut` ask" signal (`0` = no-op, chain already includes audit; `2` = infra error, fall back to asking anyway).

## Chain presets

`chain-runner.sh steps <preset>` is the sole authority for a preset's step list — never hardcode it. Current presets (`scripts/chain-runner.sh` `_expand_preset`):

| Preset | Steps |
|---|---|
| `attend-full` (default) | `plan, audit, test, implement-all, review-all` |
| `full-build` | `plan, test, implement-all, review-all` |
| `quick-build` | `plan, implement-all` (no `review-all`) |
| `research-build` | `research, plan, test, implement-all, review-all` |

## Yield and resume

`chain-runner.sh steps <preset>` emits `step:yield_after` lines. Only `plan` and `implement-all` currently have `yield_after=true` (`_yield_after`). A child sub-run can also force a yield mid-step by writing a `handoff.json` with `status == "context_pressure"` — this fires the yield protocol even when `yield_after` is false for the current step.

When a boundary fires, `write-handoff.sh` writes protocol version `1.1` and an `attend_resume` predicate containing:

- `expected_head_sha`
- `expected_phase`
- `done_set_hash`
- `dirty_state_fingerprint`
- `session_id`

All five are required (`write-handoff.sh` refuses to emit a schema-invalid 1.1 token if any is empty). Resume refuses non-attend or pre-1.1 handoff tokens.

## Resume safety checks (Phase 0R)

1. **HEAD mismatch (R1)** — hard halt (`category=risk`); default `re-plan`; `accept-new-base` rewrites `expected_head_sha` and continues.
2. **State cursor vs token phase mismatch (R2)** — hard halt (`category=risk`); options are abort or continue from the state-file cursor (the durable backend wins).
3. **Session id unchanged (R3)** — warn hard (`category=risk`), default remediation is abort and run `/clear` first; user may continue anyway.
4. **Done-set or dirty-tree drift (R4)** — warn-and-ask (`category=risk`), default options are continue/abort (fail-safe, not fail-closed — drift is a soft signal).

The immutable `handoff.json` predicate is the source of truth for resume validation; `SESSION.md` edits never affect resume safety.

## Step-outcome risk halt (Step 2.7, distinct from resume)

Separate from the Phase 0R resume checks above, a **step's own outcome** can also trigger an inline risk halt mid-chain: a `review-all` step classified `halt`/`error` on a blocking finding, or an `audit` step classified `halt`/`error` on a reject. This emits `attend_risk_halt` and asks `{fix-retry, abort, continue-anyway}` — it does not silently advance the chain past a reviewer blocker or an audit reject.

## How it interacts with others

- `z-overnight` — shares `scripts/chain-runner.sh` for sequencing/state/cursor mechanics (same runner, different gate policy: overnight sets `Z_HARNESS_NO_ASK=halt`, attend never does).
- `session-handoff` (`write-handoff.sh`, `docs/schemas/handoff.schema.json`) — attend is the only caller that populates the optional `attend_resume` predicate (protocol 1.1); `z-plan`, `z-handoff`, and `z-execute`'s clear-checkpoint path use the same script for plain 1.0 handoffs.
- `config` (`scripts/config.py`) — `HALT_CATEGORY_ENUM` and `resolve-halt-category` are the single source of truth for the gate taxonomy; attend never re-implements category resolution.
- Child skills dispatched via the chain (`z-plan`, `z-audit-plan`, `z-test`, `z-execute`, `z-review-all`, `z-research`) — attend is a wrapper only. It does not run Artifact Scout itself (Step 2.0a); it only passes a child step's scout output through inline, preserving child artifact paths, and never creates a wrapper-level `route-decision.md`.

## Edge cases / gotchas

- `/z-attend` never sets `Z_HARNESS_NO_ASK=halt` — the user is present, so substantive gates surface inline instead of becoming halt events (unlike `/z-overnight`).
- `attend-state.json` is attend-scoped (`$BASE/archive/$RUN_ID/attend-state.json`); it is never `overnight-state.json` — the state-file path is a parameter to `chain-runner.sh`, not a hardcoded constant.
- `chain-runner.sh state-write`'s stdin form (`-`) avoids OS argv/env size limits for large state payloads; both the argv and stdin forms share identical flock + tmp-rename semantics.
- `new-run-id` excludes `*-overnight-*` dirs internally; the attend caller separately excludes both `*-attend-*` and `*-overnight-*` dirs from its own before/after snapshot (Step 2.3).
- `surface-shortcut.sh` exit code `1` means "surface the shortcut ask" (deterministic success signal, independent of `log-event.sh`'s own return code); `0` means no-op (no declined alternative — Invariant 6); `2` is an infra/wiring error that still falls back to asking.
- No retry on a Skill exception — the chain stops (`STEP_STATUS=error`) and the user re-invokes `/z-attend resume <RUN>` after fixing, matching `/z-overnight`'s behavior.
- `quick-build` has no `review-all` step; a chain built on it will never trigger the Step 2.7 risk-halt path for a reviewer blocker.

## Examples

- Start a default run: `/z-attend "add rate limiting to the API"` → `attend-full` preset.
- Start with an explicit preset: `/z-attend quick-build "hotfix the typo"`.
- Resume after a `/clear`: `/z-attend resume <RUN>`.
- Check progress without mutating state: `/z-attend status <RUN>`.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/attend.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
