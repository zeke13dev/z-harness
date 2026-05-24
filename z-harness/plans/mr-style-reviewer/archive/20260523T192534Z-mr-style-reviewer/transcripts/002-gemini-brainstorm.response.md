Ripgrep is not available. Falling back to GrepTool.
### (1) Framing
The current `z-harness` review stack treats code as a fulfillment of a `SPEC.md`, prioritizing "Does it work?". The MR-style reviewer shifts the focus to "Is this code we want to live with?". It reframes the AI's role from a contractor delivering a feature to a resident craftsman protecting the project's long-term health against **"Agent-Slop"**—the specific brand of technical debt (verbose error handling for impossible states, repetitive low-signal tests, and "append-only" architecture) that LLMs generate when left to their own ergonomic defaults.

### (2) Core hypothesis
AI-generated technical debt follows a predictable "synthetic" pattern: excessive defensive boilerplate to mask uncertainty, repetitive tests that increase coverage without increasing confidence, and a refusal to refactor existing abstractions in favor of local code-length creep. A reviewer specifically prompted to recognize these **LLM-isms**—rather than just general "cleanliness"—will catch the 40% of ergonomic drift that a generic `auditor.md` (focused on static rules or general design) inevitably ignores.

### (3) Risks
*   **The "Edit War" Loop:** If the reviewer's aesthetic critique conflicts with the `Implementer` agent's logic, we risk an infinite `z-amend` cycle where subagents fight over naming or abstraction while the user pays the token bill.
*   **Style Guide Hallucination:** A generated `STYLE.md` risks becoming a "write-only" document that agents claim compliance with while actually drifting, creating a false sense of consistency.
*   **Orchestration Bloat:** If the distinction between this and `/z-audit --dimension=cleanliness` is only the prompt content, creating a new command adds "Tooling Slop"—complexity in the plugin that should have been solved by refining the existing Auditor's rubric.

### (4) Plan implications
*   **Discovery First:** Implement `/z-style-init` not as a generator, but as a **Capture** tool that analyzes the project's most idiomatic files to extract *actual* patterns, ensuring the `STYLE.md` is grounded in reality rather than LLM "best practice" hallucinations.
*   **Diff-Aware Scrutiny:** Unlike the file-based `/z-audit`, this reviewer must be strictly diff-aware, preventing the agent from blaming existing codebase mess for its own new "slop" injection.
*   **Pre-Correctness Gate:** Integrate this as the first phase of `/z-review-all`. If the code fails the "Slop Test," the expensive correctness checks (Gemini/Codex) are deferred until the implementation is tightened, saving high-tier tokens on garbage code.

### (5) What would change my mind
I would abandon the dedicated command if augmenting the existing `auditor.md` with a "Synthetic Smells" rubric and a `STYLE.md` input achieves >90% parity in finding LLM-isms. Furthermore, if the "slop" identified by the agent is so subjective that a human developer rejects more than 30% of its suggestions, the tool becomes a noise-generator and should be folded into a simple, optional linter.
