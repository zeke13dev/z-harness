MODE: plan-review

## SPEC.md (excerpt of key decisions)

1. `/z-fix` (light): user has diagnosis → single light-fix consult → inline impl → non-negotiable Codex review → optional post-mortem (auto-suggest YES if review cycles > 1).

2. `/z-debug` (heavy): unknown root cause → 3-LLM 2-round hypothesis generation → discriminating tests → orchestrator-assigned likelihood buckets → ordinal Bayesian posterior via fixed 3×5 lookup table → fix-gate requires BOTH (a) highest posterior AND (b) causal mechanism explaining all evidence.

3. D3 + D4 interaction: Orchestrator alone assigns likelihood buckets from test output (never delegated to consultants); prior derived from LLM overlap (3→high, 2→med, 1→low); orchestrator Round 1 block checkpointed to disk BEFORE consultant dispatch to prevent contamination.

4. Round 2 prompt explicitly forbids agreement ("Your value is orthogonality and critique, not endorsement").

5. Two new consultant modes mirrored across Codex + Gemini: `generate-hypotheses-round1` (independent) and `generate-hypotheses-round2-adversarial` (additions + critiques). Both return RAW.

6. Auto-bail: `/z-fix` retains today's >5-files / >2-decisions / cross-module triggers. `/z-debug` softens to multi-module / architectural / new-public-surface only (no >5-files trigger).

7. Surgical section extraction: Round-2 sees Hypothesis Pool only; fix consult sees Root Cause + Experiment Log.

## Key scrutiny points

**1. Contamination boundary (D3+D4):** Is the orchestrator-only likelihood-assignment rule actually clean? If orchestrator reads from a checkpoint file in Phase 6, how does it prevent reading from conversation state by accident? What if the checkpoint file is stale or missing?

**2. Round 2 forbid-agreement (D5):** The prompt says "Your value is orthogonality and critique, not endorsement." Will Codex/Gemini actually comply, or will they smuggle in agreement-shaped critiques like "Row 3 is a plausible variant of Row 5 but I'll mark it as unique"? What stops them from just re-stating pool entries in the CRITIQUES section?

**3. Fix-gate measurability (Phase 6 / Phase 7):** The rule is "highest posterior AND causal mechanism explains all evidence." How is "explains all evidence" operationalized? Is it just prose inspection by the orchestrator, or does it need to be machine-checkable? If prose, how does the orchestrator avoid letting a plausible-sounding mechanism slip through?

**4. Surgical section extraction (Phase 3b, Phase 7):** 
   - Round 2 dispatches get "Hypothesis Pool section only" — but what about the Problem section? Is that implicit context from Phase 1? If Round 2 models have no Problem context, how do they judge whether a test is discriminating for *this specific bug*?
   - Fix consult gets "Root Cause + Experiment Log" — does it also need Problem + Evidence Inventory for reference?
   - Are the section boundaries crisp, or will orchestrator be tempted to hand over more of DEBUG.md for "clarity"?

**5. Return-shape contract tightness (D5):** The new modes return RAW (no standard wrapper). The spec says Round-1 schema is `{claim, prediction_if_true, prediction_if_false, discriminating_test, test_cost, parallel_safe, reasoning}` and Round-2 returns TWO sections (NEW + CRITIQUES). Is the ordering of fields locked? Can a row have extra fields? If a consultant returns `[{"claim": "...", "reasoning": "...", "test_cost": "...", "discriminating_test": "...", ...}]` (different order), will the orchestrator's parser break?

**6. Migration path:** The SPEC says "today's `/z-debug` separate-file artifacts (PROBLEM/EVIDENCE/ISOLATION/FIX/POSTMORTEM) are replaced wholesale — no back-compat shim." Are there any references in existing commands (like `/z-mr-review`, `/z-implement-all`, `/z-maintain-docs`) that assume separate files exist? If so, do they need updates as a gate before `/z-debug` migration lands?

## PLAN.md (excerpt)

Phase A: consultant agent updates (must land first).
Phase B: new `/z-fix` command + docs.
Phase C: `/z-debug` rewrite + docs.
Phase D: doc index refresh.
Phase E: verification (search for leftover artifact references).

## Ask

Critique this plan — what's wrong, missing, or fragile? Specifically scrutinize the six points above. Be concrete and cite SPEC/PLAN line/section references. Flag any interaction between decisions that could break the plan.
