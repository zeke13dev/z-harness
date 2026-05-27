# Phase 1 Scaffolding — fanout-escalate-primitive

**input_hash:** f4e108675edd6cca

## Framing
The "Fanout-Escalate" (FOE) pattern is the architectural backbone for managing complexity in `z-harness`, but it is currently implemented redundantly and inconsistently across `z-audit`, `z-brainstorm`, `z-plan-split`, and `z-implement-all`. These commands all struggle with the same "orchestration tax": managing parallel subagent lifecycles, monitoring safety/cost guardrails (bailouts), and synthesizing heterogeneous outputs into a unified artifact. Extracting this into a unified primitive moves the system from procedural, error-prone shell/markdown logic to a declarative orchestration model.

## Core hypothesis
A unified `FanoutEngine` (implemented as a Python script-lib or specialized "Orchestrator" agent) can handle the heavy lifting of parallel dispatch and threshold monitoring via a standardized `fanout_spec`. This primitive would provide:
1. **Diverse Dispatch**: Single-command spawning of N parallel, vendor-diverse subagents with shared or sharded scaffolding.
2. **Deterministic Bails**: Hard-coded escalation thresholds (finding counts, cost ceilings, or scope "smell") that automatically emit a standardized `ESCALATION.md` for handoff.
3. **Pluggable Synthesis**: A library of reconciliation strategies (e.g., cross-LLM anti-bias merge, finding-deduplication, or path-overlap detection) that allows commands to define *how* to merge without managing *how* to loop.

## Risks
*   **The Synthesis Trap**: While dispatch is easy to generalize, reconciliation is highly domain-specific (e.g., audit finding promotion vs. brainstorm idea synthesis). A "one size fits all" merger might lose the nuance required for high-signal artifacts.
*   **Abstraction Leakage**: If the primitive hides subagent prompts or context-sharding logic too deeply, debugging "why an ideator failed" becomes significantly harder than in the current transparent shell scripts.
*   **Main-Thread Bloat**: Centralizing the orchestration into a single Python process could create a context/memory bottleneck if the "synthesis" phase requires re-reading massive amounts of sharded subagent output.

## Plan implications
*   **Creation of `scripts/fanout.py`**: A core utility that accepts a JSON/YAML spec for N branches, thresholds, and a synthesis strategy.
*   **Standardized Escalation Artifacts**: Unified `ESCALATION.md` and `BAILOUT.md` formats that all FOE-compliant commands use to route to `/z-plan`.
*   **Command Refactoring**: Slimming down `z-audit.md` and `z-brainstorm.md` by ~40% by offloading the parallel loop and "anti-bias" logic to the primitive.
*   **Handoff Protocols**: Defining how a "failed" or "bailed" fan-out run preserves enough evidence for the next tier (e.g., `/z-plan`) to resume without re-running the expensive discovery phase.

## What would change my mind
*   **Synthesis Uniqueness**: If the "Reconciliation" logic for each command remains >70% custom code, the primitive is just a thin wrapper over a `for` loop and isn't worth the abstraction.
*   **Planning-Router Evolution**: If the existing `planning-router` can be evolved to handle "Active Routing" (not just advising a command, but orchestrating the fan-out itself), then a separate "FOE primitive" is redundant.
*   **Handoff Latency**: If the "Reconciliation" step adds significant wall-clock time compared to the current "fast-path" shell scripts, the "Cheap" design goal of commands like `z-brainstorm` is compromised.
