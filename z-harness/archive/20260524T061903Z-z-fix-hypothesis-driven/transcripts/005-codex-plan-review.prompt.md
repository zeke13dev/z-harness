# MODE: plan-review

## Input

SPEC.md + PLAN.md for z-fix-hypothesis-driven command split.

## Context

This is a rewrite of `/z-debug` into two commands: `/z-fix` (light, user-diagnosed) and `/z-debug` (heavy, hypothesis-tournament). Five prior decisions already consulted via BRAINSTORM (D2 unified DEBUG.md, D3 ordinal Bayesian table, D4 3-LLM with orchestrator checkpoint, D5 two new consultant modes, D8 optional post-mortem in /z-fix).

## Artifact excerpts

### From SPEC.md:

**D3 + D4 interaction (section on Posterior lookup table, lines 121-129):**
```
**Posterior lookup table (locked):**

| prior \ likelihood | strongly_falsified | weakly_falsified | inconclusive | weakly_supported | strongly_supported |
|---|---|---|---|---|---|
| **high** (overlap=3) | eliminated | low | high | high | very_high |
| **med** (overlap=2) | eliminated | very_low | med | high | very_high |
| **low** (overlap=1) | eliminated | very_low | low | med | high |

Posterior order: `very_high > high > med > low > very_low > eliminated`.

**Hard rules:**
...
- **Likelihood-bucket assignment is **orchestrator-only** — never delegated to a consultant.
```

**Phase 3b Round 2 prompt (lines 84-87):**
```
Each returns:
    - **NEW** hypotheses (failure modes absent from the pool). Same Round-1 schema per row.
    - **CRITIQUES** of existing rows: which discriminating tests are non-discriminating, which mutate state but are tagged `parallel_safe: true`, which rows are duplicates that should merge.
    Orchestrator integrates additions, applies critiques (downgrades `parallel_safe` flags, merges duplicates with combined `overlap_count`, drops or refines weak-test rows).
```

**Fix-gate definition (lines 96):**
```
If any active hypothesis has posterior = `very_high` AND a written causal mechanism that explains every piece of evidence in DEBUG.md → **fix-gate open**, proceed to Phase 7.
```

**New consultant mode contract (lines 147-153):**
```
- **`generate-hypotheses-round1`** (Phase 3a of `/z-debug`): ...Return ordered list, each row schema: `claim`, `prediction_if_true`, `prediction_if_false`, `discriminating_test` (concrete, executable where possible), `test_cost` (one of `free|cheap|medium|expensive`), `parallel_safe` (bool, true only if the test mutates no shared state), `reasoning` (one sentence). Mode `schema_version: hypothesis_round1_v1`. Return RAW (no standard wrapper).
- **`generate-hypotheses-round2-adversarial`** (Phase 3b of `/z-debug`): ... The prompt MUST explicitly forbid mere agreement with existing pool entries: "Your value is orthogonality and critique, not endorsement." Mode `schema_version: hypothesis_round2_v1`. Return RAW.
```

### From PLAN.md:

**Orchestrator contamination boundary (lines 26-27):**
```
Contamination mitigation: orchestrator writes its own Round 1 hypothesis block to `archive/<run>/round1-orchestrator.md` BEFORE dispatching the parallel consultant calls, and reads from that file (not from conversation state) during the merge step.
```

**Surgical section extraction discipline (SPEC lines 84-87, PLAN lines 21):**
```
Mitigation for context bloat: subagent dispatches use surgical section extraction (Round-2 sees Hypothesis Pool only; fix consult sees Root Cause + Experiment Log).
```

**New return-shape contract (SPEC lines 148-149, 155):**
```
Both modes return **raw** (no wrapper). Document the schema versions.
```

## Six scrutiny points

**Q1: Orchestrator-only likelihood-assignment rule (D3+D4 interaction) — contamination boundary clean?**

The SPEC rule is: "Likelihood-bucket assignment is orchestrator-only — never delegated to a consultant." The consultant modes return `schema_version: hypothesis_round1_v1` and `hypothesis_round2_v1` rows, which include fields like `test_cost` and `parallel_safe` but NOT `likelihood` or `posterior`.

The contamination boundary should be clean here IF:
- The orchestrator reads test output on its own (Phase 6, step 2) and assigns the likelihood bucket in isolation, documented in `## Experiment Log`.
- Consultants NEVER see the test results or the likelihood assignment, only the initial pool.

But the SPEC does NOT explicitly define the per-phase consultant visibility. E.g., are consultants shown the raw test output? Are they asked to interpret it? Is there a Round 3 "given test results, refine your hypothesis" pass?

