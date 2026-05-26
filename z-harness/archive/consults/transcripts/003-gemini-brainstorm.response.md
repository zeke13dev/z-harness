### 1. Framing

The current `z-review-all` command disrupts the CLI's asynchronous, artifact-driven philosophy by forcing a blocking conversational gate (via `AskUserQuestion`) to triage findings into "code fixes" vs. "spec updates." This creates an impedance mismatch with `z-audit` and `z-mr-review`, which have already solved the triage problem elegantly: they output findings directly into a `TASKS.md`-shaped artifact, deferring the decision to the user's text editor. By treating the conversational gate as a crutch, we are missing a unified structural mechanism for promoting *any* analytical finding into an executable unit of work.

### 2. Core hypothesis

**The "Unified Fixup Queue" Hypothesis:** Eliminate conversational triage entirely across all review commands (`z-review-all`, `z-audit`, `z-mr-review`) by mapping every class of finding to a specific task archetype in a standardized `TASKS.md` format. 

Instead of asking the user what to do, the orchestrator automatically generates a deterministic fixup queue. For `z-review-all`:
- **Prong A (Code Drift)** automatically maps to `[ ] TNNN-fix-drift: <description>` tasks, appending them to the current plan's `TASKS.md`.
- **Prong B (Spec Gaps)** automatically maps to `[ ] TNNN-amend-spec: <description>` tasks, leveraging `z-amend` as an executable task type rather than a manual command.

The user's "decision" shifts from answering a CLI prompt to the standard, unified interaction model: review the `TASKS.md`, delete the tasks you disagree with (to handle false positives/hallucinations), and run `/z-implement-all`.

### 3. Risks

- **Deletion Fatigue:** If the false-positive rate of `z-review-all` or `z-audit` findings is high (hallucinated drift), automatically generating tasks forces the user to meticulously prune a massive list. It may be mentally easier to "reject all" in a chat prompt than to parse and delete 20 bogus task lines.
- **Bypassing the Amendment Gate:** `z-amend` currently relies on a strict impact-analysis user gate. If "amend the spec" becomes just another task in the queue (`TNNN-amend-spec`), we risk the implementer mutating `SPEC.md` autonomously during a `/z-implement-all` run, potentially destabilizing the entire plan without human sign-off.
- **Loss of Nuance:** A conversational gate allows the user to say, "Actually, you misunderstood the spec, the code is correct because of X." Text-file-based triage only allows binary inclusion/exclusion (delete or keep), stripping the LLM's ability to learn from corrective context before generating the fix.

### 4. Plan implications

- **Rewrite `commands/z-review-all.md` Phase 6:** Remove `AskUserQuestion` and replace it with logic that appends `TNNN` tasks to `$BASE/TASKS.md` based on Prong A / Prong B categorizations.
- **Standardize Task Archetypes:** Formally introduce `TNNN-fix` and `TNNN-amend` as natively understood schemas within `skills/z-implement-all/SKILL.md` and `agents/implementer.md`.
- **Modify `z-amend` mechanics:** Update `commands/z-amend.md` and `skills/z-amend/SKILL.md` to be invokable non-interactively by the implementer when processing a `TNNN-amend-spec` task, while preserving its completed-task supersession rules.
- **Align Audit/MR-Review:** Ensure `z-audit` and `z-mr-review` share the exact same findings-to-tasks promotion formatter to ensure the user only ever has to learn one triage workflow.

### 5. What would change my mind

If telemetry or user observation reveals that resolving review findings requires heavy, context-rich negotiation—where the user frequently needs to correct the LLM's understanding of the codebase before a valid fix can even be formulated. If findings are rarely "ready to implement" as written, then routing them straight to `TASKS.md` will cause implementation thrashing, and the conversational gate is actually functioning as a necessary context-alignment phase rather than a mere UX blocker.

