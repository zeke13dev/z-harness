---
artifact: brainstorm
slug: unified-review-tasks
generated_at: 2026-05-24T21:11:59Z
command: /z-brainstorm z-brainstorm Every time I run a review-all and there are amendments claude always asks me what to do (amend to spec inline, fix now, etc.). We need to unify this output into actionable tasks and make the decision once now. I am thinking that we might need to extend this idea to (possibly audit, though audit is closer to z-plan, mr-review, and any other places it might fit)
input_hash: 59d9bcd2f9d74b6b
depends_on: []
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: codex
---

## Framing: Claude

### Framing

The problem is not "Claude asks too many questions." The problem is review-family commands emit findings in a form that still requires workflow triage. That triage should be a first-class artifact, not an interactive fork at the end of a high-context run.

### Core hypothesis

Introduce a shared "findings-to-work" contract: review-all, mr-review, and maybe audit all normalize outputs into `TASKS.md`-shaped actionable items, each tagged with disposition like `fix_now`, `amend_spec`, `defer`, or `reject`. The user makes the disposition policy once up front, then the command applies it deterministically.

### Risks

- Over-unifying could flatten important differences. `z-review-all` is checking spec conformance, `z-mr-review` is quality-only, and `z-audit` can be closer to discovery/planning.
- If all commands emit identical tasks too early, "spec gap" or "design concern" may turn into implementation work without preserving rationale.

### Plan implications

- The clean design likely has a small shared intermediate schema for findings, then command-specific adapters into task artifacts.
- `z-review-all` should probably be the pilot because it has the most painful decision loop.
- `mr-review` is next because it already wants task-shaped output.
- `audit` should adopt the same schema only if it can preserve audit dimensions and severity without pretending every finding is ready-to-implement.

### What would change my mind

- If review-all amendments often require nuanced human judgment about whether the spec or implementation is wrong, then preselecting a disposition may be dangerous.
- In that case, the better move is a single consolidated triage board with all findings grouped, deduped, and awaiting one batch decision.

## Framing: Codex

### Framing

The problem is not that `z-review-all` asks a question. The problem is that it asks a workflow-shaping question too late, after findings exist, when the useful default should already be obvious: normalize actionable findings into task-shaped work, archive everything, and let the user prune or escalate once.

`z-audit` and `z-mr-review` already point to the better contract: review commands produce durable evidence plus implementer-consumable task artifacts. The user decision should move from "what mode should I use for these findings?" to "which of these proposed tasks survive?"

### Core hypothesis

`z-review-all` should adopt a "review findings become candidate tasks by default" policy, with spec amendments represented as explicit task/amendment artifacts rather than immediate inline edits.

Concretely, Phase 6 should stop offering "fix now / amend spec / both / ship / re-plan" as repeated choices. Instead, it should emit:

- Archived `findings.md` with all evidence and consultant transcripts.
- A curated task-shaped artifact, probably `REVIEW-TASKS.md` or appended pending tasks in `TASKS.md` only after a single gate.
- Spec-gap findings as amendment tasks or a generated `amendment.md`, following `z-amend` semantics.
- Explicit supersession tasks for completed `[x]` work.
- An escalation marker for findings that imply invalid premises or structural replanning.

The unifying abstraction is probably not a new command. It is a shared "finding promotion policy" used by `z-review-all`, `z-audit`, and `z-mr-review`, with command-specific output filenames.

### Risks

- Flattening distinct finding types into generic tasks too early. A code drift bug, a spec contradiction, and a premise failure should not all become "fix this" work items with the same execution path.
- Weakening the safety gate around spec mutation. If Prong B findings become tasks, implementers may accidentally encode spec changes without explicit `z-amend` approval semantics.
- Parseability drift between `MR-REVIEW.md` task blocks, audit `TASKS.md`, and canonical plan `TASKS.md`.
- Consensus laundering. Structured promotion makes findings look official, so the workflow still needs adversarial review before anything lands as executable work.

### Plan implications

