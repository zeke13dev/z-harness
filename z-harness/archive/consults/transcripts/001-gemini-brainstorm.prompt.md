Mode: brainstorm

Input artifact (verbatim from caller):
MODE: brainstorm

Topic: z-brainstorm Every time I run a review-all and there are amendments claude always asks me what to do (amend to spec inline, fix now, etc.). We need to unify this output into actionable tasks and make the decision once now. I am thinking that we might need to extend this idea to (possibly audit, though audit is closer to z-plan, mr-review, and any other places it might fit)

Scaffolding:
# Phase 1 Scaffolding

## Topic

z-brainstorm Every time I run a review-all and there are amendments claude always asks me what to do (amend to spec inline, fix now, etc.). We need to unify this output into actionable tasks and make the decision once now. I am thinking that we might need to extend this idea to (possibly audit, though audit is closer to z-plan, mr-review, and any other places it might fit)

## Doc-Fetcher Synthesis

STATUS: partial - INDEX covers `commands`, `skills`, and `agents` for review, amendment, audit, and mr-review, but it does not record a cross-workflow policy for unifying review-all amendment decisions into actionable tasks. Caller should Explore for that gap.

### commands

The closest command-tier wiring is split: `z-review-all` validates cumulative diffs against spec, `z-amend` propagates targeted amendments across plan artifacts, `z-audit` coordinates multi-dimensional audits, and `z-mr-review` writes P0-P4 branch-review findings to `MR-REVIEW.md`. The docs imply actionable work should flow through plan/task artifacts rather than ad hoc report prose.

Key files: `commands/z-review-all.md`, `commands/z-amend.md`, `commands/z-audit.md`, `commands/z-mr-review.md`.

Invariants / gotchas: commands must log execution events and resolve plan dirs via `scripts/plan-path.sh`; large plans should delegate to subagents.

### skills

Skill docs say the operational discipline lives in SKILL checklists. Relevant skills are `z-review-all` for cumulative diff/spec review, `z-amend` for consistent SPEC/PLAN/TASKS mutation, and `z-implement-all` / `z-implement-next` for executing pending task files. This supports a task-unification design where findings are normalized into TASKS-shaped work before execution.

Key files: `skills/z-review-all/SKILL.md`, `skills/z-amend/SKILL.md`, `skills/z-implement-all/SKILL.md`.

Invariants / gotchas: all skills must be idempotent; phase telemetry must be logged; do not bypass skill checklists.

### agents

Agent-tier docs identify `mr-reviewer` as deduplicating consultant findings and returning structured findings JSON, and `auditor` as producing dimension-specific findings. `implementer` is the executor for discrete task files, so the missing unification layer likely belongs between review/audit finding outputs and implementer-consumable task artifacts.

Key files: `agents/mr-reviewer.md`, `agents/auditor.md`, `agents/implementer.md`.

Invariants / gotchas: subagents are isolated; subagents are read-only except explicitly authorized output files.

DRIFT WARNING: `agents` concept JSON references missing files: `agents/codex-consultant.md`, `agents/codex-reviewer.md`, `agents/gemini-consultant.md`.

## Explore Synthesis

Skipped because `Z_HARNESS_BRAINSTORM_EXPLORE` is unset.

## RESEARCH.md

No `z-harness/unified-review-tasks/RESEARCH.md` found.

## Input Hash

`59d9bcd2f9d74b6b`

Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.

Context from repo files (quoted excerpts and observed patterns):

1. `commands/z-review-all.md` currently ends with an explicit user decision gate after findings aggregation:

```markdown
## Phase 6 — Present + ask what to do

Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps."

Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:

- **Open drift fixup tasks** → append new tasks (e.g. `T100-fixup-drift`) to `$BASE/TASKS.md`, mark them `[ ]`. User can then run `/z-implement-all` again.
- **Spec retro** → patch `$BASE/SPEC.md` to address the Prong B findings (you make the edits in-line; user reviews).
- **Both**
- **Ship as-is** — write a `$BASE/archive/$RRUN/shipped.md` acknowledging findings as acceptable; close out the plan.
- **Reject and re-plan** — escalate; recommend running `/z-plan` for the affected scope.
```

Hard rules also say:

```markdown
- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
- **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
```

2. `commands/z-review-all.md` already has two distinct finding classes:

