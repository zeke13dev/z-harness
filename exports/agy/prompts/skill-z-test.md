---
description: Semantic test-case planner. Reads SPEC.md + PLAN.md + TASKS.md for an existing plan, risk-ranks the tasks, drafts non-trivial test cases that catch real semantic bugs (sign errors, schema/feature mismatches, time-window off-by-one, unit confusion,...
role: skill
---

You are running **z-harness `/z-test`** — the semantic test-case planner. This is an **optional planning-time step** between `/z-plan` and `/z-implement-all`. It does NOT write or run any test code. It produces a structured `TESTS.md` artifact that the implementer subagent reads alongside TASKS.md, so tests get implemented in the same diff as the code they exercise.

## Setup

### Phase 0 — Slug discovery + plan sanity check

Same logic as `/z-implement-all` Phase 0:

1. Enumerate `$Z_HARNESS_PLAN_DIR/` subdirs containing a `TASKS.md`; also check legacy flat `z-harness/TASKS.md`.
2. If `--slug <slug>` arg → use it.
3. Single candidate → use it; export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
4. Multiple → `AskUserQuestion` to pick.
5. Zero → tell user "no plan found — run `/z-plan` first"; abort.

Set `$BASE = $Z_HARNESS_PLAN_DIR` (or `z-harness` for legacy).

**Require SPEC.md + PLAN.md + TASKS.md.** Abort with "incomplete plan; run /z-plan to completion first" if any of the three is missing.

**Implementation-underway warning.** If TASKS.md already has any `[x]` rows, `AskUserQuestion`:
- "Continue — add tests that will retroactively constrain in-flight tasks"
- "Abort — wait until implementation is complete, then run /z-test after /z-review-all"

Pick run id `RRUN=$(date -u +%Y%m%dT%H%M%SZ)-test`. `mkdir -p $BASE/archive/$RRUN/transcripts`.

**Version stamp + log run start:**
```bash
VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
START_PAYLOAD="$(python3 -c '
import json, sys
v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
print(json.dumps(v))
' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" test_plan_start "$START_PAYLOAD"
```

Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).

## Phase 1 — Risk-rank the plan

Read `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`.

For each task in TASKS.md, score risk on three axes:

- **Domain criticality.** Does this task touch money, ordering, position sizing, signal generation, fills, P&L attribution, or anything called out as load-bearing in SPEC.md? Trading-system specifics: notional, contract counts, fill direction, slippage application, time-zone-aware bar boundaries, feature alignment between strategy and pipeline.
- **Surface area.** Count files in the task's `Files:` block; count acceptance criteria; flag presence of `**DANGER:**` / `**INVARIANT:**` / `**MUST:**` tags in SPEC.md for any file the task touches.
- **Test-gap signal.** Acceptance criteria worded as "behavior X" without a numeric / type-shape / observable check are the worst case — the implementer can pass them without writing anything that proves correctness.

Output a ranked list (high → low):
- **High risk** → mandatory test coverage required.
- **Medium risk** → recommended.
- **Low risk** → optional.

Also extract from SPEC.md every line of these shapes and treat each as a candidate test seed:
- `**INVARIANT:**`, `**MUST:**`, `**MUST NOT:**`, `**DANGER:**`
- Numeric/quantitative assertions ("must be ≤ X", "exactly N", "monotone in Y")
- Equality/identity claims about cross-module contracts ("strategy reads field X written by Y")

**Brief user input.** Before drafting tests, `AskUserQuestion` (free-text):
- "What specific bug classes worry you most for this plan?"

Example user concerns: "notional flow direction in the new strategy", "feature schema alignment between materializer and trader", "rolling-window inclusivity at bar boundaries". Each user concern becomes an explicit test target in Phase 2 (`seed: user-concern`).

Save the ranked list + invariants + user concerns to `$BASE/archive/$RRUN/phase1-risk.md`.

## Phase 2 — Draft initial test cases (orchestrator main thread)

For each high-risk task and each spec invariant and each user concern, draft a candidate test entry:

```
- id: TEST-001
  task: T007                # link to TASKS.md entry (null if cross-task)
  invariant: <verbatim quote from SPEC.md or "derived from PLAN.md decision <name>">
  test_name: <short_snake_case>
  target_file: <abs path where the test should live, in repo-native location>
  failure_class: <one-line: what real bug would this catch?>
  setup: <fixture/data; reference existing test utilities if any>
  assertion: <concrete observable check — numeric, type-shape, or invariant on output>
  seed: spec | plan | task-risk | user-concern
  mandatory: yes | no
```

**Focus categorically on non-trivial failure classes.** Trivial mechanical tests (assert the function returns, assert no exception is raised) are explicitly rejected — every entry must name the **failure class** it catches in domain terms. Use this checklist when drafting:

