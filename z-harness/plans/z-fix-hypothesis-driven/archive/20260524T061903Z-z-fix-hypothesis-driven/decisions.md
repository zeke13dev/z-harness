# Decisions — z-fix-hypothesis-driven

Five **consult-flagged** decisions (the cap). Remaining decisions documented as obvious calls.

---

## D1: Command split granularity — SEPARATE commands (obvious, locked in BRAINSTORM)

**Decision:** Two distinct user-facing commands, `/z-fix` (light) and `/z-debug` (heavy hypothesis tournament).

**Tentative call:** Separate. Matches `/z-plan` vs `/z-plan-light` pattern; matches user's saved "explicit commands over auto-detected modes" preference.

**Consult?** No — explicit BRAINSTORM choice.

---

## D2: Hypothesis-matrix artifact (name, location, format) — CONSULT

**Decision:** How does the tournament's hypothesis matrix get persisted?

**Options:**
- **(A) New `MATRIX.md`** alongside existing PROBLEM/EVIDENCE/ISOLATION docs, markdown table format.
- **(B) Extend `ISOLATION.md`** with a top-section table; each cycle still appends below.
- **(C) Single `DEBUG.md`** that subsumes PROBLEM/EVIDENCE/ISOLATION/FIX (per Gemini ideator's framing).
- **(D) Markdown table + JSON sidecar** (`MATRIX.md` + `matrix.json`) so future tooling can parse without regex.

**Tentative call:** **(A) new `MATRIX.md`, markdown table only.** Preserves the existing artifact set (no migration cost for the current `/z-debug` archive layout); markdown table is human-readable; no other command parses it so JSON sidecar would be ceremony.

**Consult?** Yes. **Trigger:** names a new artifact on the command surface; hard to rename later; affects all downstream tooling (`/z-maintain-docs` audits, archive inspection).

---

## D3: Posterior-bucket lookup table — CONSULT

**Decision:** Exact prior × likelihood → posterior mapping. The fix-gate ("winning hypothesis has highest posterior") depends on this table being unambiguous.

**Tentative table (5 priors × 5 likelihoods → ordinal posterior):**

| prior \\ likelihood | strongly_falsified | weakly_falsified | inconclusive | weakly_supported | strongly_supported |
|---|---|---|---|---|---|
| **high** (overlap=3) | eliminated | low | med | high | very_high |
| **med** (overlap=2) | eliminated | very_low | low | med | high |
| **low** (overlap=1) | eliminated | very_low | very_low | low | med |

**Posterior ordering (high → low):** `very_high > high > med > low > very_low > eliminated`.

**Tentative call:** Above table. Rules: `strongly_falsified` always eliminates regardless of prior (a clean falsification overrides any consensus). `inconclusive` preserves prior but cannot push to `very_high`. `strongly_supported` can promote any prior up by 2 buckets.

**Consult?** Yes. **Trigger:** algorithmic choice with materially different tradeoffs across candidates; hard to revise once `/z-debug` runs are in the archive citing posteriors.

---

## D4: Tournament cardinality — 2 LLMs or 3? — CONSULT

**Decision:** Does the hypothesis tournament use **two** independent ideators (Codex + Gemini) or **three** (orchestrator-Claude + Codex + Gemini)?

**Options:**
- **(A) 3 LLMs.** Orchestrator (Claude, main thread) writes its own hypothesis block in P3a alongside dispatching Codex+Gemini in parallel. Overlap_count denominator = 3.
- **(B) 2 LLMs.** Only Codex+Gemini generate; orchestrator is purely a coordinator. Overlap_count denominator = 2.
- **(C) 2 LLMs but Claude-as-judge.** Codex+Gemini generate; orchestrator merges and adds *missed* hypotheses only if both consultants failed to surface something obvious.

**Tentative call:** **(A) 3 LLMs.** Free token-wise (orchestrator is already in main context with full evidence); meaningfully increases diversity; matches BRAINSTORM's "Claude / Codex / Gemini each independently propose 3–5" wording. The trap to avoid: orchestrator generating its block AFTER seeing the dispatch returns (cross-contamination). Mitigation: orchestrator writes its block to a checkpoint file BEFORE dispatching the parallel agents.

**Consult?** Yes. **Trigger:** algorithm choice with diversity/contamination tradeoffs; affects the overlap_count denominator and thus the prior-bucket thresholds in D3.

---

## D5: New consultant modes — CONSULT

**Decision:** Add new modes to `codex-consultant` and `gemini-consultant`, or overload existing `debug-hypotheses`?

**Options:**
- **(A) Two new modes.** `generate-hypotheses-round1` (independent generation, no context from other models) and `generate-hypotheses-round2-adversarial` (given other models' lists, hunt missing failure modes + critique discriminating tests). Existing `debug-hypotheses` retained for `/z-fix`-style ranking calls if needed.
- **(B) One new mode** `hypothesis-tournament` parameterized by `round: 1 | 2` inside the prompt body. Lower agent-file surface area.
- **(C) Reuse `debug-hypotheses`** with the caller swapping the body. No agent-file change.

**Tentative call:** **(A) Two new modes.** Different return shapes per round: R1 returns a clean hypothesis list (5-section per hypothesis: claim / prediction_if_true / prediction_if_false / discriminating_test / test_cost). R2 returns *additions* (new hypotheses) + *critiques* (rows to weaken/drop with reason). Forcing this into one mode hides the contract divergence. Existing `debug-hypotheses` stays — it can still be useful for ad-hoc ranking.

**Consult?** Yes. **Trigger:** changes the public mode contract on TWO agents; reversibility = >1 hour (touches all callers); naming choices are permanent.

---

## D6: Outlier carve-out count — top 2 (obvious)

**Decision:** How many unique-to-one-model (overlap=1) hypotheses are force-included in the test order?

**Tentative call:** **Top 2** (selected by orchestrator judgment within the overlap=1 cohort). One feels too brittle; three competes with the consensus rows for test-budget.

**Consult?** No — symmetric, small-stakes, easy to revise.

---

## D7: Isolation cycle cap — 5 (obvious)

**Decision:** Heavy-path cap. BRAINSTORM said 3–5.

**Tentative call:** **5.** This IS the heavy path; the whole point is more rounds when needed. Soft warning at cycle 3, hard halt at 5.

**Consult?** No.

---

## D8: `/z-fix` post-mortem requirement — CONSULT

**Decision:** Does `/z-fix` (the light path) require POSTMORTEM.md?

**Options:**
- **(A) Required (same as today's `/z-debug`).** Discipline is the whole point.
- **(B) Optional (`AskUserQuestion` at end).** Skip for typo-class fixes.
- **(C) Not required.** `/z-fix` is just `/z-plan-light` re-skinned for bugs; if you want post-mortem discipline, use `/z-debug`.

**Tentative call:** **(B) Optional, default-off.** Forcing a post-mortem on every typo-fix is the ceremony failure mode BRAINSTORM explicitly named. Offering it as a one-line `AskUserQuestion` at the end preserves the option for the user when the fix turned out to be subtler than they thought.

**Consult?** Yes. **Trigger:** affects the discipline/ceremony tradeoff which is the central tension of the split; reversibility = >1 hour (changes user habit).

---

## D9: Early-gate placement (obvious)

**Decision:** Where does "wrong tool" recommendation live in each command?

**Tentative call:** **P0 (premise check)**. `/z-fix` premise check asks "do you already have a hypothesis?" — if no, recommend `/z-debug`. `/z-debug` premise check asks "do you already know the cause?" — if yes, recommend `/z-fix`. Both gates are one `AskUserQuestion`, default = continue.

**Consult?** No.

---

## D10: `/z-debug` auto-bail thresholds (obvious — soften)

**Decision:** Today's `/z-debug` auto-bails on >5 files OR multi-module OR architectural. Should the heavy path soften?

**Tentative call:** **Soften to "multi-module / architectural / new public surface only."** Drop the >5-files trigger — the heavy path is meant for harder bugs. Cycle cap moves to 5 (per D7). File-count is no longer a bail criterion in `/z-debug`. `/z-fix` retains the >5-files bail (still escalates to `/z-debug`).

**Consult?** No — straightforward implication of the split.

---

## D11: Round-2 prompt shape — both orthogonality AND test-quality (obvious)

**Decision:** Already locked in BRAINSTORM User choice — round 2 asks for BOTH missing failure modes AND test-quality critique.

**Consult?** No.

---

## D12: MATRIX.md row format (obvious)

**Decision:** Schema per row.

**Tentative call:** Markdown table columns: `# | claim | proposed_by | overlap | test | cost | parallel | prior | last_result | posterior | status`. Plus a `## Cycle N` log section below the table with per-experiment narrative.

**Consult?** No.

---

## D13: Implementation dispatch (obvious — keep inline)

**Decision:** /z-debug Phase 6 inlines fix implementation today. Keep?

**Tentative call:** Keep inline (same as `/z-plan-light` Phase 7). Heavy planning is the cost; implementation is small after the funnel.

**Consult?** No.

---

## D14: docs/llm/ refresh (obvious)

**Decision:** Update `docs/llm/INDEX.json` + `docs/llm/commands.json` + `docs/llm/agents.json` + create `docs/llm/z-fix.json` manually in this run, or defer to `/z-maintain-docs`?

**Tentative call:** Manual in this run. The new command won't be discoverable to future doc-fetcher calls until indexed; deferring leaves a known-stale gap. `/z-maintain-docs` can verify later.

**Consult?** No.

---

## Summary

**Consult-flagged (5/5):** D2, D3, D4, D5, D8.
**Obvious (no consult):** D1, D6, D7, D9, D10, D11, D12, D13, D14.
