### D1: Output contract shape
**Recommendation:** **(b) Fenced JSON block** (`{ status, mode, axis, chunks: [] }`)
**Reasoning:** Since the output must contain structured data (an array of chunks with predicted costs and file examples), JSON is strictly required. Introducing a novel "hybrid" format violates the codebase's existing binary standard (either line-prefix or JSON) and adds unnecessary complexity; callers can simply use `jq` to extract top-level routing decisions instead of relying on `grep`.
**Interaction warnings:** Host command scripts (`/z-audit`, `/z-brainstorm`) must be updated to use `jq` for extracting routing variables like `STATUS` and `MODE` rather than relying on their legacy line-prefix grep logic.

### D2: SCOPE.json schema + location
**Recommendation:** **(c) Both (live namespaced + archived copy)**
**Reasoning:** Storing a live, namespaced file (e.g., `SCOPE-audit.json`) allows mid-flight agents to effortlessly consume the current execution context without deeply traversing the archive structure. Simultaneously, committing a snapshot to the `archive/$RUN/` directory is non-negotiable for preserving the project's strict audit trail and enabling the historical replay required by the calibration harness.
**Interaction warnings:** The orchestrator script must handle the synchronization (e.g., writing to live and copying to archive) to prevent state drift between the active run and the historical record. 

### D4: Axis discovery heuristics
**Recommendation:** **(c) Hybrid (caller-supplied taxonomy + structural-seam evidence)**
**Reasoning:** Allowing the LLM free-form axis generation risks hallucinating categories that downstream dispatchers cannot actually execute against. Constraining the model to a caller-supplied taxonomy ensures operational compatibility, while allowing the LLM to use structural evidence ensures the chosen axis is genuinely supported by the codebase's reality.
**Interaction warnings:** The host command must enforce a strict failure mode; if the LLM cannot justify any of the supplied taxonomy options based on the codebase evidence, the probe must fail loudly rather than defaulting to an arbitrary choice.

### D7: Calibration replay protocol
**Recommendation:** **(a) LLM-replay all 5-6 historical runs**
**Reasoning:** The primary objective of the calibration harness is to measure the actual semantic classification performance of the Haiku model, which deterministic heuristics simply cannot simulate. Given the very small historical sample size (5-6 runs) and Haiku's low token cost, a full LLM replay is empirically rigorous and highly cost-effective.
**Interaction warnings:** Full LLM replay requires D8's ground-truth rubric to be highly deterministic and pre-calculated so the harness can automatically score the Haiku outputs without human intervention.

### D8: Ground-truth label for calibration
**Recommendation:** **(c) Combined rubric (tasks_total + tasks_complexity + escalation events)**
**Reasoning:** Raw task counts fail to capture the severity or density of the work, and human escalation events are too sparse across historical runs to serve as a standalone baseline. A combined, mathematically documented scoring function synthesizes these disparate signals into an objective, reproducible LIGHT/MEDIUM/HEAVY truth value.
**Interaction warnings:** The exact scoring formula must be explicitly versioned alongside the calibration harness; any future tweaks to the weighting (e.g., changing how much `tasks_complexity` impacts the final score) will invalidate previous baseline runs.

---

### Cross-Cutting Concerns
- **Structured Predictability over Generative Flexibility:** Across D1 (JSON only), D4 (Taxonomy constraint), and D8 (Mathematical rubric), the prevailing theme is restricting the LLM's generative freedom to ensure it acts as a reliable, system-level primitive.
- **Tooling Consistency:** Recommending strict JSON for D1 necessitates that all host scripts rely on `jq`. This creates a cleaner boundary for data extraction but requires ensuring that bash orchestrators handle JSON parsing errors gracefully before delegating to the Phase 2 agents.
- **State Management:** D2 establishes a dual-write pattern that bridges the gap between the live agents (who need fast access to `SCOPE.json`) and the calibration harness (which relies on the archived snapshots approved in D7 and defined by D8).