- **Sign/direction errors.** Notional sign, P&L sign, position-size sign, slippage application direction (paid vs received).
- **Schema/feature mismatches.** Strategy reads field `x` but pipeline writes `x'` — silent zero-fill or default-value bugs. Most insidious because the type checks pass.
- **Off-by-one in time / rolling windows.** Bar boundary inclusivity (`[t, t+1)` vs `(t, t+1]`), warmup-period truncation, look-ahead leakage.
- **Stale-data usage.** Reading a cached value that was supposed to be invalidated by an upstream event.
- **Cross-module contract drift.** Caller passes seconds, callee expects ms; caller passes contracts, callee expects notional; caller passes basis points, callee expects fractions.
- **Quantity/price unit confusion.** Cents vs dollars, contracts vs notional, bid vs mid vs ask.
- **State-machine invariants.** Forbidden transitions (`filled → pending`, `cancelled → fill`), idempotency violations (double-fill on retry).
- **Bounds.** Empty input, single-element input, sorted-vs-unsorted assumptions, NaN/None propagation, equal timestamps.

**Anti-rubber-stamp rule.** For each draft, also write internally "one reason this test might be useless" (matches the `/z-plan` push-back discipline). If you can't articulate why the test could be useless, you don't understand it well enough — sharpen the assertion before consulting.

Cap the orchestrator's initial draft at ~25 entries. If more candidates exist, prefer mandatory (high-risk + spec-invariant + user-concern) over optional.

Save the draft list to `$BASE/archive/$RRUN/phase2-drafts.md`.

## Phase 3 — Bundled cross-LLM consult (mode `test-cases`)

Spawn **both** consultants in parallel in a single message:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Test-cases consult (Gemini) for <slug>",
  prompt="MODE: test-cases\n\nSPEC.md (verbatim):\n<contents>\n\nPLAN.md (verbatim):\n<contents>\n\nTASKS.md (verbatim):\n<contents>\n\nMy draft test cases (Phase 2):\n<contents of phase2-drafts.md>\n\nUser-stated concerns:\n<from Phase 1 AskUserQuestion>\n\nSource files referenced by the drafts (read these for real types/signatures):\n<list of abs paths>\n\nAsk:\n1. For each draft test: is the assertion strong enough to catch a real bug, or a tautology? If weak, propose a stronger assertion (be concrete).\n2. Which SPEC invariants do not yet have a corresponding test? Propose entries.\n3. What dangerous bug classes specific to this codebase domain (trading: notional sign, fill-quantity sign, time-zone-aware bar boundaries, feature schema alignment between strategy and pipeline) are not covered by my drafts?\n4. Flag any draft that is mechanically trivial (asserts what the implementation already obviously does) and recommend dropping it.\n5. Identify any draft whose target_file is in the wrong place (test framework convention mismatch).\n\nReturn structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries Claude missed."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Test-cases consult (Codex) for <slug>",
  prompt="MODE: test-cases\n\n<same prompt body>"
)
```

Both transcripts archive themselves under `$BASE/archive/$RRUN/transcripts/`.

## Phase 4 — Synthesize

When both return:

1. **Merge** Claude's drafts + Gemini's additions + Codex's additions. Dedupe by `test_name` + `target_file`.
2. **Apply per-draft verdicts.** For each draft Claude wrote: if both LLMs said "drop, trivial" → drop. If both said "strengthen", apply the stronger assertion. If exactly one said drop → keep but flag for user.
3. **Apply additions.** For each NEW test entry an LLM proposed, run the same anti-rubber-stamp check ("one reason this test might be useless"). Drop pure rubber-stamps.
4. **Cross-LLM disagreement.** If Gemini and Codex disagree on whether a specific draft is meaningful, surface that disagreement to the user via Phase 5 `AskUserQuestion` — do NOT silently pick one side.

Track three counts for the Phase 8 finalize push-notify:
- `n_dropped_by_consult` — drafts both LLMs flagged as trivial
- `n_added_by_consult` — net new test entries from LLMs
- `n_strengthened` — drafts where assertion was upgraded based on LLM input

Save the synthesized list to `$BASE/archive/$RRUN/phase4-synthesis.md`.

## Phase 5 — Present + approve

Send `PushNotification` (if policy != `off`): "Test plan ready for review."

Present counts via `AskUserQuestion`:
- "<M> mandatory + <R> recommended + <O> optional tests drafted. Cross-LLM dropped <D> trivial drafts; added <A> coverage gaps."

Options:
- **Accept all** — write all entries into TESTS.md.
- **Accept mandatory + recommended only** — drop optional tier.
- **Edit subset** — orchestrator iterates each contested test (cross-LLM disagreement, or user-concern items) via per-test `AskUserQuestion`: keep / drop / modify (free-text).
- **Abandon** — log `test_plan_end` with `status: abandoned`; exit. No TESTS.md written.

**Fixture-scaffolding gate.** For any accepted test whose `setup:` field requires non-trivial new test infrastructure (a new fixture file, a new mock framework, a new test-data generation step), get separate explicit approval via `AskUserQuestion`. Same discipline as `/z-plan` shortcuts: building new test infra without buy-in is a scope expansion.

## Phase 6 — Write TESTS.md

Write `$BASE/TESTS.md`:

```markdown
# Tests for <slug>

