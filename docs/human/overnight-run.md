# overnight-run

> Last updated: 2026-05-28
> Covers source: commands/z-overnight.md, scripts/run-status.sh, scripts/normalize-task-state.sh, scripts/overnight-preflight.sh, scripts/config.py

## Overview

`/z-overnight` runs a linear pipeline of z-harness sub-commands end-to-end with no interactive gates. AskUserQuestion callsites that are instrumented for overnight mode convert to halt events when `Z_HARNESS_NO_ASK=halt` is set; everything else continues. At the end of each run (complete, halted, or errored) a `MORNING_REPORT.md` is written and a push-notification fires.

The overnight gate system lives in `scripts/config.py` and handles three paths when `Z_HARNESS_NO_ASK=halt` is active: (a) allowlist hit → emit `overnight_decision` envelope and auto-proceed; (b) registered question not in allowlist → emit `askuser_halted` and halt; (c) unregistered question → emit `unknown_ask_blocked` and halt. A separate `check-no-ask` subcommand in `config.py` serves non-resolver gate callsites that want a simple halt/proceed answer without running the full resolver.

---

## Invocation

```
/z-overnight <chain> [task-description]
/z-overnight preset:<name> [task-description]
/z-overnight resume <RUN_ID>
```

### Chain form

`<chain>` is a comma-separated or arrow-separated list of sub-command names (without the `/z-` prefix):

```
/z-overnight plan,test,implement-all,review-all  my feature description
/z-overnight plan → test → implement-all          my feature description
```

Supported step names: `plan`, `test`, `implement-all`, `review-all`, `research`.

### Preset form

```
/z-overnight preset:full-build     "add rate limit middleware"
/z-overnight preset:research-build "refactor logging layer"
/z-overnight preset:quick-build    "fix null pointer in auth"
```

| Preset | Expands to |
|--------|-----------|
| `full-build` | `plan,test,implement-all,review-all` |
| `research-build` | `research,plan,test,implement-all,review-all` |
| `quick-build` | `plan,implement-all` |

### Resume form

```
/z-overnight resume 20260528T220000Z-overnight-my-slug
```

Picks up at the first step whose status is not `complete`. Does a HEAD SHA check against the last completed step's `head_sha_after` — mismatch surfaces a CRITICAL warning but proceeds.

---

## Preflight collision check

Run by `scripts/overnight-preflight.sh check-collisions` in Phase 0 (SPEC C13), **before** lock acquisition and **before** `Z_HARNESS_NO_ASK` is set.

**v1 rule (broadened):** if the first step in the chain is `plan` **or** `research` AND `$BASE/PLAN.md` already exists → emit `slug_collision_halt` event and exit nonzero. This catches both `plan`-led chains and `research`-led chains (e.g. `research-build` preset) where a PLAN.md from a prior run would conflict.

Chains that do not start with `plan` or `research` (e.g. `implement-all,review-all`) pass the check even if PLAN.md exists.

---

## Overnight gate system (config.py)

The gate logic lives entirely in `scripts/config.py`. Key constants and functions:

| Symbol | Kind | Purpose |
|--------|------|---------|
| `OVERNIGHT_AUTODECIDE_QIDS_DEFAULT` | `const` | Default allowlist: `{workflow.slug_confirm: recommend_derived, workflow.audit_to_amend: amend}` |
| `_apply_overnight_overrides` | `fn` | Post-processes the resolver envelope when `Z_HARNESS_NO_ASK=halt`; routes to allowlist hit, halt, or no-op |
| `cmd_check_no_ask` | `fn` | `check-no-ask --question-id <id>`: lightweight halt/proceed answer for non-resolver gate callsites |
| `_parse_overnight_allowlist` | `fn` | Parses `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` (JSON object); merges over `OVERNIGHT_AUTODECIDE_QIDS_DEFAULT` |

The resolver (`cmd_resolve_question`) uses a 4-layer config stack (defaults → global `~/.config/z-harness/config.toml` → repo `.z-harness/config.toml` → env vars) plus memory-based routing preferences read from `docs/llm/*.json`. The overnight override layer sits on top of the resolver and fires only when `Z_HARNESS_NO_ASK=halt`.

