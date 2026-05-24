    49	
    50	## Phase 2 — Friction analysis

codex
**Overall:** the direction is solid, but the current SPEC/PLAN is not yet tight enough for implementation. The biggest gaps are around Round 2 output shape, fix-gate measurability, and migration blast radius.

**Q1: Orchestrator-only likelihood assignment**

Mostly clean, but not fully sealed.

SPEC lines 92 and 136 explicitly say the orchestrator alone assigns likelihood buckets. The Round 1/2 schemas in SPEC lines 148-149 also omit `likelihood` and `posterior`, which is good.

Fragile parts:

- SPEC line 99 introduces an optional “Round 3 generation pass” after all hypotheses are eliminated, with consultants given `## Eliminated Alternatives`. That section likely contains test-derived conclusions, so consultants may indirectly see likelihood/falsification state.
- SPEC line 100 sends `## Root Cause` + `## Experiment Log` to `light-fix`. That is probably fine because it is fix-review, not likelihood assignment, but the boundary should say consultants may see interpreted evidence only after fix-gate, and may not revise likelihood/posterior.
- The SPEC does not define a universal “consultant visibility matrix” per phase. PLAN line 21 and SPEC lines 82/84/100 define some cases, but not the whole policy.

Add a table: phase, consultant mode, sections passed, forbidden fields, whether raw test output is allowed. Explicitly say no consultant mode may assign, revise, vote on, or validate likelihood/posterior.

**Q2: Round 2 obedience**

The prompt wording is clear, but enforcement is missing.

SPEC lines 149 and 153 forbid restating/agreement-only returns. PLAN line 30 repeats this. But there is no validation step in SPEC line 87 beyond “applies critiques.”

Agreement-shaped output should be treated as a schema violation, not “downweighted.” Round 2 should not affect posterior anyway. Suggested rule:

- Any Round 2 item that only endorses, ranks, or increases confidence in an existing hypothesis is ignored.
- If a consultant returns no valid `NEW` or `CRITIQUES`, record “no usable adversarial output” in the archive.
- Critiques must reference existing hypothesis IDs; otherwise they are advisory only.

Without this, Round 2 can drift back into likelihood/ranking by rhetoric.

**Q3: Fix-gate measurability**

Not robust enough.

SPEC line 96 says the causal mechanism must “explain every piece of evidence in DEBUG.md.” PLAN line 44 relies on that as a false-confirmation mitigation. But “every piece” is undefined, and DEBUG.md includes non-evidence sections like Hypothesis Pool, Test Matrix, Score Updates, Fix Plan, etc. That makes the gate subjective and potentially impossible.

Make evidence auditable:

- Assign evidence IDs in `## Evidence Inventory` and experiment IDs in `## Experiment Log`, e.g. `EVID-001`, `EXP-003`.
- Root cause must include an “Evidence coverage table”: `evidence_id | explained_by_mechanism | status`.
- Allowed statuses: `explained`, `falsifies_alternative`, `orthogonal_with_reason`, `unexplained`.
- Fix-gate opens only when there are zero `unexplained` items across Problem symptoms, Evidence Inventory, and Experiment Log.
- “Orthogonal” must require a concrete reason, not dismissal.

That turns the gate from vibes into a checklist.

**Q4: Surgical extraction scope**

Partly clean, partly underspecified.

SPEC line 82 says Round 1 receives DEBUG.md so far: Problem + Evidence Inventory, plus doc-fetcher synthesis. That answers one concern. But SPEC line 148 says the caller hands “problem statement + evidence inventory + relevant code,” while line 82 does not explicitly include relevant code except indirectly via doc-fetcher. Tighten that.

Round 2 is riskier. SPEC line 84 says Round 2 receives only Hypothesis Pool. PLAN line 21 says the same. That reduces bloat, but consultants are asked to critique whether tests are discriminating without seeing the underlying evidence/problem. They can critique logical form, but not relevance.

Either:

- Include a compact `Evidence Index` with IDs and one-line facts, or
- Require every Hypothesis Pool row to carry `evidence_refs`, so Round 2 has enough context inside the pool.

Fix consult scope at SPEC line 100 also needs clarity. `Root Cause + Experiment Log` excludes the original Evidence Inventory unless Root Cause includes the evidence coverage table above. If you adopt the table, this becomes clean.

**Q5: Return-shape contract**

Not tight enough.

Round 1 is acceptable as a field list in SPEC line 148, though “RAW” plus `schema_version` is ambiguous: where does `schema_version` appear if there is no wrapper?

Round 2 is loose. SPEC lines 86 and 149 define critique categories in prose, but not a parseable schema. This will invite markdown variance and brittle extraction.

Define Round 2 as a strict raw markdown shape or JSON block. For example:

