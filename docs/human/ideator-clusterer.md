# ideator-clusterer

> Last updated: 2026-06-24
> Covers source: agents/ideator-clusterer.md

## Overview

`ideator-clusterer` is a read-only Haiku subagent used by `/z-brainstorm` wide mode after all ideator waves have completed. It reads the combined `BRAINSTORM.md`, receives the ordered `ideator_ids` array and total `n`, then collapses N peer five-section framings into K genuinely distinct directions by the core hypothesis / approach axis. It never picks a winner and never writes files; it returns structured text that the orchestrator folds into the Phase 3 ranked briefing.

The key output is an effective-diversity report: N, K, reduction, cluster labels, members, representative ideator, the representative's five-section framing reproduced verbatim, collapsed-framing explanations, cross-cluster consensus, and a short clusterer note. K may be 1; convergence is a signal, not a failure.

## Key entry points

- `agents/ideator-clusterer.md:1` — agent definition; `tools: Read, Grep, Glob`, `model: haiku`, read-only.
- `agents/ideator-clusterer.md:16` — caller inputs: `brainstorm_path`, `ideator_ids`, and `n`.
- `agents/ideator-clusterer.md:26` — procedure step 1: read all ideator framing blocks from `BRAINSTORM.md`.
- `agents/ideator-clusterer.md:38` — procedure step 2: distill a <=12-word approach axis per ideator.
- `agents/ideator-clusterer.md:44` — procedure step 3: group ideators into K clusters by shared architectural bet.
- `agents/ideator-clusterer.md:59` — effective-diversity report and cross-cluster consensus.
- `agents/ideator-clusterer.md:65` — required returned report structure.

## How it interacts with others

- `z-brainstorm` — sole dispatcher, from Phase 2c-5 after wide-mode base and overflow waves finish.
- `scope-reconciler-brainstorm` — sibling but not interchangeable; reconciler operates on HEAVY chunks, clusterer operates on peer framings for the same topic.
- `ideator agents` — clusterer consumes their outputs but does not re-dispatch or edit them.

## Edge cases / gotchas

- Every input ideator ID must appear either as a cluster representative or as a collapsed member; silent omission violates the agent contract.
- Representative framings must be reproduced verbatim; no lossy summarization.
- Do not over-split vocabulary differences that share the same architectural bet.
- Do not over-merge genuinely conflicting approaches.
- The cross-cluster consensus section is mandatory; emit `None detected.` if empty.
- Clusterer failure or `K=0` is non-fatal; `/z-brainstorm` falls back to N raw framings.
- The clusterer always runs on Haiku regardless of the wide overflow model.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/ideator-clusterer.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

- `N=5`, `K=2`: three framings collapse into a schema-first approach and two into a runtime-isolation approach; Phase 3 ranks two cluster directions instead of five raw outputs.
- `N=6`, `K=1`: all ideators converged on the same core bet; the briefing should present this as strong consensus.
