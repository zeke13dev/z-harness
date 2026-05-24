You are reviewing code that Claude just wrote for task T001: Add two new modes (generate-hypotheses-round1, generate-hypotheses-round2-adversarial) to agents/codex-consultant.md.

## Spec excerpt

From SPEC.md § "File: agents/codex-consultant.md (MODE ADDITIONS)":

Two new entries in the "Modes" list (after `debug-hypotheses`):

- **`generate-hypotheses-round1`** (Phase 3a of `/z-debug`): caller hands you a problem statement + evidence inventory + relevant code (surgical sections from DEBUG.md). Ask Codex to **independently** propose 3-5 hypotheses, no awareness of any other model's list. Return ordered list, each row schema: `claim`, `prediction_if_true`, `prediction_if_false`, `discriminating_test` (concrete, executable where possible), `test_cost` (one of `free|cheap|medium|expensive`), `parallel_safe` (bool, true only if the test mutates no shared state), `reasoning` (one sentence). Mode `schema_version: hypothesis_round1_v1`. Return RAW (no standard wrapper).
- **`generate-hypotheses-round2-adversarial`** (Phase 3b of `/z-debug`): caller hands you Problem + Evidence Inventory + the merged Round-1 Hypothesis Pool (per the Phase-visibility matrix; NOT the full DEBUG.md). Ask Codex to return **two markdown tables in this exact order**:
    1. **NEW** rows (additions to the pool — orthogonality hunt) with columns `| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning | orthogonality_to |`. `orthogonality_to` is a comma-separated list of `H<NNN>` IDs this row fills a gap relative to.
    2. **CRITIQUES** with columns `| target_id | critique_type | problem | recommended_action | merge_with_id |`. `critique_type` MUST be one of: `non_discriminating_test`, `false_parallel_safe`, `duplicate`, `weak_claim`, `unclear_prediction`. `problem` cell must be concrete (no `"looks good"`, no `"agree"`); `false_parallel_safe` rows MUST cite the specific mutation in the `problem` cell (e.g., `"writes to ~/.cache/foo"`). `merge_with_id` populated only when `critique_type == duplicate`.
    The prompt MUST explicitly forbid mere agreement with existing pool entries: "Your value is orthogonality and critique, not endorsement. Do not return rows that merely restate existing pool entries." Mode `schema_version: hypothesis_round2_v1`. Return RAW.

## Acceptance criteria
- Two new bullets in `## Modes` list with exact wording from SPEC
- Round-1 schema matches SPEC exactly
- Round-2 has two ordered markdown tables (NEW + CRITIQUES) with critique_type vocab; false_parallel_safe must cite mutation; forbid agreement-only
- Ask templates added
- Returning section notes RAW for both
- debug-hypotheses unchanged

## Focus
1. Do the two new mode bullets in "## Modes" list match SPEC exactly?
2. Does Round-1 schema description match all required fields?
3. Does Round-2 clearly document both tables in exact order, with critique_type vocab, mutation-citation requirement for false_parallel_safe, and forbid-agreement explicit language?
4. Are Ask templates added correctly for both modes?
5. Does "Returning to the caller" section correctly note both modes as RAW with schema versions documented?
6. Is debug-hypotheses mode unchanged?
