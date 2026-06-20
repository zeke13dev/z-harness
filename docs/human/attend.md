# attend

> Last updated: 2026-06-19
> Covers source: commands/z-attend.md, scripts/chain-runner.sh, scripts/config.py (resolve-halt-category + HALT_CATEGORY_ENUM), scripts/lint-halt-categories.sh, scripts/surface-shortcut.sh, scripts/write-handoff.sh, docs/schemas/handoff.schema.json

## Overview

`/z-attend` is the **middle gear** between `/z-overnight` (fully unattended; blocks on every significant question) and manual one-command-at-a-time operation. You are present at the keyboard, but you do not want to answer a dozen mechanical "proceed?" prompts during a long chain.

`/z-attend` runs a configurable command chain (default: plan, audit, test, implement-all, review-all), auto-advancing past mechanical gates while surfacing only the four categories of gate that genuinely require a human decision. At declared context boundaries it writes a resume token to `handoff.json` and asks you to run `/clear`, then re-enter via `/z-attend resume <RUN>`.

---

## The middle-gear model

| Mode | Gate handling | Context boundaries |
|------|--------------|--------------------|
| `/z-overnight` | Converts all gates to halt events; you answer later | No `/clear` — accumulates context for the whole chain |
| **`/z-attend`** | Auto-proceeds mechanical gates; asks inline for the four substantive categories | Yields for `/clear` at declared boundaries (`plan`, `implement-all` complete) |
| manual | Every gate blocked; you invoke each command separately | You decide when to `/clear` |

`/z-attend` **does not set `Z_HARNESS_NO_ASK=halt`**. Because you are present, gates surface inline rather than being converted to halt events. The separation of duties is:
- `scripts/chain-runner.sh` owns sequencing, state persistence, cursor computation, and sub-run identification (mechanics-only — no gate policy inside the runner).
- `commands/z-attend.md` owns the gate-category posture and the yield protocol.

---

## Invocation

```
/z-attend [chain-preset] [task-description]
/z-attend resume <RUN>
/z-attend status <RUN>
```

**Default preset `attend-full`** = `plan, audit, test, implement-all, review-all`

This is the overnight `full-build` chain with an `audit` step inserted after `plan` — the extra step is what makes attend "attended": the audit result is a human-reviewed gate before implementation starts.

Other presets (`full-build`, `quick-build`, `research-build`) are also accepted. If the first token is not a known preset, the whole argument is taken as the `task-description` and `attend-full` is used.

---

## The four halt categories

Every instrumented `AskUserQuestion` gate in the chain commands is tagged with a `halt_category` in `scripts/config.py`. When a gate fires during a step, `/z-attend` resolves the category and acts:

| Category | What it means | Action |
|----------|--------------|--------|
| `mechanical_proceed` | A routine "shall we proceed?" prompt with an obvious answer | **Auto-answer** with the question's `skill_default`. No user prompt. Logged as `attend_gate_auto`. |
| `decision` | A non-obvious architectural or scope choice | **Surface inline `AskUserQuestion`**. You choose. |
| `risk` | A potential correctness or safety concern requiring awareness | **Surface inline `AskUserQuestion`**. You choose. |
| `shortcut` | A deliberate trade-off: the chain is taking a looser path and declining a more robust alternative | **Surface inline `AskUserQuestion`**. You choose to accept or take the robust path. |
| `archiving` | A gate about what to keep vs. discard | **Surface inline `AskUserQuestion`**. You choose. |
| *untagged / unknown* | No `halt_category` tag in `config.py` for this question id | **`ask` (fail-safe)**. Always surface as an inline question — never auto-skip. |

**HARD INVARIANT (Invariant 1 — fail-safe):** an untagged gate resolves to `ask`, **never** `mechanical_proceed`. Mis-surfacing requires an explicit wrong tag, not an omission. `config.py resolve-halt-category` already encodes this (unknown question id — `ask`); the command relies on it rather than guessing.

### Resolving a category at runtime

```bash
HALT_CATEGORY="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" \
  resolve-halt-category "<question_id>")"
# -> one of: decision | risk | shortcut | archiving | mechanical_proceed | ask
```

---

## The yield /clear resume loop

