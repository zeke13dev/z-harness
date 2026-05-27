## Framing

This should be a **route-control primitive**, not a planning primitive. Its job is to take a unit of work, classify whether it should be split, escalated, fanned out, or reconciled, then hand off to existing z-commands without owning their domain logic. Treat it like a harness-level “control plane” for decomposition and escalation.

## Core hypothesis

The shared pattern is: **generate parallel bounded perspectives, measure escalation pressure, dispatch specialized workers, then reconcile artifacts into a canonical next artifact**. If extracted well, `z-plan-light`, `z-plan`, `z-plan-split`, `z-audit`, and `z-review-all` become thin command adapters over one primitive with pluggable axes: strategy, cluster, audit dimension, review scope, implementation track.

## Risks

- Over-abstracting could erase useful command-specific judgment, especially around `FIX.md` versus `SPEC/PLAN/TASKS.md`.
- A generic reconciler may mishandle heterogeneous artifacts unless each command supplies a strict merge contract.
- Automatic escalation can become noisy if thresholds are global instead of command-local.
- Subagent dispatch from inside the primitive risks hiding route history and making ping-pong harder to debug.
- If the primitive owns too much, failures become opaque: users see “fanout failed” instead of “auditor dimension X exceeded HIGH threshold.”

## Plan implications

- Define a small library-level contract first: `fanout_axis`, `branch_prompt`, `thresholds`, `dispatch_target`, `artifact_schema`, `reconcile_fn`, `route_chain`.
- Keep command-specific adapters responsible for thresholds and artifact semantics.
- Make reconciliation main-orchestrator only; subagents produce evidence and candidate artifacts, never commit canonical outputs directly.
- Use route-chain metadata everywhere to prevent command ping-pong.
- Start by extracting threshold/escalation bookkeeping before extracting prompt generation or reconciliation.

## What would change my mind

- If `z-audit` and `z-plan-split` reconciliation differ too much in artifact shape, this should be two primitives: `fanout-review` and `fanout-plan`.
- If route decisions require substantial semantic judgment each time, keep escalation as command-local policy with only shared telemetry helpers.
- If implementation complexity exceeds the duplicated code it removes, prefer a documented pattern plus tiny shared utilities.
- If users need highly visible command-specific behavior, a hidden generic primitive may reduce debuggability more than it improves reuse.
