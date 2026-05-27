### (1) Framing
Currently, our architecture relies on reactive, mid-flight escalation. Commands like `/z-plan` or `/z-debug` launch with the assumption of a manageable scope, perform initial exploration, and only "up-route" (bail and escalate) when they hit hardcoded complexity thresholds (e.g., >25 tasks, >5 files). While we have specific fan-out patterns (like `/z-plan-split` clustering or `/z-brainstorm` parallel ideators), we lack a universal, proactive "map-reduce" layer. The goal is a pre-dispatch router that intercepts any `z-*` command, sizes the bounding box of the request *before* executing the primary skill, discovers natural structural seams, and orchestrates N parallel, narrowly-scoped sub-runs, followed by a main-thread synthesis. This shifts the system from "try and abort" to "measure and divide."

### (2) Core hypothesis
**Where routing lives:** A new, lightweight universal CLI entrypoint (e.g., a `z-dispatch` wrapper script) paired with a fast Haiku-based `scope-analyzer` subagent. It intercepts the user's prompt before the underlying `z-*` skill is invoked.

**How the natural axis is discovered:** The `scope-analyzer` performs a rapid pass over `INDEX.json`, the workspace directory tree, and the initial prompt. It looks for architectural boundaries (directories/components), polymorphic patterns (e.g., multiple strategy implementations in a trading system), or distinct analytical dimensions. It outputs a standard JSON schema dictating `size` (LIGHT, MEDIUM, HEAVY) and an array of `sub_targets`.

**What main-thread synthesis looks like per command:**
*   **`/z-audit`:** Maps per component or module. Reduces by aggregating N component-specific audits into a single prioritized risk matrix and unified summary document.
*   **`/z-debug`:** Maps per distinct failure hypothesis or affected subsystem (e.g., "Run a trace on DB layer" parallel with "Run a trace on API validation"). Reduces by comparing diagnostic outputs, rejecting false hypotheses, and synthesizing the single confirmed root cause and fix.
*   **`/z-plan`:** The pre-flight router entirely replaces the Phase 1 mid-flight cluster proposal of `/z-plan-split`. Maps per cluster seam. Reduces via the existing `SHARED-CONCERNS.md` reconciliation and sequential sequencing.
*   **`/z-review-all`:** Maps per distinct feature, PR, or logical commit chunk. Reduces by merging localized code-review comments into a unified, deduplicated review memo.

**How this differs from today:** Today, the user pays the time and token cost of a partial run that ultimately aborts and restarts. Pre-flight routing calculates the shape of the work first, meaning sub-agents are spawned with strict, non-overlapping boundaries from second zero.

### (3) Risks
*   **The "Unknown Unknowns" Problem:** Particularly for debugging, the true scope or natural axis of a problem often cannot be known until the agent has actually explored the code mid-flight. Pre-flight routing might guess the wrong axis entirely.
*   **Synthesis Lossiness:** Merging N separate audit reports or debug traces into a cohesive narrative is notoriously difficult. The reducer might drop critical nuanced cross-references, leading to a disjointed final output.
*   **Over-splitting (Context Fragmentation):** Decomposing a medium-sized task into five micro-tasks might rob the sub-agents of necessary holistic context, causing them to hallucinate localized fixes that break the global system.
*   **Latency Overhead:** Adding a mandatory LLM-driven scoping pass before *every* command adds baseline latency, making genuinely simple, single-file commands feel sluggish.

### (4) Plan implications
*   **Creation of `scope-analyzer`:** A new Haiku-powered tool/subagent must be built to instantly parse intents and `INDEX.json` into a standardized `{ size, axis, targets }` routing payload.
*   **CLI Refactoring:** The entrypoints for `z-audit`, `z-debug`, `z-plan`, and `z-review-all` must be refactored to accept targeted `--scope` flags, allowing them to act as headless workers for the main orchestrator.
*   **Synthesis Scripts:** Distinct "reducer" scripts or prompts must be written for each command type, as combining debug logs is fundamentally different from combining plan clusters.
*   **Bypass Mechanism:** We will need a `--force-medium` or `--no-route` flag to allow users to bypass the router for known-quantity tasks.

### (5) What would change my mind
*   If we discover that the token economics of models like Gemini 1.5 Pro (with massive context windows) make monolithic, single-pass processing significantly cheaper and more cohesive than running 5 parallel Haiku agents + 1 orchestrator.
*   If pre-flight scoping proves consistently inaccurate (e.g., splitting by file type instead of feature capability), proving that mid-flight exploration is the only reliable way to measure task complexity.
*   If users report that the added 5-10 second latency before a command "actually starts doing work" creates a frustrating, unresponsive UX.