```markdown
schema_version: hypothesis_round2_v1

## NEW
| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning |

## CRITIQUES
| target_id | critique_type | problem | recommended_action | merge_with_id |
```

Where `critique_type` is one of `non_discriminating_test | false_parallel_safe | duplicate | weak_claim | unclear_prediction`.

Also add ID rules: Round 2 critiques must reference `H###` IDs from the pool. Duplicate critiques must specify `merge_with_id`.

**Q6: Migration path**

This is the weakest part.

PLAN line 13 says no back-compat shim. That is acceptable only if all dependent commands/docs are updated. But Phase E line 72 only checks `commands/z-debug.md`. That misses real references elsewhere.

I found current old-artifact references outside `commands/z-debug.md`, including:

- [commands/z-stats.md](/Users/zeke/dev/z-harness/commands/z-stats.md:99): expects debug plans with `POSTMORTEM.md`.
- [commands/z-improve.md](/Users/zeke/dev/z-harness/commands/z-improve.md:45): looks for `POST-MORTEM.md` or `PROBLEM.md`.
- [skills/z-suggest-memory/SKILL.md](/Users/zeke/dev/z-harness/skills/z-suggest-memory/SKILL.md:385): reads concept hints from `POSTMORTEM.md` and `PROBLEM.md`.

The grep also shows mirrored command/skill copies for several commands. If this repo treats `commands/` and `skills/` as parallel surfaces, Phase E must check both. The current verification plan is too narrow.

Add a migration task:

- Search all `commands/`, `skills/`, `docs/`, `README.md`, and scripts for old artifact names.
- Decide per reference whether it remains valid for `/z-fix` `FIX.md`, new `/z-debug` `DEBUG.md` sections, or legacy archived runs.
- Update `/z-stats`, `/z-improve`, and `/z-suggest-memory` contracts explicitly.
- Add a legacy/read path decision: either no support, or “legacy archived debug runs are recognized but new runs use DEBUG.md.”

**Bottom Line**

Q1 is mostly clean but needs a phase visibility matrix and Round 3 clarification. Q2 is prompt-clean but procedure-weak. Q3 is too subjective. Q4 is mostly specified but Round 2 and fix consult need compact evidence context. Q5 needs a formal Round 2 critique schema. Q6 is currently incomplete; the plan’s self-check misses live dependencies outside `commands/z-debug.md`.
2026-05-24T06:38:02.667816Z ERROR codex_core::session: failed to record rollout items: thread 019e58b3-7748-7bc2-b36e-3b7ae964000b not found
tokens used
124,166
**Overall:** the direction is solid, but the current SPEC/PLAN is not yet tight enough for implementation. The biggest gaps are around Round 2 output shape, fix-gate measurability, and migration blast radius.

**Q1: Orchestrator-only likelihood assignment**

Mostly clean, but not fully sealed.

SPEC lines 92 and 136 explicitly say the orchestrator alone assigns likelihood buckets. The Round 1/2 schemas in SPEC lines 148-149 also omit `likelihood` and `posterior`, which is good.

Fragile parts:

- SPEC line 99 introduces an optional “Round 3 generation pass” after all hypotheses are eliminated, with consultants given `## Eliminated Alternatives`. That section likely contains test-derived conclusions, so consultants may indirectly see likelihood/falsification state.
- SPEC line 100 sends `## Root Cause` + `## Experiment Log` to `light-fix`. That is probably fine because it is fix-review, not likelihood assignment, but the boundary should say consultants may see interpreted evidence only after fix-gate, and may not revise likelihood/posterior.
- The SPEC does not define a universal “consultant visibility matrix” per phase. PLAN line 21 and SPEC lines 82/84/100 define some cases, but not the whole policy.

Add a table: phase, consultant mode, sections passed, forbidden fields, whether raw test output is allowed. Explicitly say no consultant mode may assign, revise, vote on, or validate likelihood/posterior.

**Q2: Round 2 obedience**

The prompt wording is clear, but enforcement is missing.

SPEC lines 149 and 153 forbid restating/agreement-only returns. PLAN line 30 repeats this. But there is no validation step in SPEC line 87 beyond “applies critiques.”

Agreement-shaped output should be treated as a schema violation, not “downweighted.” Round 2 should not affect posterior anyway. Suggested rule:

- Any Round 2 item that only endorses, ranks, or increases confidence in an existing hypothesis is ignored.
- If a consultant returns no valid `NEW` or `CRITIQUES`, record “no usable adversarial output” in the archive.
- Critiques must reference existing hypothesis IDs; otherwise they are advisory only.

Without this, Round 2 can drift back into likelihood/ranking by rhetoric.

**Q3: Fix-gate measurability**

Not robust enough.