- Introduce a shared policy doc or helper around "promote findings to actionable artifacts" rather than hardcoding behavior independently in each command.
- Define finding classes: `implementation_drift`, `spec_gap`, `completed_task_contradiction`, `premise_failure`, and `observation`.
- Let `z-review-all` mirror `z-audit`: write full findings plus a curated implementer-compatible artifact.
- Make the user's single decision edit/delete/approve the generated artifact, not choose a mode per finding.
- Keep `z-amend` as the authority for mutating `SPEC.md`, `PLAN.md`, and `TASKS.md`; review-all can prepare amendment material, but propagation should still go through the amendment gate unless an explicit policy says otherwise.

### What would change my mind

- Move this into a new command only if review findings need a separate lifecycle: triage queues, cross-plan deduplication, dismissal persistence, or multi-run finding state.
- Keep the existing question model if users regularly make different disposition choices per review run and the generated task artifact creates more cleanup than clarity.
- Append directly to `TASKS.md` only if `z-implement-all` already handles mixed canonical/review tasks cleanly and the audit trail can prove which tasks came from which review run.
- Require full `z-plan` escalation more often if spec-gap findings commonly reveal broken assumptions rather than localized amendments.

## Framing: Gemini

### Framing

The current `z-review-all` command disrupts the CLI's asynchronous, artifact-driven philosophy by forcing a blocking conversational gate to triage findings into "code fixes" vs. "spec updates." This creates an impedance mismatch with `z-audit` and `z-mr-review`, which have already solved the triage problem by outputting findings directly into a `TASKS.md`-shaped artifact. By treating the conversational gate as a crutch, we are missing a unified structural mechanism for promoting any analytical finding into an executable unit of work.

### Core hypothesis

Eliminate conversational triage across review commands (`z-review-all`, `z-audit`, `z-mr-review`) by mapping every class of finding to a specific task archetype in a standardized `TASKS.md` format.

For `z-review-all`:

- Prong A (Code Drift) automatically maps to `[ ] TNNN-fix-drift: <description>` tasks, appending them to the current plan's `TASKS.md`.
- Prong B (Spec Gaps) automatically maps to `[ ] TNNN-amend-spec: <description>` tasks, leveraging `z-amend` as an executable task type rather than a manual command.

The user's decision shifts from answering a CLI prompt to the standard interaction model: review the `TASKS.md`, delete tasks you disagree with, and run `/z-implement-all`.

### Risks

- Deletion fatigue if false-positive findings force the user to prune a massive task list.
- Bypassing the amendment gate if "amend the spec" becomes just another implementer task.
- Loss of nuance when binary text-file triage replaces the user's ability to correct the LLM before generating the fix.

### Plan implications

- Rewrite `commands/z-review-all.md` Phase 6: remove `AskUserQuestion` and replace it with logic that appends `TNNN` tasks to `$BASE/TASKS.md` based on Prong A / Prong B categorizations.
- Standardize task archetypes such as `TNNN-fix` and `TNNN-amend` in `skills/z-implement-all/SKILL.md` and `agents/implementer.md`.
- Modify `z-amend` mechanics so it can be invoked non-interactively by an implementer processing a `TNNN-amend-spec` task while preserving completed-task supersession rules.
- Align audit and mr-review on the same findings-to-tasks promotion formatter.

### What would change my mind

- If resolving review findings requires heavy, context-rich negotiation where the user frequently needs to correct the LLM's understanding before a valid fix can be formulated.
- If findings are rarely ready to implement as written, routing them straight to `TASKS.md` will cause implementation churn and the conversational gate is a necessary context-alignment phase.

## Anti-bias check

Framing: Codex wins. Claude correctly names late workflow triage as the core problem, and Gemini strongly connects the issue to artifact-driven workflows, but Codex best reframes the user decision from "which mode now?" to "which proposed tasks survive?" That preserves the user's requested one-time decision while leaving room for artifact review.

Core hypothesis: Codex wins. Gemini is boldest but too eager to append directly to canonical `TASKS.md` and make `z-amend` executable by implementers. Claude is appropriately cautious but less concrete about artifacts. Codex gives the strongest middle path: candidate tasks by default, spec amendments as explicit amendment material, and no direct spec mutation without the amendment gate.

