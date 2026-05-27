## Framing

The z-harness today is a collection of commands that each re-implement the same three-phase lifecycle: *fan out* (spawn N parallel subagents along some axis), *gate* (check outputs against thresholds and optionally escalate to a heavier command), and *reconcile* (merge heterogeneous artifacts from different branches into a coherent output consumed downstream). The code surface is command-local — z-audit hard-codes auditor dimensions, z-brainstorm hard-codes ideator count and vendors, z-implement-all hard-codes task tracks. The proposal is to extract a `z-fanout` primitive that makes this lifecycle a first-class, parameterizable abstraction, and to hang the escalation ladder and reconciliation contract on that primitive rather than re-deriving them per command.

## Core hypothesis

A single **`fan-out-gate-reconcile` (FGR) primitive** — implemented as a reusable script library (`scripts/fanout.sh` + `scripts/reconcile.sh`) or a thin agent spec (`agents/fanout-orchestrator.md`) — can subsume all existing fan-out patterns without losing command-specific logic. The primitive's three parameters are: (a) a *strategy axis* (the dimension set to fan out along: dimensions, vendors, tasks, clusters), (b) a *gate spec* (a threshold table mapping signal names to escalation targets), and (c) a *reconciliation contract* (a typed merge strategy per artifact kind: findings-merge, cross-LLM-dedup, task-append, delta-patch). Every existing command becomes a thin wrapper that defines its axis + gate + contract and delegates the rest to the primitive. Escalation stops being ad-hoc `if [ $HIGHS -gt 10 ]; then` and becomes a declarative routing table the primitive enforces uniformly.

## Risks

- **Over-abstraction tax.** Each current command's gate logic encodes domain semantics (z-audit's 10-HIGH threshold is meaningful for code quality; z-plan-light's 5-file threshold is a complexity proxy). Forcing them into a generic gate-spec table may obscure the semantics and make each command harder to read in isolation. This is the "leaky abstraction" risk: the primitive must be transparent enough that command authors can still reason about their specific thresholds.
- **Reconciliation contract heterogeneity is load-bearing.** The existing merge patterns are NOT interchangeable — z-audit does cross-LLM dedup+scoring, z-brainstorm does anti-bias synthesis, z-implement-all does cross-task notes threading. A generic "reconcile" function that handles all these correctly requires a plugin/dispatch mechanism, which may end up being as complex as the current per-command logic.
- **Escalation ladders have different targets per command.** z-plan-light escalates to z-plan; z-audit escalates to z-plan-with-escalation.md; z-do escalates to z-plan-light; z-debug escalates to z-plan. A unified escalation table requires a complete route-graph which doesn't yet exist and could create circular escalation risks.
- **Testing surface explodes.** Today each command's failure modes are isolated. If a bug in the FGR primitive affects reconciliation logic, it silently corrupts the output of every command that uses it.
- **The "strategy axis" abstraction may be wrong.** z-brainstorm fans out along *vendor*, z-audit along *quality dimension*, z-implement-all along *task dependency graph*. These are structurally different axes — vendor fan-out is symmetric and bias-prone; task fan-out is dependency-constrained and sequential within clusters. Forcing them into the same abstraction may require so many special-casing hooks that the primitive becomes a framework tax.

## Plan implications

- The primitive should be implemented as a **Bash script library** (not a new agent spec), since the fan-out dispatch is already orchestrated from the main thread in each command. A library means command files `source scripts/fanout-lib.sh` and call `z_fanout_dispatch`, `z_fanout_gate`, `z_fanout_reconcile` with their parameters.
- The escalation table should live in a **per-command `ESCALATION_SPEC` env block** (not in a central registry), so each command's escalation logic remains co-located with its other thresholds.
- Reconciliation contracts should be **typed merge-strategy names** (`dedup-score`, `anti-bias-merge`, `task-append`, `delta-patch`) with a dispatch table in the library — new strategies can be registered without modifying existing commands.
- The plan must include a *migration* path: z-audit and z-brainstorm refactored to use the primitive first (simplest cases), then z-implement-all (most complex, task-graph-constrained) last.
- A gate-spec format (YAML or structured env) needs to be standardized before any refactoring begins — this is the load-bearing decision.

## What would change my mind

- If a survey of the actual command files shows that the shared code surface is less than ~30% of each command's total logic, the abstraction may not pay off — the overhead of maintaining the primitive would exceed the deduplication gain.
- If the reconciliation contracts for z-audit (dedup+score) and z-brainstorm (anti-bias synthesis) turn out to require fundamentally different data structures as inputs (not just different merge strategies on the same shape), that kills the "typed merge-strategy" approach and suggests the primitive should only cover fan-out dispatch + escalation gating, not reconciliation.
- If z-implement-all's task-graph fan-out (dependency-constrained, sequential within clusters) cannot be modeled as a strategy-axis parameter without adding >2 special-case hooks to the primitive, I would scope the primitive to exclude z-implement-all and target only the review/audit/brainstorm family.
