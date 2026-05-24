# Phase 3 — Decisions final (post-consult)

## D2 — FLIPPED from tentative: **Single `DEBUG.md`**

Tentative was new `MATRIX.md` markdown-only. **Flipped** because Gemini correctly pointed out that BRAINSTORM.md's User choice section explicitly specifies "Single DEBUG.md with sections: Problem, Evidence Inventory, Hypothesis Pool, Test Matrix, Experiment Log, Score Updates, Eliminated Alternatives, Root Cause, Fix Plan, Verification, Post-mortem." I missed that in the original drafting; the user already approved unified DEBUG.md.

**Final:** `z-harness/<slug>/DEBUG.md` is the single artifact for `/z-debug`, with the section list above. Today's PROBLEM/EVIDENCE/ISOLATION/FIX/POSTMORTEM are all merged into this one file as sections.

**Context-hygiene mitigation (from Gemini):** when a subagent (Round 2 critique or fix consult) is dispatched, the orchestrator extracts ONLY the relevant section(s) into the prompt — never the full DEBUG.md. Default extraction map: Round-2 LLMs see `Hypothesis Pool` + `Test Matrix` + `Experiment Log`; fix consult sees `Root Cause` + `Experiment Log`.

## D3 — Codex's revised table

Adopt Codex's two cell tweaks: `high + inconclusive → high` (not `med`) and `med + strongly_supported → very_high` (not `high`). Principle: a single low-prior hypothesis with strong evidence should beat a high-prior hypothesis with inconclusive evidence; consensus is not truth.

**Final table:**

| prior \ likelihood | strongly_falsified | weakly_falsified | inconclusive | weakly_supported | strongly_supported |
|---|---|---|---|---|---|
| **high** (overlap=3) | eliminated | low | high | high | very_high |
| **med** (overlap=2) | eliminated | very_low | med | high | very_high |
| **low** (overlap=1) | eliminated | very_low | low | med | high |

**Posterior order (high → low):** `very_high > high > med > low > very_low > eliminated`.

**Likelihood-assignment rule (Gemini, adopted):** LLMs set the PRIOR by their independent generation overlap. Only the ORCHESTRATOR reads raw test output and assigns the likelihood bucket. This breaks the D3↔D4 entanglement (no per-LLM likelihood vote, no consensus bottleneck). Orchestrator logs which DEBUG.md row + which test result drove each likelihood assignment.

## D4 — 3 LLMs (Claude + Codex + Gemini) with checkpoint

Accepted. The 3-source overlap is what gives the prior bucket its three-bucket resolution (`3→high, 2→med, 1→low`). Reducing to 2 LLMs would collapse priors to binary and break the D3 table.

**Contamination mitigation:** Round 1 orchestrator hypothesis block is **written to a checkpoint file BEFORE dispatching the parallel Codex+Gemini calls**, and is NOT re-read after. Path: `z-harness/<slug>/archive/<run>/round1-orchestrator.md`. Subagents never see it. Orchestrator's "merge into Hypothesis Pool" step reads from disk, not from prior conversation state.

## D5 — Two new consultant modes

Accepted. Both new modes added to `agents/codex-consultant.md` AND `agents/gemini-consultant.md` (mirrored):

- **`generate-hypotheses-round1`** — independent generation, no other-model context. Returns ordered hypothesis list, each row: `{claim, prediction_if_true, prediction_if_false, discriminating_test, test_cost: free|cheap|medium|expensive, parallel_safe: bool, reasoning}`. Tagged `schema_version: hypothesis_round1_v1`.
- **`generate-hypotheses-round2-adversarial`** — given the merged Hypothesis Pool from Round 1, returns TWO sections: (a) NEW hypotheses (failure modes conspicuously absent), (b) CRITIQUES of existing rows (which discriminating tests are non-discriminating, which are not parallel-safe but tagged as such, which hypotheses overlap with another's claim and should be merged). Tagged `schema_version: hypothesis_round2_v1`. Return raw (no wrapper).
- Round-2 prompt MUST explicitly forbid "just agreeing with Round 1" (Gemini's risk note) — the prompt template says: "Do not return rows that merely restate existing Pool entries. Your value here is orthogonality, not endorsement."

The existing `debug-hypotheses` mode is retained for `/z-fix`-style ranking (and possibly for the merged-pool re-ranking step inside `/z-debug` if needed).

## D8 — Optional post-mortem, default-off, with auto-suggest

Accepted. `/z-fix` Phase 9 asks via `AskUserQuestion`: "Write post-mortem?" (default = no). 

**Auto-suggest trigger (Gemini):** if Phase 8 Codex review needed >1 retry cycle, change the default to YES and add the line: "Review cycles: <N>. Suggesting post-mortem — simple fix may have been subtler than expected."

## Shortcuts taken

None. All five decisions resolved to robust calls; the only deviation from the tentatives was D2, which was a fix to align with BRAINSTORM (not a shortcut).

## Locked decision interactions

- **D3 + D4 + likelihood-assignment** are a single coherent system: 3 LLMs vote priors → orchestrator alone interprets results to assign likelihoods → revised table maps prior×likelihood to posterior.
- **D2 + D5:** unified DEBUG.md must include a designated `Hypothesis Pool` section keyed by hypothesis ID; Round 2 mode contract references that section by name.
- **D8 split:** the optional-vs-required post-mortem is the primary behavioral difference between `/z-fix` and `/z-debug`. The command-help text for each should reference the other ("for unknown root cause use `/z-debug`" / "for known cause use `/z-fix`").