**Run:** <RRUN>
**Status:** drafted (awaiting /z-implement-all)
**Plugin version:** <z_harness_version from setup>
**Cross-LLM consensus:** <agree | gemini-only-<N> | codex-only-<N> | user-overrode-<N>>
**Counts:** <M> mandatory, <R> recommended, <O> optional
**Cross-LLM delta:** dropped <D> trivial, added <A> coverage gaps, strengthened <S>

## TEST-001  (covers T007)
**Invariant:** <quote from SPEC.md or derivation>
**Failure class:** <one-line: what real bug this catches>
**Target file:** <abs path>
**Setup:** <fixtures, data — reference existing utilities by path>
**Assertion:** <concrete observable check>
**Seed:** spec
**Mandatory:** yes

## TEST-002  (covers T009)
...
```

Each TEST-NNN block must be parseable by the implementer subagent (it greps the file for `## TEST-NNN` to find its entry). Use stable IDs even if the user dropped some during Phase 5 — gaps in numbering are fine; renumbering would invalidate any cross-references.

No SPEC.md / PLAN.md changes. TESTS.md is its own artifact.

## Phase 7 — Cross-link into TASKS.md

For each task `Txxx` referenced by one or more TEST-NNN entries, append a line under that task's block in TASKS.md:

```
**Tests:** TEST-001, TEST-004  (see TESTS.md)
```

Placement: directly after the task's `Acceptance:` block, before any `**REMOTE_VERIFY:**` or `**DOCS:**` line.

This is the signal to the implementer subagent: when implementing this task, also implement the listed TEST-NNN entries from TESTS.md in the same diff. The implementer reads TESTS.md, grep-finds each `## TEST-NNN`, and produces the test code at the entry's `Target file:` path.

If a task already has a `**Tests:**` line from a prior `/z-test` invocation, **merge IDs** — never overwrite. Sort the merged list.

**Cross-task tests** (entries with `task: null`) are not linked into TASKS.md. They get implemented as part of `/z-review-all`'s final gate or as standalone follow-up tasks the user creates manually. Note this in the user-facing summary in Phase 8.

## Phase 8 — Finalize

1. Copy TESTS.md into `$BASE/archive/$RRUN/`.
2. Log:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" test_plan_end \
     "$(printf '{"status":"drafted","n_mandatory":%d,"n_recommended":%d,"n_optional":%d,"n_dropped_by_consult":%d,"n_added_by_consult":%d,"n_strengthened":%d,"n_cross_task":%d}' \
        "$M" "$R" "$O" "$D" "$A" "$S" "$X")"
   ```
3. Push-notify (if policy != `off`):
   ```
   Test plan complete. <M> mandatory + <R> recommended + <O> optional tests drafted.
   Cross-LLM dropped <D> trivial drafts; added <A> coverage gaps.

   Recommended next:
     /z-implement-all   — implements tasks AND their linked TESTS.md entries together
   ```
4. Brief user summary (3-5 sentences): what was drafted, what cross-LLM caught, how many cross-task tests are deferred to /z-review-all.

## Hard rules

- **Non-trivial tests only.** Every TESTS.md entry must name a domain-specific **failure class**. Assertions like "function returns" or "no exception raised" without further constraint are rejected. The cross-LLM consult exists precisely to catch and drop these.
- **Tests tied to invariants.** Every mandatory test must trace to (a) a quoted SPEC.md invariant, (b) a high-risk task in TASKS.md, or (c) a user-stated concern from Phase 1. No orphan tests.
- **Cross-LLM consult is non-skippable.** This is the entire point of `/z-test` — Claude alone reliably generates trivial tests; the cross-LLM step catches the bug classes it would otherwise miss.
- **No test execution.** `/z-test` is planning, not execution. The implementer writes the test code (in the same task as its production code); `/z-implement-all`'s per-task acceptance check runs it; `/z-review-all`'s final gate runs the suite.
- **No SPEC.md / PLAN.md edits.** Only writes TESTS.md and appends `**Tests:**` lines to TASKS.md.
- **No new agents dispatched.** Reuses `consultant-primary` and `consultant-secondary` only.
- **No emojis** anywhere in TESTS.md.

## What /z-test deliberately skips

- Does not run any tests (deferred to /z-implement-all + /z-review-all).
- Does not write actual test code (the implementer subagent does, in the task's diff).
- Does not modify SPEC.md or PLAN.md (only appends `**Tests:**` to TASKS.md and creates TESTS.md).
- No implementer-subagent dispatch (all ideation in orchestrator main thread + cross-LLM consult, same model as /z-plan-light).
- No `--apply` flag — Phase 5 `AskUserQuestion` is the only write gate. The user can re-run `/z-test` later to add more tests; merge semantics in Phase 7 handle this.