---

## Allowlist customization

By default, two AskUserQuestion routing decisions are resolved automatically by the overnight allowlist:

| question_id | Default chosen value | Effect |
|-------------|---------------------|--------|
| `workflow.slug_confirm` | `recommend_derived` | Pre-selects the derived slug (no blocking prompt) |
| `workflow.audit_to_amend` | `amend` | Auto-proceeds as amend after any audit phase |

Override the default allowlist at runtime with `Z_HARNESS_OVERNIGHT_AUTODECIDE`. The value is a JSON object mapping `question_id` to a valid choice string:

```bash
export Z_HARNESS_OVERNIGHT_AUTODECIDE='{"workflow.slug_confirm":"auto_accept","workflow.audit_to_amend":"stop"}'
/z-overnight preset:full-build "my task"
```

The env JSON is **merged over** (not replaced by) the defaults. To keep a default entry, omit it from the override; to change it, supply a new value; no mechanism exists to remove a default entry in v1.

---

## Env-var reference

All `Z_HARNESS_OVERNIGHT_*` env vars recognized by `/z-overnight` and supporting scripts:

| Env var | Type | Default | Purpose |
|---------|------|---------|---------|
| `Z_HARNESS_OVERNIGHT_AUTODECIDE` | JSON string | `{}` | Override map merged on top of `OVERNIGHT_AUTODECIDE_QIDS_DEFAULT`; see Allowlist customization above |
| `Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE` | JSON string | (computed) | Internal: merged allowlist exported by the orchestrator before invoking sub-skills; do not set manually |
| `Z_HARNESS_OVERNIGHT_RUN_ID` | string | (computed) | Internal: identifies the current overnight run; exported for sub-skills and log-event.sh calls |
| `Z_HARNESS_OVERNIGHT_LOCK_STALE_S` | integer | `7200` | Seconds after which a lock heartbeat is considered stale and takeover is allowed (default 2 h, accommodating long /z-implement-all runs) |
| `Z_HARNESS_OVERNIGHT_AUTO_COMPACT` | `0` \| `1` | `0` | When `1`, emit a `compact_recommended` log event after each completed step as a hint to compact context |
| `Z_HARNESS_NO_ASK` | `halt` \| unset | unset | Instructs instrumented callsites to convert `ask` results to halt events; set/unset exclusively around Skill-tool calls by the orchestrator |

---

## Resume

Resume re-enters the chain at the first step whose status is not `complete`. To resume:

1. Find the `RUN_ID` from a previous `/z-overnight` run. It appears in the MORNING_REPORT terminal summary:
   ```
   /z-overnight halt: my-slug (20260528T220000Z-overnight-my-slug)
   ```
2. Run:
   ```
   /z-overnight resume 20260528T220000Z-overnight-my-slug
   ```
3. The orchestrator validates the state file, warns on HEAD SHA mismatch, re-acquires the lock, and continues from the first non-`complete` step.

**Already-complete guard:** if the named run is already `complete`, the orchestrator surfaces an `AskUserQuestion` acknowledgement ("nothing to resume") and exits cleanly.

---

## Halt semantics

A halt can have two sources:

1. **Registered callsite halt** — one of the 12 instrumented AskUserQuestion callsites (9 existing resolver sites + 3 retrofitted gates) detected `Z_HARNESS_NO_ASK=halt` and returned `result: "halt"` instead of blocking. The step status is `halt` in `overnight-state.json`.
2. **Hard halt** — a non-bypassable condition: slug collision (PLAN.md already exists for a chain whose first step is `plan` or `research`), lock corruption, or state file corruption. These are never converted to halt events by the allowlist — they stop the chain before the lock is even acquired.

When the chain halts, the orchestrator:
- Writes `MORNING_REPORT.md` with the halt reason and the `Recommended next` section.
- Releases the lock.
- Push-notifies via `should-notify --event approval`.

After addressing the halt question, resume with:
```
/z-overnight resume <RUN_ID>
```

### `would_have_asked` restriction

The halt envelope written to events.jsonl contains a `would_have_asked` field. This field captures **only** `{default, choices}` — never the question text, header, description, or any per-callsite human-readable string. This prevents accidental leakage of stack traces, paths, or other contextual data into the repo-tracked events.jsonl.

