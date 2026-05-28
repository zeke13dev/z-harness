# overnight-run

> Last updated: 2026-05-28
> Covers source: commands/z-overnight.md, scripts/run-status.sh, scripts/normalize-task-state.sh, scripts/overnight-preflight.sh, scripts/config.py

## Overview

`/z-overnight` runs a linear pipeline of z-harness sub-commands end-to-end with no interactive gates. AskUserQuestion callsites that are instrumented for overnight mode convert to halt events when `Z_HARNESS_NO_ASK=halt` is set; everything else continues. At the end of each run (complete, halted, or errored) a `MORNING_REPORT.md` is written and a push-notification fires.

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
2. **Hard halt** — a non-bypassable condition: slug collision (PLAN.md already exists for first plan step), lock corruption, or state file corruption. These are never converted to halt events by the allowlist — they stop the chain before the lock is even acquired.

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