```markdown
**Prong A — Implementation faithfulness.** Does the cumulative diff implement SPEC.md as written? List drift:
- Files that should have changed per SPEC but didn't.
- Files that changed but don't match the spec'd surface/behavior.
- Cross-task drift ...
- Missing tests / assertions called out in spec acceptance criteria.

**Prong B — Spec correctness.** Now that the implementation is done, is the spec itself correct/sufficient? List spec gaps:
- Decisions made in PLAN.md that turned out wrong when implemented.
- Invariants the spec asserted that the code can't actually satisfy.
- Edge cases the spec missed ...
```

3. `commands/z-amend.md` has a mature amendment model that preserves completed work:

```markdown
**Completed-task rule:** if a `[x]` task's behavior is contradicted by the amendment, do NOT edit it in place. Instead, add a new `[ ]` task whose description explicitly says "supersedes T0NN: <reason>". The user sees both in the archive trail.
```

It also mandates an impact-analysis gate:

```markdown
## Phase 4 — User gate
Show `amendment.md` to the user via `AskUserQuestion`:
- **Approve as drafted** → proceed to Phase 5
- **Revise** ...
- **Abandon** ...
```

4. `commands/z-audit.md` is already task-normalized by design:

```markdown
You are running **z-harness `/z-audit`** — a structured, read-only audit pipeline. The output is `REPORT.md` (everything found) plus a curated `TASKS.md` (actionable subset, in `/z-implement-all`-compatible format) under `$Z_HARNESS_PLAN_DIR-audit/`.
```

Audit promotion rule:

```markdown
## Phase 5 — Promote to TASKS.md
Only actionable findings go into TASKS.md. An observation that has no clear fix stays in REPORT.md.
Write `$BASE/TASKS.md` in the **exact format `/z-implement-all` consumes** ...
```

Audit also emits minimal SPEC/PLAN wrappers so `/z-implement-all` can consume the queue:

```markdown
This three-file set (SPEC.md / PLAN.md / TASKS.md) is what `/z-implement-all` requires.
```

5. `commands/z-mr-review.md` is also task-shaped, not question-shaped:

```markdown
Findings ranked P0-P4. **Delete any finding you don't want fixed.** Then `/z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md`.
```

And the command description says:

```yaml
description: Multi-LLM code-quality review of the current branch diff against STYLE.md. Never blocks; ranks P0-P4; output is a TASKS.md-shape file you edit and feed to /z-implement-all.
```

6. `skills/z-implement-all/SKILL.md` defines implementer-compatible task execution and halt behavior. Important snippets:

```markdown
- `STATUS: decision_needed` → halt queue, push-notify, present the decision + options via `AskUserQuestion`. This is the "major design decision must be approved by user" gate.
```

and final recommended flow:

```markdown
Recommended next:
  /z-review-all      — final-gate cross-LLM review of the cumulative diff
  /z-maintain-docs   — refresh docs for any concepts the implementation touched
```

7. `agents/implementer.md` says tasks are the executable unit and the implementer must stop on surprise decisions/spec problems:

```markdown
You implement **exactly one task** from `$Z_HARNESS_PLAN_DIR/TASKS.md` and return a structured summary.
...
If during implementation you hit an **unforeseen non-obvious decision** ... STOP and return `status: "decision_needed"` with the decision and ≥2 options. Do not pick one yourself.
```

8. `agents/auditor.md` produces findings, not fixes, with strict grounding:

```markdown
For each finding:
- **Location:** `path:line`
- **Evidence:** ≤3 lines of quoted code or a measured fact
- **Recommendation:** concrete fix in one sentence
- **Severity:** `CRITICAL | HIGH | MED | LOW`
```

9. `agents/mr-reviewer.md` returns parseable JSON findings and the orchestrator owns task shaping:

```markdown
You rank findings P0–P4 and return them as a fenced JSON block plus a `## Summary` markdown block. You never write MR-REVIEW.md yourself — the orchestrator does that from your return.
```

Constraints:
- The goal is brainstorm ideation, not final design. Be bold and distinct.
- Existing z-harness conventions favor task artifacts as the unit of execution, archive trails, telemetry via `scripts/log-event.sh`, and user gates only at high-value decision points.
- Avoid adding another ad hoc ask-every-time branch if a deterministic classification policy can decide once now.
- Preserve safety: final review findings can be wrong, and current docs require pushback (“one reason this might be wrong”) before action.
- Consider whether the policy should apply only to `/z-review-all`, also to `/z-audit`, `/z-mr-review`, or to a generalized “finding promotion” layer.
- Consider completed task semantics: completed tasks should generally be superseded by new fixup tasks, not silently mutated.

Ask:
Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation.

