# ideator-clusterer

> Last updated: 2026-06-19
> Covers source: agents/ideator-clusterer.md

## Overview

`ideator-clusterer` is a read-only Haiku subagent dispatched by `/z-brainstorm` during wide-mode runs (when `WIDE_N > 3`). After all ideator waves have written their framing blocks to `BRAINSTORM.md`, the clusterer reads those N blocks and collapses them into K genuinely distinct directions by identifying each ideator's core hypothesis / approach axis. It returns a structured text report — K cluster labels with member ideators and one verbatim representative framing per cluster, a collapsed-framing explanation, cross-cluster consensus findings, and a meta-observation paragraph. The orchestrator uses this output to present K cluster directions in the Phase 3 ranked briefing rather than N raw framings.

The agent lives in `agents/ideator-clusterer.md` and runs exclusively on Haiku regardless of the `brainstorm.wide_overflow_model` config knob. It performs no file writes and issues no shell commands. Its sole output is structured text returned directly to the `/z-brainstorm` orchestrator, which stores it in `CLUSTER_REPORT`, `CLUSTER_K`, and `CLUSTER_BLOCKS` for Phase 3 consumption. If the clusterer fails or returns K=0, the orchestrator falls back to presenting all N raw framings in the briefing — the command never halts on clusterer failure.

## Key entry points

- `agents/ideator-clusterer.md:1` — `ideator-clusterer` — YAML-fronted Haiku agent definition; declares `tools: Read, Grep, Glob` and `model: haiku`.
- `agents/ideator-clusterer.md:27` — `clustering procedure` — Five-step procedure: (1) read N framing blocks from `brainstorm_path`; (2) distill a ≤12-word approach axis per ideator; (3) cluster into K groups with label, members, representative; (4) compile effective-diversity report and cross-cluster consensus; (5) return the structured report text.

## How it interacts with others

- `z-brainstorm` — The sole dispatcher. Calls this agent at Phase 2c-5 after all wide-mode waves complete. Passes `brainstorm_path`, `ideator_ids` (JSON array), and `n`. Extracts K and `CLUSTER_BLOCKS` for Phase 3 ranked briefing; sets `CLUSTER_K=0` as failure sentinel.
- `agents` — This concept is listed as a member of the agents registry concept (`agents/ideator-clusterer.md` appears in the agents INDEX entry). Shares the same agent dispatch mechanism as all other z-harness subagents.
- `scope-reconciler-brainstorm` — A sibling agent with a superficially similar read-then-return pattern, but operating on the **chunk axis** (HEAVY mode, per-sub-topic framing merge + anti-bias audit). The two agents must NOT be reused for each other's role.

## Edge cases / gotchas

- Every ideator ID supplied in `ideator_ids` must appear either as a cluster representative or in the "Collapsed framings" section. Silent omission is a spec violation.
- The representative framing is reproduced **verbatim** — no lossy summarization. Paraphrasing introduces bias.
- K=1 is a valid and useful result (strong consensus signal); the agent must not artificially inflate K to appear to have found diversity.
- The "Cross-cluster consensus" section is mandatory even when findings are empty; the agent must emit "None detected." rather than omitting the section.
- The clusterer never picks or recommends a framing — ranking and selection is strictly the orchestrator's responsibility in Phase 3.
- `OVERFLOW_MODEL` (the `brainstorm.wide_overflow_model` config knob) applies only to Claude-family overflow ideator slots. The clusterer itself always runs at Haiku.
- Maximum wide-mode overflow cap: 3 overflow waves regardless of `WIDE_N`, capping total ideators at 9. Requests for N > 9 are silently capped.
- If dispatched from a non-supporting driver (cursor, codex flat mode), the `RUNTIME-GATE: subagent` comment in z-brainstorm.md instructs those drivers to skip the clusterer Agent() call and fall back to N raw framings.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/ideator-clusterer.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

- Narrow-mode run (`WIDE_N = 3`): clusterer is NOT dispatched; Phase 3 uses three raw framings directly.
- Wide-mode run (`WIDE_N = 5`): clusterer dispatched with `n=5` and five ideator IDs. Returns K=2 clusters (three framings converged on "event-sourcing pipeline", two on "CRUD-first incremental"), plus cross-cluster consensus that all five framings agree the current schema is the bottleneck. Phase 3 ranked briefing presents 2 directions instead of 5.
- Clusterer failure: `CLUSTER_K` set to 0; Phase 3 falls back to presenting all N raw framings. `/z-brainstorm` continues normally — clusterer failure is not a halt condition.
