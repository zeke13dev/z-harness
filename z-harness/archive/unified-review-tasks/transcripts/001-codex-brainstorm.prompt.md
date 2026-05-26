Mode: brainstorm

Input artifact:
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

Context:

Quoted local context from the z-harness repo:

1. `commands/z-review-all.md` / `skills/z-review-all/SKILL.md` currently aggregate findings, then ask the user what to do:

```
## Phase 5 — Aggregate findings
Build `$BASE/archive/$RRUN/findings.md` with Prong A — Implementation drift and Prong B — Spec gaps, grouped by severity and consensus.

## Phase 6 — Present + ask what to do
Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
- Open drift fixup tasks → append new tasks to `$BASE/TASKS.md`, mark them `[ ]`. User can then run `/z-implement-all` again.
- Spec retro → patch `$BASE/SPEC.md` to address the Prong B findings.
- Both
- Ship as-is — write shipped.md acknowledging findings as acceptable.
- Reject and re-plan — escalate; recommend running `/z-plan` for the affected scope.

Hard rules:
- Never edit SPEC.md or TASKS.md automatically. Always present changes to the user first.
- Never trust a single LLM's finding without pushback.
- Always archive cumulative diff and transcripts.
```

2. `commands/z-amend.md` / `skills/z-amend/SKILL.md` already defines safe plan mutation semantics:

```
Phase 3 — Impact analysis writes amendment.md listing what changes in SPEC.md, PLAN.md, TASKS.md/FIX.md.
ID-allocation rule: new tasks always take fresh IDs. Never reuse a deleted task's ID.
Completed-task rule: if a `[x]` task's behavior is contradicted, do NOT edit it in place. Add a new `[ ]` task whose description explicitly says "supersedes T0NN".
Phase 4 — User gate: Show amendment.md to the user; approve/revise/abandon. Touched completed tasks get a separate explicit decision.
Phase 6 — Propagate edits: update SPEC/PLAN/TASKS surgically, append fresh tasks, preserve completed tasks unless explicitly reopened.
```

3. `commands/z-audit.md` already normalizes findings into implementer-ready artifacts instead of asking what to do per finding:

```
/z-audit output is REPORT.md (everything found) plus curated TASKS.md (actionable subset, /z-implement-all-compatible) under $Z_HARNESS_PLAN_DIR-audit/.
This command is read-only. Never edit the target. Fixes happen later via /z-implement-all consuming the emitted TASKS.md.
Phase 5 — Promote to TASKS.md: Only actionable findings go into TASKS.md. An observation with no clear fix stays in REPORT.md.
It also writes minimal SPEC.md and PLAN.md so /z-implement-all can consume the audit task set.
Phase 6 — Codex safety gate on TASKS.md: review audit-produced tasks for vague acceptance, severity inflation, scope creep, and invariant regressions.
```

4. `commands/z-mr-review.md` similarly writes a task-shaped artifact and makes the user's decision a single edit/delete pass:

```
MR-REVIEW.md frontmatter includes findings_index. Findings are emitted as T-MR-NNN task blocks grouped by severity.
Header text: "Findings ranked P0-P4. Delete any finding you don't want fixed. Then /z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md."
Final message: "Delete what you don't want, then /z-implement-all --tasks=... to apply the survivors."
```

5. `agents/mr-reviewer.md` returns structured JSON findings for machine promotion:

```
Findings schema: severity, category, file, line_start, line_end, title, detail, citation, voices.
The orchestrator dedups, consensus-bumps/demotes, applies dismissal patterns, then writes MR-REVIEW.md.
```

6. `agents/auditor.md` returns grounded findings with Location, Evidence, Recommendation, Severity. It must be read-only, one dimension per invocation, and drops findings without concrete evidence.


Constraints:

Constraints and conventions:
- Prefer one up-front policy decision over repeated AskUserQuestion prompts after review-all.
- Preserve z-harness's audit trail: archive findings, consultant transcripts, telemetry events, and user decisions.
- Preserve safety rules around completed `[x]` tasks: do not mutate completed work silently; supersede with new tasks unless explicitly reopened.
- Outputs that imply work should be consumable by `/z-implement-all` or `/z-implement-next` where practical.
- Avoid turning every review into full replanning; retain escalation path for structural/spec-premise failures.
- Keep workflows idempotent and task files parseable; do not create ambiguous prose-only dead ends.
- DRY/KISS/SOLID: if adding a unification layer, decide whether it belongs as shared policy/helper, command convention, artifact schema, or a new command.


Ask:
Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation.

