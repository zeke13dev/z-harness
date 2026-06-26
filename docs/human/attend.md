# attend

> Last updated: 2026-06-24
> Covers source: skills/z-attend/SKILL.md, scripts/chain-runner.sh, scripts/config.py, scripts/lint-halt-categories.sh, scripts/surface-shortcut.sh, scripts/write-handoff.sh, docs/schemas/handoff.schema.json

## Overview

`/z-attend` is the middle gear between fully unattended `/z-overnight` and manual one-command-at-a-time operation. It runs a configured command chain while the user is present, auto-answers only mechanical proceed gates, asks inline for substantive gates, and yields at context boundaries so the user can `/clear` and resume safely.

The default preset is `attend-full`: `plan, audit, test, implement-all, review-all`. `chain-runner.sh` owns sequencing/state/cursor mechanics; `skills/z-attend/SKILL.md` owns the gate posture and resume protocol.

## Gate taxonomy

`config.py resolve-halt-category <question_id>` returns one of `decision`, `risk`, `shortcut`, `archiving`, `mechanical_proceed`, or `ask`. Unknown or untagged IDs resolve to `ask`, never to mechanical auto-proceed.

| Category | Attend behavior |
|---|---|
| `mechanical_proceed` | Auto-answer with the question's skill default; log `attend_gate_auto`. |
| `decision`, `risk`, `shortcut`, `archiving` | Surface inline via `AskUserQuestion`; log `attend_gate_asked`. |
| `ask` / unknown | Fail-safe surface inline; never auto-skip. |

`lint-halt-categories.sh --check-chain <preset>` runs before the first step and lists uncategorized reachable gates. It is advisory: the chain still runs, and uncategorized gates surface inline at runtime.

## Yield and resume

`chain-runner.sh steps <preset>` emits `step:yield_after` lines. Only `plan` and `implement-all` currently have `yield_after=true`, though a child sub-run can also force yield by writing `handoff.json` with `status == context_pressure`.

When a boundary fires, `write-handoff.sh` writes protocol version `1.1` and an `attend_resume` predicate containing:

- `expected_head_sha`
- `expected_phase`
- `done_set_hash`
- `dirty_state_fingerprint`
- `session_id`

All five are required. Resume refuses non-attend or pre-1.1 handoff tokens.

## Resume safety checks

1. HEAD mismatch: hard halt, default `re-plan`; optional accept-new-base rewrites `expected_head_sha`.
2. State cursor vs token phase mismatch: hard halt, default abort.
3. Session id unchanged: warning, default abort and run `/clear` first.
4. Done-set or dirty-tree drift: warning, default continue.

The immutable `handoff.json` predicate is the source of truth; SESSION.md edits do not affect resume safety.

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-attend/SKILL.md:56` — fail-safe category rule — unknown question IDs resolve to `ask`, never `mechanical_proceed`.
- `skills/z-attend/SKILL.md:90` — state file path — `$BASE/archive/$RUN_ID/attend-state.json`.
- `skills/z-attend/SKILL.md:132` — `attend_resume` extraction — resume refuses handoffs without the protocol-1.1 predicate.
- `skills/z-attend/SKILL.md:157` — HEAD mismatch guard — emits `attend_resume_halt`.
- `skills/z-attend/SKILL.md:290` — preflight gate-lint — lists uncategorized chain gates before the first step.
- `scripts/chain-runner.sh:27` — `steps` subcommand — emits `name:yield_after` lines.
- `scripts/chain-runner.sh:86` — `_yield_after` — true only for `plan` and `implement-all`.
- `scripts/chain-runner.sh:283` — `new-run-id` — C14 archive set-difference with overnight exclusion.
- `scripts/config.py:317` — `HALT_CATEGORY_ENUM` — canonical category enum.
- `scripts/config.py:1707` — `cmd_resolve_halt_category` — returns registered category or `ask`.
- `scripts/write-handoff.sh:178` — protocol 1.1 writer — adds `attend_resume` when `Z_HARNESS_ATTEND_RESUME=1`.
- `docs/schemas/handoff.schema.json:69` — `attend_resume` schema — optional object, all fields minLength 1.
<!-- AUTO-END: entry-points -->

## Gotchas

- `/z-attend` does not set `Z_HARNESS_NO_ASK=halt`; the user is present, so substantive gates surface inline.
- `attend-state.json` is attend-specific; it is not `overnight-state.json`.
- The chain runner's state-write stdin form (`-`) avoids argv/env size limits for large state payloads.
- `new-run-id` excludes overnight runs internally; the attend caller separately excludes attend/overnight dirs in its before-set.
- `surface-shortcut.sh` exit code `1` means "surface the shortcut ask"; `2` is infra fallback-to-ask.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/attend.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
