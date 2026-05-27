## 1. Framing

The recurring pattern is not "parallelism." It is a **bounded decomposition transaction**: break one ambiguous objective into independent branches, execute each branch with command-specific workers, then reconcile outputs under explicit escalation rules.

The reusable primitive should be a **harness kernel**, probably a script-lib plus thin skill wrapper, not a new user-facing z-command. Skills should describe policy; scripts should enforce invariants: branch manifests, thresholds, event logging, artifact collection, retry semantics, and reconciliation envelopes.

## 2. Core hypothesis

Create a primitive like `fanout_reconcile_run` with five pluggable contracts:

1. **Axis generator**: produces branches along a strategy, dimension, cluster, task, or idea axis.
2. **Escalation policy**: file count, findings count, severity count, attempts, wall time, decision count, drift, overlap, stall.
3. **Branch dispatcher**: maps each branch to a z-command, agent, or script.
4. **Artifact schema adapter**: normalizes heterogeneous outputs into findings, tasks, notes, routes, patches, or plans.
5. **Main reconciler**: runs only in the orchestrator, never in branch agents, and performs dedup, scoring, promotion, escalation artifact creation, and atomic writes.

The primitive units unit of work should be a **branch record**, not a subagent call:

```json
{
  "branch_id": "audit-security",
  "axis": "dimension",
  "intent": "Audit auth/session risks",
  "dispatcher": "z-audit-dimension",
  "inputs": {},
  "thresholds": {},
  "expected_artifacts": ["findings-security.md"],
  "status": "pending"
}
```

## 3. Risks

The biggest risk is over-abstracting away the parts that make each command good. `/z-brainstorm` wants diversity and bias checks. `/z-audit` wants severity discipline. `/z-implement-all` wants task settlement and retry controls. A primitive that tries to own all domain logic will become a second orchestration language.

The second risk is **hidden state coupling**. Today's fresh-context branches are clean. A reusable primitive must preserve that by passing immutable branch inputs and collecting explicit artifacts only.

The third risk is artifact impedance mismatch. Brainstorm sections, audit findings, research citations, implementation diffs, and split-plan manifests are not naturally the same shape. The primitive should normalize metadata and lifecycle, not force all content into one schema.

## 4. Plan implications

The right extraction boundary is likely:

- `scripts/lib/fanout.sh` or `scripts/lib/fanout.py` for branch lifecycle, logging, thresholds, temp dirs, and atomic settlement.
- Command-local adapters for `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-audit`, `/z-review-all`.
- A small shared artifact envelope: `branch.json`, `result.json`, `events.jsonl`, `artifacts/`.
- A shared escalation artifact format: `escalation.md` plus machine-readable `escalation.json`.
- A reconciliation API that receives all branch results at once; no branch should mutate global plan files directly.

Do not start by extracting `/z-implement-all`; it has the most mature but also most specialized semantics. Start with `/z-audit` plus `/z-brainstorm` because they expose the cleanest common shape: fan-out, collect files, reconcile, possibly escalate.

## 5. What would change my mind

If the existing commands mostly differ in shell ceremony rather than behavior, a script-lib extraction is enough.

If branch outputs cannot be normalized without losing important command semantics, this should stay as duplicated skill patterns plus shared helper scripts for only logging, thresholds, and atomic writes.

If users need to invoke this directly, then it is not a primitive; it is a new command. In that case the design should become `/z-decompose` or `/z-fanout`, with explicit modes, rather than a hidden reusable layer.