Risks: Codex wins. It captures the broadest failure modes: flattening finding types, weakening spec-mutation safety, task dialect drift, and consensus laundering. Gemini's deletion-fatigue risk is useful and should be carried forward, but Codex covers more design-critical hazards.

Plan implications: Codex wins. Its shared "finding promotion policy" is the most reusable shape across `z-review-all`, `z-audit`, and `z-mr-review`, while still allowing command-specific output files and preserving `z-amend` authority.

What would change my mind: Codex wins. It offers the clearest boundary tests: when to make a new command, when to keep conversational prompts, when to append directly to `TASKS.md`, and when to escalate to full planning.

## Orchestrator recommendation

Choose the Codex framing: implement a shared finding-promotion policy that makes `z-review-all` produce durable findings plus candidate task/amendment artifacts by default, while preserving `z-amend` as the authority for actual spec/plan/task mutation.

## User choice

### Framing

The problem is not that `z-review-all` asks a question. The problem is that it asks a workflow-shaping question too late, after findings exist, when the useful default should already be obvious: normalize actionable findings into task-shaped work, archive everything, and let the user prune or escalate once.

`z-audit` and `z-mr-review` already point to the better contract: review commands produce durable evidence plus implementer-consumable task artifacts. The user decision should move from "what mode should I use for these findings?" to "which of these proposed tasks survive?"

### Core hypothesis

`z-review-all` should adopt a "review findings become candidate tasks by default" policy, with spec amendments represented as explicit task/amendment artifacts rather than immediate inline edits.

Concretely, Phase 6 should stop offering "fix now / amend spec / both / ship / re-plan" as repeated choices. Instead, it should emit:

- Archived `findings.md` with all evidence and consultant transcripts.
- A curated task-shaped artifact, probably `REVIEW-TASKS.md` or appended pending tasks in `TASKS.md` only after a single gate.
- Spec-gap findings as amendment tasks or a generated `amendment.md`, following `z-amend` semantics.
- Explicit supersession tasks for completed `[x]` work.
- An escalation marker for findings that imply invalid premises or structural replanning.

The unifying abstraction is probably not a new command. It is a shared "finding promotion policy" used by `z-review-all`, `z-audit`, and `z-mr-review`, with command-specific output filenames.

### Risks

- Flattening distinct finding types into generic tasks too early. A code drift bug, a spec contradiction, and a premise failure should not all become "fix this" work items with the same execution path.
- Weakening the safety gate around spec mutation. If Prong B findings become tasks, implementers may accidentally encode spec changes without explicit `z-amend` approval semantics.
- Parseability drift between `MR-REVIEW.md` task blocks, audit `TASKS.md`, and canonical plan `TASKS.md`.
- Consensus laundering. Structured promotion makes findings look official, so the workflow still needs adversarial review before anything lands as executable work.

### Plan implications

- Introduce a shared policy doc or helper around "promote findings to actionable artifacts" rather than hardcoding behavior independently in each command.
- Define finding classes: `implementation_drift`, `spec_gap`, `completed_task_contradiction`, `premise_failure`, and `observation`.
- Let `z-review-all` mirror `z-audit`: write full findings plus a curated implementer-compatible artifact.
- Make the user's single decision edit/delete/approve the generated artifact, not choose a mode per finding.
- Keep `z-amend` as the authority for mutating `SPEC.md`, `PLAN.md`, and `TASKS.md`; review-all can prepare amendment material, but propagation should still go through the amendment gate unless an explicit policy says otherwise.

### What would change my mind

- Move this into a new command only if review findings need a separate lifecycle: triage queues, cross-plan deduplication, dismissal persistence, or multi-run finding state.
- Keep the existing question model if users regularly make different disposition choices per review run and the generated task artifact creates more cleanup than clarity.
- Append directly to `TASKS.md` only if `z-implement-all` already handles mixed canonical/review tasks cleanly and the audit trail can prove which tasks came from which review run.
- Require full `z-plan` escalation more often if spec-gap findings commonly reveal broken assumptions rather than localized amendments.

Refinement: proceed to planning from this framing.