SPEC line 96 says the causal mechanism must “explain every piece of evidence in DEBUG.md.” PLAN line 44 relies on that as a false-confirmation mitigation. But “every piece” is undefined, and DEBUG.md includes non-evidence sections like Hypothesis Pool, Test Matrix, Score Updates, Fix Plan, etc. That makes the gate subjective and potentially impossible.

Make evidence auditable:

- Assign evidence IDs in `## Evidence Inventory` and experiment IDs in `## Experiment Log`, e.g. `EVID-001`, `EXP-003`.
- Root cause must include an “Evidence coverage table”: `evidence_id | explained_by_mechanism | status`.
- Allowed statuses: `explained`, `falsifies_alternative`, `orthogonal_with_reason`, `unexplained`.
- Fix-gate opens only when there are zero `unexplained` items across Problem symptoms, Evidence Inventory, and Experiment Log.
- “Orthogonal” must require a concrete reason, not dismissal.

That turns the gate from vibes into a checklist.

**Q4: Surgical extraction scope**

Partly clean, partly underspecified.

SPEC line 82 says Round 1 receives DEBUG.md so far: Problem + Evidence Inventory, plus doc-fetcher synthesis. That answers one concern. But SPEC line 148 says the caller hands “problem statement + evidence inventory + relevant code,” while line 82 does not explicitly include relevant code except indirectly via doc-fetcher. Tighten that.

Round 2 is riskier. SPEC line 84 says Round 2 receives only Hypothesis Pool. PLAN line 21 says the same. That reduces bloat, but consultants are asked to critique whether tests are discriminating without seeing the underlying evidence/problem. They can critique logical form, but not relevance.

Either:

- Include a compact `Evidence Index` with IDs and one-line facts, or
- Require every Hypothesis Pool row to carry `evidence_refs`, so Round 2 has enough context inside the pool.

Fix consult scope at SPEC line 100 also needs clarity. `Root Cause + Experiment Log` excludes the original Evidence Inventory unless Root Cause includes the evidence coverage table above. If you adopt the table, this becomes clean.

**Q5: Return-shape contract**

Not tight enough.

Round 1 is acceptable as a field list in SPEC line 148, though “RAW” plus `schema_version` is ambiguous: where does `schema_version` appear if there is no wrapper?

Round 2 is loose. SPEC lines 86 and 149 define critique categories in prose, but not a parseable schema. This will invite markdown variance and brittle extraction.

Define Round 2 as a strict raw markdown shape or JSON block. For example:

```markdown
schema_version: hypothesis_round2_v1

## NEW
| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning |

## CRITIQUES
| target_id | critique_type | problem | recommended_action | merge_with_id |
```

Where `critique_type` is one of `non_discriminating_test | false_parallel_safe | duplicate | weak_claim | unclear_prediction`.

Also add ID rules: Round 2 critiques must reference `H###` IDs from the pool. Duplicate critiques must specify `merge_with_id`.

**Q6: Migration path**

This is the weakest part.

PLAN line 13 says no back-compat shim. That is acceptable only if all dependent commands/docs are updated. But Phase E line 72 only checks `commands/z-debug.md`. That misses real references elsewhere.

I found current old-artifact references outside `commands/z-debug.md`, including:

- [commands/z-stats.md](/Users/zeke/dev/z-harness/commands/z-stats.md:99): expects debug plans with `POSTMORTEM.md`.
- [commands/z-improve.md](/Users/zeke/dev/z-harness/commands/z-improve.md:45): looks for `POST-MORTEM.md` or `PROBLEM.md`.
- [skills/z-suggest-memory/SKILL.md](/Users/zeke/dev/z-harness/skills/z-suggest-memory/SKILL.md:385): reads concept hints from `POSTMORTEM.md` and `PROBLEM.md`.

The grep also shows mirrored command/skill copies for several commands. If this repo treats `commands/` and `skills/` as parallel surfaces, Phase E must check both. The current verification plan is too narrow.

Add a migration task:

- Search all `commands/`, `skills/`, `docs/`, `README.md`, and scripts for old artifact names.
- Decide per reference whether it remains valid for `/z-fix` `FIX.md`, new `/z-debug` `DEBUG.md` sections, or legacy archived runs.
- Update `/z-stats`, `/z-improve`, and `/z-suggest-memory` contracts explicitly.
- Add a legacy/read path decision: either no support, or “legacy archived debug runs are recognized but new runs use DEBUG.md.”

**Bottom Line**

Q1 is mostly clean but needs a phase visibility matrix and Round 3 clarification. Q2 is prompt-clean but procedure-weak. Q3 is too subjective. Q4 is mostly specified but Round 2 and fix consult need compact evidence context. Q5 needs a formal Round 2 critique schema. Q6 is currently incomplete; the plan’s self-check misses live dependencies outside `commands/z-debug.md`.
