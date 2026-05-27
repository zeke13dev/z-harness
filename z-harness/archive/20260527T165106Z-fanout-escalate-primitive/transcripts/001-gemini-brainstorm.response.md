Warning: 256-color support not detected. Using a terminal with at least 256-color support is recommended for a better visual experience.
Ripgrep is not available. Falling back to GrepTool.
### 1. Framing
The "Fanout-Escalate-Reconcile" (FER) Primitive. Rather than treating parallel ideation, auditing, and multi-track implementation as distinct workflows, we extract them into a generalized, MapReduce-like orchestration layer. This primitive acts as a universal pipeline that standardizes context partitioning (fan-out along a defined axis), circuit-breaking via hard/soft thresholds (auto-escalate), and context distillation (reconciliation). It relegates the specific business logic—whether evaluating complexity limits, auditing security, or drafting plans—into thin strategy configurations.

### 2. Core hypothesis
The cognitive overhead, context limits, and scope creep associated with complex LLM tasks necessitate a unified mechanism for containment and synthesis. Currently, every `z-*` command reinvents its own parallel dispatch, state tracking, and failure recovery. A single, composable primitive will drastically reduce boilerplate, enforce rigorous, uniform cost containment across the entire `z-harness` suite, and guarantee that anti-bias and cross-LLM critique behaviors are universally applied rather than ad-hoc. 

### 3. Risks
*   **Over-abstraction:** We risk building a generic, sluggish "workflow engine" that forces overly rigid schemas, obscuring the nuanced, domain-specific reconciliation required for tasks like merging dependent code patches versus merging abstract architectural ideas.
*   **Context Dilution:** A generic fan-in step might aggressively summarize heterogeneous artifacts to fit context windows, inadvertently flattening the critical, divergent ideas that specialized anti-bias merges are designed to protect.
*   **State Machine Hell:** Managing sequential retries, cross-task notes, and asynchronous halts within a generalized DAG could introduce opaque race conditions that are significantly harder to debug than the current siloed, command-specific scripts.

### 4. Plan implications
*   **Command Hollowing:** Monolithic agents like `z-plan`, `z-audit`, `z-brainstorm`, and `z-review-all` would be gutted. They would transition into declarative configurations (or very thin prompt wrappers) specifying the fan-out axis, the precise escalation triggers, and the reconciliation strategy.
*   **New Core Engine:** Introduction of a central `orchestrator` (likely a script library paired with a router agent) strictly responsible for dispatching subagents, tracking state via `events.jsonl`, evaluating circuit breakers, and triggering the final merge step.
*   **Artifact Standardization:** All subagent branches would be forced to emit artifacts adhering to a strict, parseable envelope (e.g., structured JSON alongside markdown) to allow the generic orchestrator to predictably handle deduping, cost-gating, and merging.

### 5. What would change my mind
*   If mapping the domain-specific thresholds (e.g., "3 modified files" vs "10 CRITICAL findings") into a generic configuration schema becomes as complex and error-prone as writing the bespoke orchestration scripts.
*   If we discover that the reconciliation phase is inherently too coupled to the task; for instance, if safely merging architectural plans requires a fundamentally different contextual awareness than deduping audit findings, making a shared primitive useless.
*   If enforcing a universal artifact schema on all parallel branches restricts the natural, unstructured reasoning capabilities of the subagents, leading to a measurable drop in output quality.
