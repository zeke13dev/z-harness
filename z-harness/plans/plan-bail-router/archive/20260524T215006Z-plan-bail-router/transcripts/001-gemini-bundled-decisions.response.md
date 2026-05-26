Warning: Basic terminal detected (TERM=dumb). Visual rendering will be limited. For the best experience, use a terminal emulator with truecolor support.
Ripgrep is not available. Falling back to GrepTool.
Here is a review of the plan-bail-router decisions, addressing your specific questions and constraints.

### D1: Router Shape
*   **Agree?** Yes.
*   **Reasoning & Tradeoffs:** Because exported commands (Cursor/Codex) must be standalone, you cannot rely on runtime includes. A canonical source document (`docs/human/PLAN-ROUTING.md`) that gets compiled into a terse matrix inside each command's prompt is the only way to stay DRY in source while being standalone in output.
*   **What could go wrong:** If the embedded rubric is too verbose, it will dilute the system prompt of lightweight commands like `/z-do`, degrading their primary performance.
*   **Concrete Changes:** The canonical source can be detailed, but the injected text must be an aggressively minimized, bulleted "Bail Matrix" (e.g., `If files > 5 -> Bail to /z-plan`).

### D2: Route Targets and Boundaries
*   **Agree?** Yes, with a clarification on `/z-audit-plan`.
*   **Reasoning & Tradeoffs:** Allowing bails to narrow off-family commands (`/z-fix`, `/z-debug`, `/z-amend`) perfectly handles the "wrong front-door" problem without making the router a monolithic monolith. 
*   **Specific Ask - `/z-audit-plan`:** `/z-audit-plan` does **not** belong in the *bail/routing* matrix. Bailing implies "you picked the wrong tool for this user request." `/z-audit-plan` is a *pipeline* step that requires an existing `SPEC/PLAN/TASKS` tree. It should remain a post-plan recommendation, not a pre-execution bail target.
*   **What could go wrong:** Bailing to `/z-fix` just because the user said "bug", even if it's a massive architectural defect requiring `/z-plan`.
*   **Concrete Changes:** Gate the off-family bails strictly on complexity, not just intent. (e.g., "If simple bug -> `/z-fix`. If complex/architectural bug -> `/z-plan`").

### D3: Complexity Metric and Classifier Role
*   **Agree?** No. Discard the hybrid subagent approach.
*   **Reasoning & Tradeoffs:** You asked if this should be a new agent, an extension of `complexity-classifier`, or a main-thread heuristic. It **must be a main-thread heuristic**. Invoking a subagent at the very beginning of a command just to decide *whether* to execute it introduces unacceptable latency, context-switching, and token costs to lightweight commands like `/z-do`. The existing `complexity-classifier` operates on well-structured post-plan `TASKS.md`; a pre-plan request is too unstructured for a cheap subagent to reliably beat a main-thread LLM utilizing a deterministic rubric.
*   **What could go wrong:** High failure rates or timeouts during the routing phase, frustrating users before work even begins.
*   **Concrete Changes:** Use purely deterministic, main-thread heuristics based on the prompt's embedded rubric. If the heuristics fall into an ambiguous band, default to the safer/heavier option (e.g., escalate `/z-do` to `/z-plan-light`) or use an `AskUser` gate.

### D4: Bail Semantics and Loop Prevention
*   **Agree?** Partially. 
*   **Reasoning & Tradeoffs:** You asked if "halt-with-recommendation" is too conservative. It is. Automatically halting forces the user to manually re-invoke the CLI, which breaks flow. However, automatic handoffs are dangerous because of differing approval gates.
*   **What could go wrong:** Hard halts frustrate users. Auto-handoffs might accidentally execute a heavy `/z-plan` without user consent.
*   **Concrete Changes:** Use the **AskUser handoff gate**. Since commands like `/z-do` already utilize `AskUser` successfully mid-flight, use it for early bails too. When a bail condition is met:
    1. Write the context artifact (`escalation.md` or `handoff.md`).
    2. Log the route telemetry.
    3. Use `AskUser`: "This task exceeds `/z-plan-light` thresholds. Escalate to `/z-plan`? [Yes/No/Abandon]".
    4. If Yes, instruct the user on the exact command to run, or trigger the handoff if the CLI execution environment supports it. If it doesn't support auto-chaining, a hard halt *after* writing context is an acceptable fallback.