---

## Event vocabulary

Events emitted to `events.jsonl` during an overnight run. Each row: **kind** — when emitted — key payload fields.

### Orchestrator lifecycle

| Kind | When emitted | Key payload fields |
|------|-------------|-------------------|
| `overnight_start` | Run begins (after lock acquired) | `chain`, `preset_used`, `slug`, `head_sha_at_start` |
| `overnight_step_start` | Before each step's Skill call | `step`, `position`, `total_steps` |
| `overnight_step_complete` | Step classified as clean | `step`, `position`, `run_id`, `wall_ms` |
| `overnight_step_halt` | Step classified as halted | `step`, `position`, `run_id`, `halt_reason`, `halt_event` |
| `overnight_step_error` | Step classified as errored | `step`, `position`, `run_id`, `error_event` |
| `overnight_decision` | Allowlist auto-decided a question | `question_id`, `chosen`, `source`, `strength`, `rule_id`, `sources[]` |
| `overnight_end` | Chain terminates (any status) | `status`, `total_steps`, `completed_steps`, `wall_ms` |
| `overnight_step_abandoned` | User invokes `/z-overnight abandon` during resume | `step`, `position`, `run_id`, `reason` |
| `compact_recommended` | `Z_HARNESS_OVERNIGHT_AUTO_COMPACT=1` and a step completed | `cumulative_chars_estimate` |

### Per-command halt events

Each per-command halt event has the same payload shape: `{reason, question_id, rule_id}`.

| Kind | Command / skill | `question_id` when emitted |
|------|----------------|--------------------------|
| `fix_halt` | `/z-fix` | `workflow.slug_confirm` |
| `audit_halt` | `/z-audit-plan` | `workflow.audit_to_amend` |
| `plan_style_halt` | `/z-audit-plan-style` | `workflow.audit_to_amend` |
| `uplift_halt` | `/z-uplift` | `workflow.slug_confirm` |
| `debug_halt` | `skills/z-debug` | `workflow.slug_confirm` |
| `light_halt` | `skills/z-plan-light` | `workflow.slug_confirm` |
| `map_halt` | `skills/z-map` | `workflow.slug_confirm` |
| `brainstorm_halt` | `skills/z-brainstorm` | `workflow.slug_confirm` |
| `plan_halt` | `/z-plan` | `workflow.slug_confirm` (Phase 1) or `workflow.plan_decisions_approval` (Phase 2.5) |
| `review_halt` | `/z-review-all` | `workflow.review_all_proceed` (Phase 3.7) |
| `implement_all_halt` | `/z-implement-all` (reserved) | `workflow.implement_all_proceed` — reserved kind recognized by `run-status.sh`; v1 uses `task_halt` per-task instead of a single batch-level halt event. If a future batch-level halt is added, it will use this kind. |

### Hard halt events (pre-lock, non-bypassable)

| Kind | When emitted | Key payload fields |
|------|-------------|-------------------|
| `slug_collision_halt` | Phase 0 preflight — first step is `plan` or `research` and `$BASE/PLAN.md` already exists | `slug`, `conflicting_artifact`, `chain`, `first_step` |
| `overnight_lock_corrupt` | Lock file parse fails (JSON invalid) | `path`, `parse_error` |
| `state_corrupt` | `overnight-state.json` fails to parse on resume | `path`, `error` |
| `head_sha_mismatch_at_resume` | HEAD SHA differs from `head_sha_after` of last completed step (warn-and-continue) | `expected`, `actual`, `last_step` |

### Instrumented callsite halt events (config.py)

| Kind | When emitted | Key payload fields |
|------|-------------|-------------------|
| `askuser_halted` | `Z_HARNESS_NO_ASK=halt`, question_id in registered set but NOT in allowlist — emitted by `_apply_overnight_overrides` | `question_id`, `would_have_asked` (`{default, choices}` only) |
| `unknown_ask_blocked` | `Z_HARNESS_NO_ASK=halt`, question_id NOT in registered set — emitted by `cmd_check_no_ask` | `question_id`, `callsite_hint` |
| `config_conflict` | `Z_HARNESS_ASK_ALL=1` AND `Z_HARNESS_NO_ASK=halt` detected simultaneously | `conflict` (string description), `question_id` |

