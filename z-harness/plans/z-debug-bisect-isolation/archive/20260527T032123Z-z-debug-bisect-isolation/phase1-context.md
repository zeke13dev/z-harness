# Phase 1 context — z-debug bisect-isolation

## Problem statement
`/z-debug` currently runs a heavy hypothesis-tournament loop for every bug, even when the bug is a clean regression with a known-good ref. For regressions, `git bisect` against a failing-test/repro-script is mechanically guaranteed to identify the offending commit and the exact line-level diff — no LLM reasoning required. Today the orchestrator burns ~5 cycles × 3 LLMs × hypothesis generation to converge on what bisect would have located deterministically in a few build/test runs. Worse, the hypothesis loop can converge on a plausible-but-wrong root cause when the actual offender is a one-line change in an unrelated commit on the same branch.

## Context
- `/z-debug` is a 10-phase pipeline; Phase 1 already captures "When did this start?" → `Started:` field in DEBUG.md (last-good ref or "unknown"). Phase 2 confirms repro reliability. Phase 3a–6 are hypothesis generation + tournament. (commands/z-debug.md:64–319)
- Existing Haiku subagents follow a consistent shape: YAML frontmatter (`name`, `description`, `tools`, `model: haiku`), refusal checks, explicit STATUS return contract (e.g. `STATUS: ok | failed | refused`), telemetry start/end events. (agents/doc-fetcher.md, agents/remote-runner.md)
- The agent should be mechanical, not interpretive — same boundary as `remote-runner` (refuses interpretive work, returns raw output for the caller to reason about).
- `git bisect run <script>` is the standard non-interactive bisect path: script exits 0 = good, non-zero = bad, exit 125 = skip. This is exactly what a Haiku can drive without LLM judgment.

## Where it slots into /z-debug
**New Phase 2.5 — Regression bisect (conditional)**, between Phase 2 (Repro + Evidence Inventory) and Phase 3a (Round 1 hypotheses). Gated on:
1. `Started:` field from Phase 1 ≠ "unknown" (user supplied last-good ref/commit/tag).
2. Phase 2 confirmed repro is reliable (`Reproducibility confirmed: yes` — not partial/no).
3. The repro is scriptable (a command that exits 0/non-zero deterministically).

If gate passes → dispatch `bisect-isolator` (Haiku). On success, the offending SHA + line-level diff is appended to the Evidence Inventory as a high-confidence EVID-NNN entry tagged `source: bisect`, and Phase 3a hypotheses are seeded with strong prior weight toward "the changes in `<sha>` caused the regression."

If gate fails or bisect returns `bisect_unusable` → skip the phase entirely; proceed to Phase 3a unchanged. Bisect never blocks the pipeline — it's a fast-path, not a gate.