At declared context boundaries the chain **yields**: it writes a hardened resume token to `handoff.json`, prints `/clear then /z-attend resume <RUN>`, and exits.

### When does a yield fire?

Two triggers:

1. **`yield_after` boundary** — `chain-runner.sh` marks two steps as `yield_after=true`: `plan` and `implement-all`. After either of these completes successfully, the chain yields. These are the two points where context is largest and clearing is most beneficial.

2. **`context_pressure`** — if the sub-run produced by a step writes its own `handoff.json` with `status == "context_pressure"` (its own mid-run compaction path), the attend chain yields even if that step was not a declared boundary.

### What the token contains (handoff.json protocol 1.1)

`write-handoff.sh` writes `handoff.json` in the plan directory. For attend yields it bumps `protocol_version` to `"1.1"` and adds an `attend_resume` sub-object with five fields:

| Field | Purpose |
|-------|---------|
| `expected_head_sha` | Git HEAD at yield time; resume halts on mismatch (the tree moved) |
| `expected_phase` | Chain step to re-enter (the first non-complete step after the yield) |
| `done_set_hash` | Hash of completed tasks in TASKS.md at yield time |
| `dirty_state_fingerprint` | `git status --porcelain` digest at yield time |
| `session_id` | Session id at yield time (detects "you did not run `/clear`") |

All five must be non-empty or `write-handoff.sh` exits non-zero and names the missing field(s). The command guards all five explicitly before calling `write-handoff.sh`.

### How to resume

1. Note the `RUN` id printed at the yield:
   ```
   /clear then /z-attend resume 20260612T143020Z-attend-my-feature
   ```
2. Run `/clear` (clears the Claude context window — this is the whole point).
3. Run `/z-attend resume 20260612T143020Z-attend-my-feature`.

The resume path validates the predicate before re-entering the chain.

---

## Resume predicate safety (Phase 0R)

On resume, four validations run in order:

### R1 — HEAD SHA (HARD HALT)

If `expected_head_sha` differs from current HEAD, the tree moved since the yield. Resuming on a different base is unsafe. The command **halts** and asks:

- `re-plan` — abort this resume; the user re-runs `/z-plan`/the chain against the new base (safe default).
- `accept-new-base` — explicitly accept the moved base and continue at your own risk (rewrites `attend_resume.expected_head_sha` to the current HEAD so subsequent resumes are consistent, then falls through to R2).

On `re-plan` (the safe default): print the remediation and **exit cleanly**. Do not re-enter.

### R2 — Phase/cursor agreement (HARD HALT)

The state file's cursor (durable backend) and the token's `expected_phase` must name the same step. Disagreement means the state file and token are out of sync (corrupted or hand-edited artifact). The command **halts** and asks:

- `Abort (inspect manually)` — safe default; exit cleanly.
- `Continue from the state-file cursor anyway` — the state file wins.

### R3 — Session id (WARN, allow continue)

If the session id is unchanged since the yield, you very likely did **not** run `/clear`. The command warns hard and asks:

