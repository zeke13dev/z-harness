## Framing

The problem is not that `z-review-all` asks a question. The problem is that it asks a workflow-shaping question too late, after findings exist, when the only useful default should already be obvious: normalize actionable findings into task-shaped work, archive everything, and let the user prune or escalate once.

`z-audit` and `z-mr-review` already point to the better contract: review commands produce durable evidence plus implementer-consumable task artifacts. The user decision should move from “what mode should I use for these findings?” to “which of these proposed tasks survive?”

## Core hypothesis

`z-review-all` should adopt a “review findings become candidate tasks by default” policy, with spec amendments represented as explicit task/amendment artifacts rather than immediate inline edits.

Concretely, Phase 6 should stop offering “fix now / amend spec / both / ship / re-plan” as repeated choices. Instead, it should emit:

- archived `findings.md` with all evidence and consultant transcripts
- a curated task-shaped artifact, probably `REVIEW-TASKS.md` or appended pending tasks in `TASKS.md` only after a single gate
- spec-gap findings as amendment tasks or a generated `amendment.md`, following `z-amend` semantics
- explicit supersession tasks for completed `[x]` work
- an escalation marker for findings that imply invalid premises or structural replanning

The unifying abstraction is probably not a new command. It is a shared “finding promotion policy” used by `z-review-all`, `z-audit`, and `z-mr-review`, with command-specific output filenames.

## Risks

The main risk is flattening distinct finding types into generic tasks too early. A code drift bug, a spec contradiction, and a premise failure should not all become “fix this” work items with the same execution path.

Another risk is weakening the safety gate around spec mutation. If Prong B findings become tasks, implementers may accidentally encode spec changes without the explicit `z-amend` approval semantics. The task format needs to distinguish implementation fixes from spec amendments from replan blockers.

There is also a parseability risk. `MR-REVIEW.md` task blocks, audit `TASKS.md`, and canonical plan `TASKS.md` can drift into subtly different dialects unless the repo defines one task block schema.

Finally, consensus can become laundering. If structured promotion makes findings look official, the workflow still needs the current “never trust a single LLM without pushback” rule before anything lands as executable work.

## Plan implications

I would introduce a shared policy doc or helper around “promote findings to actionable artifacts” rather than hardcoding the behavior independently in each command.

The policy should define finding classes:

- `implementation_drift`: promote to pending implementation task
- `spec_gap`: promote to amendment proposal or amendment task, not direct SPEC edit
- `completed_task_contradiction`: promote to fresh pending task with “supersedes T0NN”
- `premise_failure`: do not promote directly; mark replan/escalation required
- `observation`: keep in report only

`z-review-all` would then mirror `z-audit`: write full findings plus a curated implementer-compatible artifact. The user’s single decision becomes edit/delete/approve the generated artifact, not choose a mode per finding.

`z-amend` remains the authority for mutating `SPEC.md`, `PLAN.md`, and `TASKS.md`. Review-all can prepare amendment material, but propagation still goes through the amendment gate unless the user has explicitly chosen a repo-wide policy that permits review-generated amendment files.

## What would change my mind

I would move this into a new command only if review findings need a genuinely separate lifecycle: triage queues, cross-plan deduplication, dismissal persistence, or multi-run finding state.

I would keep the existing AskUserQuestion model if users regularly make different disposition choices per review run and the generated task artifact creates more cleanup than clarity.

I would append directly to `TASKS.md` instead of writing a separate review task artifact only if `z-implement-all` already handles mixed canonical/review tasks cleanly and the audit trail can still prove which tasks came from which review run.

I would require full `z-plan` escalation more often if spec-gap findings commonly reveal broken assumptions rather than localized amendments.

