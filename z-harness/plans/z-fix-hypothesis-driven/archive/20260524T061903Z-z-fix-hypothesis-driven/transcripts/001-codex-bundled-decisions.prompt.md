MODE: bundled-decisions

## Artifact: Decisions document from /z-fix-hypothesis-driven brainstorm

Context: This is the final planning phase for a brainstorm-derived decision set. The work splits `/z-debug` (current: linear hypothesis-generation → isolation → fix) into two commands:
- `/z-fix` — light path for users who already have a diagnosis
- `/z-debug` — heavy hypothesis-tournament path for diagnosis-free investigations

Five decisions are flagged for cross-LLM consult. The BRAINSTORM doc describes three independently generated framings (Claude, Codex, Gemini) and a user-synthesized hybrid choice folding the strongest parts of each into a `/z-debug` redesign (evidence-ledger framing with ordinal Bayesian scoring, multi-LLM round-1 generation + round-2 adversarial critique, forced outlier carve-out to avoid groupthink).

---

## D2: Hypothesis-matrix artifact (name, location, format)

**Decision:** How does the tournament's hypothesis matrix get persisted?

**Options:**
- (A) New `MATRIX.md` alongside existing PROBLEM/EVIDENCE/ISOLATION docs, markdown table format.
- (B) Extend `ISOLATION.md` with a top-section table; each cycle still appends below.
- (C) Single `DEBUG.md` that subsumes PROBLEM/EVIDENCE/ISOLATION/FIX (per Gemini ideator's framing).
- (D) Markdown table + JSON sidecar (`MATRIX.md` + `matrix.json`) so future tooling can parse without regex.

**Tentative:** (A) new `MATRIX.md`, markdown table only.

**Rationale for tentative:** Preserves the existing artifact set (no migration cost for the current `/z-debug` archive layout); markdown table is human-readable; no other command parses it so JSON sidecar would be ceremony.

**Why flagged for consult:** Names a new artifact on the command surface; hard to rename later; affects all downstream tooling (`/z-maintain-docs` audits, archive inspection).

---

## D3: Posterior-bucket lookup table (prior × likelihood → posterior)

**Decision:** Exact prior × likelihood → posterior mapping. The fix-gate ("winning hypothesis has highest posterior") depends on this table being unambiguous.

**Tentative table (5 priors × 5 likelihoods → ordinal posterior):**

| prior \ likelihood | strongly_falsified | weakly_falsified | inconclusive | weakly_supported | strongly_supported |
|---|---|---|---|---|---|
| **high** (overlap=3) | eliminated | low | med | high | very_high |
| **med** (overlap=2) | eliminated | very_low | low | med | high |
| **low** (overlap=1) | eliminated | very_low | very_low | low | med |

**Posterior ordering (high → low):** `very_high > high > med > low > very_low > eliminated`.

**Tentative rules:**
- `strongly_falsified` always eliminates regardless of prior (clean falsification overrides consensus).
- `inconclusive` preserves prior but cannot push to `very_high`.
- `strongly_supported` can promote any prior up by 2 buckets.

**Why flagged for consult:** Algorithmic choice with materially different tradeoffs; hard to revise once `/z-debug` runs cite posteriors. **Critical interaction with D4:** the prior buckets depend on the overlap_count denominator — if 3 LLMs (D4 option A), a hypothesis is "high prior" at overlap=3. If 2 LLMs (D4 option B), the thresholds shift.

---

## D4: Tournament cardinality — 2 LLMs or 3?

**Decision:** Does the hypothesis tournament use two independent ideators (Codex + Gemini) or three (orchestrator-Claude + Codex + Gemini)?

**Options:**
- (A) 3 LLMs. Orchestrator (Claude, main thread) writes its own hypothesis block in Phase 3 alongside dispatching Codex+Gemini in parallel. Overlap_count denominator = 3. **Mitigation against cross-contamination:** orchestrator writes block to checkpoint file BEFORE dispatching.
- (B) 2 LLMs. Only Codex+Gemini generate; orchestrator is purely coordinator. Overlap_count denominator = 2.
- (C) 2 LLMs but Claude-as-judge. Codex+Gemini generate; orchestrator merges and adds *missed* hypotheses only if both consultants failed to surface something obvious.

**Tentative:** (A) 3 LLMs.

**Rationale for tentative:**
- Free token-wise (orchestrator already in main context with full evidence).
- Meaningfully increases diversity.
- Matches BRAINSTORM's framing: "Claude / Codex / Gemini each independently propose 3–5."
- Mitigates LLM groupthink (the "everyone misses X" failure mode).

**Why flagged for consult:** Algorithm choice with diversity/contamination tradeoffs; **affects the overlap_count denominator and thus the prior-bucket thresholds in D3** — this is a hard D3↔D4 interaction.

---

## D5: New consultant modes

**Decision:** Add new modes to `codex-consultant` and `gemini-consultant`, or overload existing modes?

**Options:**
- (A) Two new modes: `generate-hypotheses-round1` (independent generation, no context from other models) and `generate-hypotheses-round2-adversarial` (given other models' lists, hunt missing failure modes + critique discriminating tests). Existing `debug-hypotheses` retained.
- (B) One new mode `hypothesis-tournament` parameterized by `round: 1 | 2` inside the prompt body.
- (C) Reuse `debug-hypotheses` with the caller swapping the body. No agent-file change.

**Tentative:** (A) Two new modes.

**Rationale for tentative:**
- Different return shapes per round:
  - R1 returns clean hypothesis list (per hypothesis: claim / prediction_if_true / prediction_if_false / discriminating_test / test_cost).
  - R2 returns *additions* (new hypotheses) + *critiques* (rows to weaken/drop with reason).
- Forcing into one mode hides the contract divergence and makes return parsing fragile.
- Existing `debug-hypotheses` stays for ad-hoc ranking (e.g. in `/z-fix` final consult).

**Why flagged for consult:** Changes the public mode contract on TWO agents; reversibility = >1 hour (touches all callers); naming choices are permanent. The return-shape divergence is a material design constraint.

---

## D8: `/z-fix` post-mortem requirement

**Decision:** Does `/z-fix` (the light path) require POSTMORTEM.md?

**Options:**
- (A) Required (same as today's `/z-debug`). Discipline is the whole point.
- (B) Optional (`AskUserQuestion` at end). Skip for typo-class fixes.
- (C) Not required. `/z-fix` is just `/z-plan-light` re-skinned for bugs; if you want post-mortem, use `/z-debug`.

**Tentative:** (B) Optional, default-off.

**Rationale for tentative:**
- Forcing a post-mortem on every typo-fix is the ceremony failure mode BRAINSTORM explicitly named.
- Offering as a one-line `AskUserQuestion` at the end preserves the option for the user when the fix turned out to be subtler than expected.
- Maintains the "light mode cuts ceremony" property that `/z-plan-light` established.

**Why flagged for consult:** Affects the discipline/ceremony tradeoff, which is the central tension of the split. Reversibility = >1 hour (changes user habit). Also interacts with D1 (the split itself) — if D1 is locked as "separate commands," this decision determines whether `/z-fix` feels like a lightweight tool or a junior `/z-debug`.

---

## Context: Current `/z-debug` and `/z-plan-light` structure

Current `/z-debug` (Phase 1–8):
1. Problem statement
2. Reproduce + evidence
3. Hypothesize (2–3 hypotheses, ranked)
4. Cross-LLM consult (`debug-hypotheses` mode; calls out hypothesis plausibility, missing ones, cheapest experiment)
5. Isolate (focused experiment per top hypothesis)
6. Root cause + fix (synthesize FIX.md)
7. Post-mortem (mandatory, includes preventative action items)
8. Finalize

Current `/z-plan-light` (Phase 1–9):
1. Premise + quick exploration (no fresh Explore subagent; doc-fetcher if INDEX.json exists, else Read/Grep inline)
2. Identify single key decision
3. Bundled cross-LLM consult (`light-fix` mode; one per consultant)
4. Synthesize + push back
5. Present + approve
6. Write FIX.md
7. Inline implementation (no implementer subagent)
8. Codex review (non-negotiable)
9. Finalize

User's stated choice from BRAINSTORM:
- `/z-fix` mirrors `/z-plan-light` (phases 1–9); wraps the existing `/z-plan-light` machinery
- `/z-debug` uses the heavy hypothesis-tournament pipeline (phases 1–12 per the codex framing in BRAINSTORM)
- Early gates in each command recommend the other when scope feels wrong

---

## Consultant agents available

**`codex-consultant`:** Haiku model, takes modes including:
- `debug-hypotheses` (existing; works on ranked hypotheses + evidence)
- `light-fix` (existing; works on single problem + key decision + candidate options)
- `generate-hypotheses-round1` (proposed D5 option A)
- `generate-hypotheses-round2-adversarial` (proposed D5 option A)

**`gemini-consultant`:** Similar interface, same mode set.

Both agents use the standard "build prompt, call LLM, return unfiltered" pattern. Return shapes are specified per mode.

---

## Ask

For each of the five consult-flagged decisions (D2, D3, D4, D5, D8), recommend with reasoning, tradeoffs, missed considerations, and decision interactions.

**Special attention to D3 ↔ D4 interaction:** If you recommend a different cardinality for D4, specify how the posterior table in D3 should shift.

**Special attention to D5:** If you recommend a different approach to new modes, articulate why the return-shape divergence between round 1 and 2 does or does not justify separate modes.

**Special attention to D8:** If you recommend required or drop post-mortem entirely, explain the discipline/ceremony tradeoff and any downstream implications for user habit or escalation flow.