### Infrastructure error events

| Kind | When emitted | Key payload fields |
|------|-------------|-------------------|
| `skill_tool_failure` | Skill-tool call raises or times out | `step`, `position`, `message` |
| `run_id_ambiguous` | New-archive-dir detection (C14) finds 0 or >1 new dirs after a Skill call | `step`, `position`, `reason`, `new` (list of new dirs) |

---

## MORNING_REPORT layout

Written to `z-harness/<slug>/MORNING_REPORT.md` (canonical: `z-harness/plans/<slug>/MORNING_REPORT.md`) and overwritten on every chain run.

```markdown
# MORNING_REPORT — <slug> — <RUN_ID>

## Chain summary
- Chain: <step1 → step2 → ...>
- Started: <ISO timestamp>
- Ended: <ISO timestamp or "in progress">
- Status: <complete | halted-at-step-N | errored-at-step-N>
- HEAD at start / end: <sha> / <sha>

## Phase results
| # | Step | RUN_ID | Wall (ms) | Status | Terminal event |
|---|------|--------|-----------|--------|---------------|
| 1 | plan | ...    | 840000    | complete | run_end    |
| 2 | test | ...    | 12000     | halt     | task_halt(reason=no_ask_blocked) |

## Unilateral decisions
| Step | question_id | chosen | rule_id | source | strength |
|------|-------------|--------|---------|--------|----------|
| plan | workflow.slug_confirm | recommend_derived | workflow.slug_confirm:recommend_derived | overnight_allowlist | policy |

## Test outcomes
See z-harness/<slug>/archive/<sub-run-id>/events.jsonl for test results.

## Recommended next
Resume with: /z-overnight resume <RUN_ID> after answering the halt question above.
git diff --stat headline: 3 files changed, 47 insertions(+), 2 deletions(-)
```

The report is a pure function of `overnight-state.json` — all timing, diff stat, and step data come from the state file, which is updated at every step terminal transition (complete, halt, or error).

---

## v1 known limitations

### Fail-OPEN for unregistered AskUserQuestion callsites (SPEC C11)

> **v1 known limit (fail-OPEN for unregistered callsites):** Only 12 AskUserQuestion callsites participate in halt-from-ask (9 existing resolver sites + 3 new gates). Sub-commands that call `AskUserQuestion` outside this set will block the conversation until you respond, even with `Z_HARNESS_NO_ASK=halt`. `scripts/lint-askuser.sh` is documentation and audit tooling — it is NOT runtime enforcement and cannot convert a non-instrumented AskUser into a halt. Run `scripts/lint-askuser.sh --strict` before launching a long chain and instrument any callsites flagged as unregistered if they are on your chain's hot path. v2 will pursue runtime enforcement (e.g., centralized AskUser wrapper at the driver layer).

The 12 instrumented callsites are:
- **workflow.slug_confirm** (7): `commands/z-plan.md`, `commands/z-fix.md`, `commands/z-uplift.md`, `skills/z-debug/SKILL.md`, `skills/z-brainstorm/SKILL.md`, `skills/z-map/SKILL.md`, `skills/z-plan-light/SKILL.md`
- **workflow.audit_to_amend** (2): `commands/z-audit-plan.md`, `commands/z-audit-plan-style.md`
- **workflow.implement_all_proceed** (1): `/z-implement-all` halt-resolution gate
- **workflow.review_all_proceed** (1): `/z-review-all` Phase 3.7 proceed gate
- **workflow.plan_decisions_approval** (1): `/z-plan` Phase 2.5 decisions-doc approval gate

### Linear chains only

DAG / parallel-cluster overnight runs are deferred to v2.

### No retry on Skill-tool failure

If a sub-skill's Skill-tool invocation itself fails (exception, timeout), the step status is set to `error`. No automatic retry is attempted. Resume via `/z-overnight resume <RUN_ID>` after addressing the underlying issue.

### Skill-tool composition over subprocess

Context accumulation risk for step 4+ on large implementations. Deferred to v2.