- `Abort and run /clear first` — you go clear and come back.
- `Continue without clearing` — proceed (old context remains, defeating the yield's purpose).

### R4 — Done-set / dirty-tree drift (WARN, allow continue)

A parallel session may have advanced tasks or the working tree may have changed since the yield. On drift, the command warns and asks `Continue` / `Abort`. This is a soft signal (not a hard block).

### Summary of predicate responses

| Predicate | Mismatch severity | Default action |
|-----------|-----------------|----------------|
| HEAD SHA | HARD HALT | `re-plan` (abort resume) |
| Phase/cursor | HARD HALT | `Abort` |
| Session id | WARN | `Abort and run /clear first` |
| Done-set / dirty-tree | WARN | `Continue` |

---

## Preflight gate lint

Before the first step, `/z-attend` runs `lint-halt-categories.sh --check-chain <preset>` to list any `ask_user` gates reachable on the chain that have **no** `category=` token. These gates will surface as inline `ask` questions at runtime (fail-safe Invariant 1). The lint output is printed verbatim as an advisory nudge — the chain proceeds regardless. It is not blocking.

```bash
scripts/lint-halt-categories.sh --check-chain attend-full
```

`lint-halt-categories.sh` uses `chain-runner.sh` to resolve the preset when available; it falls back to an inline preset map if `chain-runner.sh` is absent.

---

## Status (Phase 0S)

```
/z-attend status <RUN>
```

Read-only progress report. Delegates classification to `run-status.sh` and mutates nothing. Shows the overall classification (`clean` / `halted` / `errored` / `unknown`), the chain and per-step statuses, which step the cursor points at, and the last event.

---

## State file

The state file lives at `$BASE/archive/$RUN_ID/attend-state.json`. This is **not** `overnight-state.json` — attend keeps its own run-scoped file (the state-file path is a parameter to `chain-runner.sh`, never a hardcoded constant).

---

## chain-runner.sh subcommands

`chain-runner.sh` is a mechanics-only primitive shared by both `/z-attend` and `/z-overnight`. It provides:

| Subcommand | Purpose |
|------------|---------|
| `steps <preset>` | Emit `name:yield_after` per line; exit 2 on unknown preset |
| `state-init <file> <csv> ...` | Write initial run state (all steps queued) |
| `state-read <file>` | Print state JSON to stdout |
| `state-write <file> <json\|->` | Flock-guarded atomic replace; `-` reads from stdin for unbounded payloads |
| `cursor <file>` | Index of first non-complete step; `len(steps)` when all complete |
| `new-run-id <unused> <before-set> <archive-dir>` | C14 set-difference; excludes `*-overnight-*` from both sides |

The `state-write` stdin form (`-`) exists specifically to avoid the OS argv/env size ceiling for large overnight states.

---

## Event vocabulary

| Event | When |
|-------|------|
| `attend_start` | Run begins |
| `attend_step_start` | Before a step's Skill call |
| `attend_step_complete` | Step classified clean |
| `attend_step_halt` | Step classified halted |
| `attend_step_error` | Step classified errored |
| `attend_gate_auto` | `mechanical_proceed` gate auto-answered |
| `attend_gate_asked` | Substantive gate surfaced to user |
| `attend_risk_halt` | Risk-category step outcome (reviewer blocker / audit reject) |
| `chain_yield` | Boundary yield written; chain exiting for `/clear` |
| `attend_resumed` | Re-entry after a successful resume |
| `attend_resume_halt` | Resume blocked (HEAD mismatch or phase disagreement) |
| `attend_resume_warn` | Resume warning (session unchanged or predicate drift) |
| `attend_end` | Chain terminates (any status) |
| `shortcut_proposed` | Audit-skip shortcut surfaced to user |

---

## Key entry points

<!-- AUTO-START: entry-points -->
- `commands/z-attend.md:11` — `middle-gear model` — Positioned between /z-overnight and manual operation; auto-advances mechanical gates, asks inline on four categories, yields for /clear at declared boundaries
- `commands/z-attend.md:44` — `category posture` — Category table: mechanical_proceed->auto, decision/risk/shortcut/archiving->ask inline, untagged->ask (Invariant 1 fail-safe)
- `commands/z-attend.md:69` — `Phase 0` — Argument parsing: resume/status sub-flows dispatch to Phase 0R/0S; default preset attend-full
- `commands/z-attend.md:270` — `Phase 1 Setup` — New-run: slug derivation, RUN_ID, preflight lint, state-init, attend_start event
- `commands/z-attend.md:323` — `Phase 2 audit-skip shortcut` — Once pre-loop: surface-shortcut.sh exit 1=ask, exit 0=no-op, exit 2=infra-fallback-to-ask
- `commands/z-attend.md:353` — `Phase 2 per-step loop` — Per-step: skip-complete, mark-running, archive snapshot, Skill dispatch, gate handling, sub-run classification, boundary yield
- `commands/z-attend.md:493` — `Phase 2 boundary yield (Step 2.9)` — Two triggers: yield_after boundary or context_pressure; writes protocol-1.1 handoff.json
- `commands/z-attend.md:584` — `Phase 3 terminal handling` — Determine overall status, update state, log attend_end, print summary
- `scripts/chain-runner.sh:76` — `_expand_preset` — Four presets: full-build, research-build, quick-build, attend-full
- `scripts/chain-runner.sh:86` — `_yield_after` — yield_after=true only for plan and implement-all
- `scripts/chain-runner.sh:128` — `_atomic_write` — flock-guarded atomic state write via Python fcntl.flock + tmp+rename; both argv and stdin forms
- `scripts/config.py:292` — `HALT_CATEGORY_ENUM` — {decision, risk, shortcut, archiving, mechanical_proceed} — startup guard validates every registered question_id has a member of this enum
- `scripts/config.py:1598` — `cmd_resolve_halt_category` — resolve-halt-category CLI: prints halt_category for a question_id or "ask" for unknown
- `scripts/lint-halt-categories.sh:161` — `_check_chain` — --check-chain <preset>: lists uncategorized ask_user gates reachable on that chain; advisory, not blocking
- `scripts/surface-shortcut.sh:1` — `surface-shortcut.sh` — Emits shortcut_proposed event; exit 1=surface-ask, exit 0=no-op, exit 2=infra error
- `scripts/write-handoff.sh:1` — `write-handoff.sh` — Writes handoff.json; Z_HARNESS_ATTEND_RESUME=1 bumps to protocol 1.1 and populates attend_resume predicate; status always 'clean_break'
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `config` — `scripts/config.py` owns the gate registry (`HALT_CATEGORY_ENUM`) and `resolve-halt-category`; attend is the primary consumer of the halt-category metadata
- `commands` — `/z-attend` delegates each step to a z-harness sub-skill via the Skill tool; it is itself a command in the commands concept
- `scripts` — uses chain-runner.sh (sequencing/state), log-event.sh, write-handoff.sh (yield token), surface-shortcut.sh (shortcut gate signaling), lint-halt-categories.sh (preflight), session-helpers.sh (done_set_hash), active-plan-registry.py (session-id)
- `session-handoff` — the yield token is a protocol-1.1 handoff.json produced by write-handoff.sh; the schema is defined in docs/schemas/handoff.schema.json
- `overnight-run` — `/z-overnight` is the fully-unattended sibling; attend and overnight both use chain-runner.sh for sequencing but diverge in gate policy (attend=inline category ask, overnight=halt-only)

## Edge cases / gotchas

- **No `Z_HARNESS_NO_ASK=halt`** — attend never sets this env var; all gates surface inline
- **Preflight is advisory, not blocking** — uncategorized gates produce a warning and still run (ask inline per Invariant 1); the chain is not aborted
- **Boundary yield is declared, not detected** — only `plan` and `implement-all` have `yield_after=true` in chain-runner.sh; other step completions do not yield unless context_pressure fires
- **All five attend env vars must be non-empty** before `write-handoff.sh` is called; both z-attend.md and write-handoff.sh guard this explicitly and report which var is missing
- **Resume validates handoff.json's attend_resume, not SESSION.md** — the predicate is in the immutable token; hand-editing SESSION.md does not affect resume safety
- **HEAD SHA mismatch on resume is a hard halt** (unlike overnight where it is warn-and-continue)
- **State file is attend-scoped** (`attend-state.json`), not overnight-state.json; the state-file path is always a parameter to chain-runner.sh
- **Skill-tool failure stops the chain with no retry** — the user resumes via `/z-attend resume <RUN>` after fixing
- **`context_pressure` from a sub-run triggers yield even on non-boundary steps** — the sub-run's own handoff status is checked after each step
- **new-run-id attend-dir exclusion is split**: chain-runner.sh's `new-run-id` filters `*-overnight-*` from both sides; the caller (z-attend.md Step 2.3) separately excludes `*-attend-*` and `*-overnight-*` when building the before-set snapshot — the attend-dir exclusion from the after-set is NOT done by chain-runner.sh
- **write-handoff.sh status is always `clean_break`** for attend yields regardless of which step triggered the yield
- **HALT_CATEGORY_ENUM and cmd_resolve_halt_category line numbers shift** as config.py grows; always locate them with grep rather than relying on cached line numbers
- **state-write accepts `-` for large state payloads** — use stdin form when the JSON payload could exceed OS argv/env size limits (relevant for overnight with many tasks)

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/attend.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
