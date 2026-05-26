Here is a critique of the plan, focusing on spec gaps, implementation risks, and missing details based on the provided context.

### 1. Handling Conflicting Escalation Paths & Telemetry (Implementation Risk)
**Issue:** `z-do` and `z-plan-light` *already* have thresholds, write to `escalation.md`, and emit `do_escalation` logs. The spec introduces `route-decision.md` and `plan_route_decision` telemetry.
**Fix:** Explicitly define the transition strategy in Phase 2/3. To respect the constraint to "preserve existing telemetry consumers," the plan must state whether to rewrite the existing escalation blocks entirely and shim the old telemetry events (e.g., logging both `do_escalation` and `plan_route_decision`), or replace them and update `z-improve/z-stats` to consume the new `plan_route_decision` event. Leaving both prompt blocks in the commands will cause conflicting LLM behavior.

### 2. Archive Path Inconsistency (Implementation Risk)
**Issue:** The spec requires writing `route-decision.md` to the "active run archive", but the context explicitly states that archive paths differ wildly across commands (`z-harness/adhoc/archive/` vs `$Z_HARNESS_PLAN_DIR/archive/` vs `$BASE/archive/`).
**Fix:** The plan must specify how the route block determines the correct archive path per command, or introduce a standardized variable (e.g., `$CURRENT_ARCHIVE_DIR`) in the sentineled blocks to ensure `route-decision.md` is written to the correct location without hardcoding fragile paths.

### 3. Missing Loop Prevention Mechanism (Spec/Plan Gap)
**Issue:** The spec mandates "Loop prevention: max 2 prior route entries". However, the plan does not give the LLM a mechanism to actually *check* prior entries. 
**Fix:** Add instructions to the command/skill sentineled blocks telling the agent to read `route-decision.md` (if it exists) to extract the `route_chain` before attempting to route again. Without an explicit read step in the prompt, the agent will have no state awareness of previous bounces.

### 4. `docs/llm/commands.json` Omission (Under-scoped)
**Issue:** The context notes that `commands/z-audit-plan.md` exists but is missing from `docs/llm/commands.json`. The plan's Phase 4 generically mentions "docs/memory and z-audit-plan drift" but fails to explicitly address the registry file.
**Fix:** Update Phase 4 to explicitly add `z-audit-plan.md` to the `docs/llm/commands.json` registry. If this isn't fixed, the export generation (Phase 5) will continue to omit the command from IDE exports.

### 5. Agent Frontmatter & Tool Capabilities (Spec/Plan Gap)
**Issue:** The context dictates that new agents must fit existing frontmatter conventions (`tools`/`model` fields). The spec mentions "haiku/read-only" but doesn't define how the router agent gathers context.
**Fix:** Phase 1 must specify the `planning-router` frontmatter configuration. Set the model to Haiku and, crucially, grant it the specific tools it needs (e.g., `read_file`, `list_directory`) to independently verify "signals" like candidate files and code seams, ensuring it doesn't hallucinate structural metrics.
Warning: Basic terminal detected (TERM=dumb). Visual rendering will be limited. For the best experience, use a terminal emulator with truecolor support.
Ripgrep is not available. Falling back to GrepTool.

