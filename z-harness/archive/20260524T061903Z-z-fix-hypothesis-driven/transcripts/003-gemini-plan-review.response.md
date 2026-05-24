Ripgrep is not available. Falling back to GrepTool.
Error executing tool grep_search: Path does not exist: /Users/zeke/dev/z-harness/z-harness/commands
(node:64476) [DEP0190] DeprecationWarning: Passing args to a child process with shell option true can lead to security vulnerabilities, as the arguments are not escaped, only concatenated.
(Use `node --trace-deprecation --max-listeners=unlimited ...` to show where it happens.)

Here is the critique of the provided SPEC and PLAN, structured around the six key scrutiny points:

### 1. Contamination boundary (D3+D4)
- **Flaw (Context Window Reality):** The orchestrator is an LLM with a persistent session history. In SPEC Phase 3a.1, the orchestrator generates hypotheses in the main thread and writes them to a checkpoint file. When it later "reads its checkpoint file from disk (not from conversation state)" (SPEC Phase 3a.3, PLAN D4), the original generation is *still permanently in its context history*. It cannot simply "forget" it.
- **Interaction/Impact:** This breaks the D4 contamination mitigation. The orchestrator's semantic de-dup step will be biased by its own generation remaining in context.
- **Fix:** The orchestrator must spawn a separate subagent (e.g., `gemini-consultant`) to generate the Round 1 block, or write the checkpoint using a stateless script.

### 2. Round 2 forbid-agreement (D5)
- **Flaw (Prompt Fragility):** Relying solely on prompt wording ("Your value is orthogonality and critique, not endorsement" in SPEC `agents/codex-consultant.md`) is fragile against LLM sycophancy. Models will likely disguise endorsements as "nuanced additions" or "refinements."
- **Missing Filter:** PLAN Phase A and SPEC Phase 3b lack an active rejection step. The orchestrator's integration instructions ("Orchestrator integrates additions...") naively assume the output complies.
- **Fix:** Instruct the orchestrator during the Phase 3b merge to explicitly filter and discard any "NEW" hypothesis that is semantically similar to the pool, and any "CRITIQUE" that merely validates.

### 3. Fix-gate measurability (Phase 6 / Phase 7)
- **Flaw (Prose Loophole):** The rule requiring "a written causal mechanism that explains every piece of evidence" (SPEC Phase 11) is entirely prose-based. This interacts poorly with the LLM's tendency to rubber-stamp plausible-sounding text, reopening the "False confirmation at scale" risk explicitly noted in the PLAN.
- **Missing Rigor:** There is no machine-checkable or structured validation step.
- **Fix:** Force the orchestrator to construct an explicit mapping matrix (`Evidence Item` → `How the Root Cause explains it`) before declaring the fix-gate open.

### 4. Surgical section extraction (Phase 3b, Phase 7)
- **Critical Flaw (Context Starvation):** The extraction boundaries defined in PLAN D2 and SPEC are overly restrictive and break the agents' ability to reason:
  - **Round 2 (Phase 3b):** Consultants receive "ONLY the merged `## Hypothesis Pool` section... NOT the full DEBUG.md". Without the `Problem` or `Evidence Inventory`, they cannot possibly generate relevant new hypotheses or judge if a test is "discriminating" for the specific bug.
  - **Fix Consult (Phase 7):** Receives "Root Cause + Experiment Log sections only". It cannot push back on whether the fix addresses the original symptoms if it doesn't have the `Problem` or `Evidence Inventory`.
- **Fix:** Round 2 and Fix Consult *must* receive the `Problem` and `Evidence Inventory` sections alongside their targeted sections.

### 5. Return-shape contract tightness (D5)
- **Flaw (Parsing Ambiguity):** The new modes specify "Return RAW (no standard wrapper)" and an "ordered list, each row schema..." (SPEC `agents/codex-consultant.md`). It never mandates a strict, parsable data format.
- **Impact:** If one model returns a Markdown table and another returns a Markdown list, the orchestrator's Phase 3b parsing will be heuristic and fragile, risking a broken pool merge.
- **Fix:** The mode contracts must explicitly enforce JSON arrays of objects if they return RAW.

### 6. Migration path
- **Flaw (Wrong Order & Broken Commands):** PLAN Phase E places a grep for `/z-debug` references at the very end. However, existing commands currently hardcode the old file artifacts. A codebase search reveals:
  - `commands/z-improve.md` explicitly checks for `POST-MORTEM.md if present, else PROBLEM.md` (Line 45).
  - `commands/z-stats.md` explicitly parses `POSTMORTEM.md` (Line 98).
- **Impact:** Implementing Phase C will immediately break `/z-improve` and `/z-stats`.
- **Fix:** These references must be updated to target sections within the unified `DEBUG.md` as a prerequisite or concurrent update in Phase C, not as a post-hoc verification in Phase E. Additionally, `commands/z-amend.md` should be evaluated to see if it needs to support amending `DEBUG.md`.