**Q2: Round 2 prompt "forbid mere agreement" — will they actually obey?**

The SPEC says (line 149): "The prompt MUST explicitly forbid mere agreement with existing pool entries: 'Your value is orthogonality and critique, not endorsement.'"

But the agent contract (codex-consultant.md, lines 151-153) states the Ask template:
```
`generate-hypotheses-round2-adversarial`: "Given this merged hypothesis pool, return: (1) NEW hypotheses representing failure modes absent from the pool; (2) CRITIQUES of existing rows — non-discriminating tests, false parallel-safe tags, duplicate claims. Do not restate existing pool entries — your value is orthogonality and critique, not endorsement."
```

This is clear but does not pass any penalty or constraint if they do violate it. How will the orchestrator detect and handle agreement-shaped critiques (e.g., "I agree with Hypothesis 3, and here's why I think it's even more likely")? Is that a fail state? Does the orchestrator downweight it?

**Q3: Fix-gate "explains all evidence" — is it measurable/falsifiable?**

The fix-gate (SPEC line 96) requires: "a written causal mechanism that explains every piece of evidence in DEBUG.md."

This is subjective. What does "explains every piece" mean?
- Every log line?
- Every symptom listed in the Problem statement?
- Every test result in the Experiment Log, or only the positive ones?
- Can there be "this evidence is orthogonal to the root cause" dismissals?

The SPEC does not define a rubric or a decision procedure. The orchestrator must make a judgment call. This is not falsifiable in the way a test result is. How does the orchestrator know when to accept or reject a causal mechanism?

**Q4: Surgical-section-extraction discipline — which concrete sections per subagent?**

The SPEC says (line 84): "Each receives ONLY the merged `## Hypothesis Pool` section (surgical extraction per D2 mitigation), NOT the full DEBUG.md."

And for the fix consult (line 100): "Subagent input: `## Root Cause` + `## Experiment Log` sections only (surgical extraction)."

But it does not define:
- Does Round 1 receive the full `## Problem` + `## Evidence Inventory` sections? (Implied yes, but not explicit.)
- Does Round 2 receive ONLY the `## Hypothesis Pool`, or also Problem + Evidence for context? (Implied only Pool, but what if a hypothesis is incoherent without the Evidence context?)
- In the fix consult, does Root Cause + Experiment Log include the full Evidence Inventory, or just the final causal mechanism?

Vague boundaries risk either context bloat (subagents drowning in text) or misunderstanding (subagents confused about what evidence supports what).

**Q5: New consultant-mode return-shape contract — tight enough?**

The SPEC defines two raw-return schemas:
- `hypothesis_round1_v1`: `claim, prediction_if_true, prediction_if_false, discriminating_test, test_cost, parallel_safe, reasoning`
- `hypothesis_round2_v1`: NEW section (same schema) + CRITIQUES section (unspecified schema)

The CRITIQUES section is not formally defined. The SPEC says (line 86): "which discriminating tests are non-discriminating, which mutate state but are tagged `parallel_safe: true`, which rows are duplicates that should merge."

But what's the return format? Markdown bullets? Rows with an `id` column pointing to the pool? This will matter for orchestrator parsing. If the schema is loose, the orchestrator may need regex hell to extract critiques and apply them to the pool.

**Q6: Migration — today's /z-debug separate-file artifacts explicitly dropped. Any breaking paths?**

The SPEC says (PLAN line 13): "Do not migrate today's `/z-debug` separate-file artifacts (PROBLEM/EVIDENCE/ISOLATION/FIX/POSTMORTEM) — they are replaced wholesale by unified DEBUG.md going forward. No back-compat shim."

But are there any references in the codebase that *expect* separate files? E.g.:
- Does `/z-maintain-docs` scan for `PROBLEM.md` and `FIX.md` separately?
- Does `/z-mr-review` or any post-mortem integration script assume separate `POSTMORTEM.md` files?
- Do any scripts in `scripts/` glob for `**/ISOLATION.md` or parse filename patterns?

The PLAN includes a self-check (Phase E, lines 71-73) but does not list what was actually found. This is a dependency-tracking risk.

## Ask

Critique this plan. What's wrong, missing, or fragile? For each of the six scrutiny points above, is the boundary clean, the contract unambiguous, or the procedure robust? Flag any gaps in the contamination boundary, the return-shape schema, the fix-gate definition, the surgical extraction scope, the Round 2 obedience mechanism, or the migration path. Be specific and cite SPEC/PLAN lines.

