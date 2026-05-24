# SPEC — z-fix-hypothesis-driven

## Overview

Split the existing `/z-debug` command into two commands that mirror this codebase's `/z-plan` vs `/z-plan-light` pattern:

- **`/z-fix`** — light, user-already-has-diagnosis path. Single sanity-check consult, inline implementation, non-negotiable Codex review. Optional post-mortem.
- **`/z-debug`** — heavy hypothesis-tournament path. 3-LLM two-round adversarial hypothesis generation, consensus-first ranking with forced outlier carve-out, discriminating-test matrix, discrete Bayesian ordinal scoring (orchestrator-assigned likelihoods), 3-5 isolation rounds, fix-gate requires highest posterior AND causal mechanism explaining all evidence. Single unified `DEBUG.md` artifact (per BRAINSTORM User choice).

Each command has an early gate to recommend the other when scope feels wrong (no auto-routing).

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/z-fix-hypothesis-driven/BRAINSTORM.md | 2026-05-24T05:53:33Z |
| RESEARCH.md | n/a | n/a |

---

## File: `commands/z-fix.md` (NEW)

**Path:** `/Users/zeke/dev/z-harness/commands/z-fix.md`

**Frontmatter:**
```yaml
---
description: Lightweight bug-fix command for the case where the user already has a diagnosis. Captures problem + repro, single light-fix sanity consult ("does the proposed cause explain all symptoms?"), inline implementation, non-negotiable Codex review. Optional post-mortem (auto-suggested if review needed >1 retry). Early gate recommends /z-debug if user signals unknown root cause.
argument-hint: <symptom or proposed fix description>
---
```

**Phases:**

1. **Setup** — same as `/z-plan-light` Setup steps 1-7 (derive slug as `fix-<symptom-slug>`, export `Z_HARNESS_SLUG`, RUN, mkdir, version stamp via `scripts/version.sh`, log `fix_run_start`, notification policy).
2. **Auto-bail thresholds** (same as `/z-plan-light`): >5 candidate files, >2 non-obvious decisions, cross-module/cross-crate impact. On trigger, write `escalation.md` and recommend `/z-plan`.
3. **Phase 0 — Wrong-tool gate.** `AskUserQuestion`: "Do you already have a hypothesis for what's causing this?" Options: `yes — proceed` (default), `no — recommend /z-debug` (exits with one-line recommendation). Free-text "modify hypothesis" path also allowed.
4. **Phase 1 — Problem + repro + quick exploration** (combined). Capture `PROBLEM.md` and `EVIDENCE.md` sections inline (re-use today's `/z-debug` P1+P2 schemas, just inlined into the FIX flow). Dispatch `doc-fetcher` (Haiku) if `docs/llm/INDEX.json` exists; otherwise direct Read/Grep/Glob from main thread. **Never** spawn `Explore`. Output: 1-paragraph problem + 1-paragraph context + repro confirmation. Re-check auto-bail.
5. **Phase 2 — Single key decision.** Articulate the one question: "what's the right fix?" If >2 non-obvious decisions surface, bail to `/z-plan`.
6. **Phase 3 — Bundled `light-fix` consult.** Spawn `codex-consultant` and `gemini-consultant` in parallel in a single message with `MODE: light-fix`. Consult question framed as: *"User's proposed cause: <X>. Does this cause explain all symptoms in EVIDENCE? If not, what's the gap? Recommend the fix approach with tradeoffs."* — NOT the generic "what's the best fix?" framing.
7. **Phase 4 — Synthesize + push back.** For each recommendation, articulate one reason it might be wrong. Flag shortcuts. Cross-LLM disagreement is surfaced to the user in Phase 5.
8. **Phase 5 — Approve.** `AskUserQuestion` with `approve | modify | abandon` options. Push-notify if policy permits.
9. **Phase 6 — Write `FIX.md`** (same schema as `/z-plan-light` Phase 6; `Status: approved`). Note: `/z-fix` writes `FIX.md` as the single artifact (no separate PROBLEM.md / EVIDENCE.md files); the problem+evidence content lives as sections within FIX.md.
10. **Phase 7 — Inline implementation** (main thread). Same implementer self-check (no broad exception handlers, no scope expansion, no unsolicited validation, no new public surface, no stale comments). Mid-edit escape hatch identical to `/z-plan-light` Phase 7.
11. **Phase 8 — Codex review** (non-negotiable). Same retry-once policy as `/z-plan-light` Phase 8. Track `REVIEW_CYCLES` count for Phase 9 trigger.
12. **Phase 9 — Optional post-mortem.** `AskUserQuestion`: "Write post-mortem?"
    - **Default = NO** if `REVIEW_CYCLES <= 1`.
    - **Default = YES** if `REVIEW_CYCLES > 1`, with prompt text: *"Review cycles: <N>. Suggesting post-mortem — simple fix may have been subtler than expected."*
    - If user picks YES → write `POSTMORTEM.md` using today's `/z-debug` Phase 7 schema (Summary, Timeline, Root cause, Fix, Why we didn't catch it, Action items, Confidence). The MR-review integration block (today's `/z-debug` P7 steps 1-3) is *not* triggered automatically in `/z-fix` — user can run `/z-mr-review` separately.
13. **Phase 10 — Finalize.** Update `FIX.md` `Status: shipped`. Log `fix_run_end` with `{status, files_changed, review_cycles, postmortem_written: bool}`. Push-notify. If `FIX.md` "Docs touched" is non-empty, suggest `/z-maintain-docs --audit`.

**Hard rules:**
- Never skip Codex review.
- Never proceed past auto-bail thresholds without explicit user override.
- Always emit cross-LLM consult — both Gemini and Codex in parallel.
- No emojis.
- Early gate (Phase 0) is non-skippable — if the user can't name a hypothesis, the command exits with a `/z-debug` recommendation, even if the user typed an argument.

---

## File: `commands/z-debug.md` (MAJOR REWRITE)

**Path:** `/Users/zeke/dev/z-harness/commands/z-debug.md`

**Frontmatter (revised):**
```yaml
---
description: Heavy hypothesis-tournament debugging pipeline for the case where root cause is unknown. Two rounds of adversarial multi-LLM hypothesis generation (Claude + Codex + Gemini), discriminating-test matrix with consensus-first ranking + forced outlier carve-out, ordinal Bayesian scoring with orchestrator-assigned likelihoods, 3-5 isolation rounds, fix-gate requires highest posterior AND causal mechanism. Single unified DEBUG.md artifact. Early gate recommends /z-fix if user already has a diagnosis.
argument-hint: <symptom description>
---
```

**Phases:**

1. **Setup** — mostly unchanged from today (derive slug `debug-<symptom-slug>`, export `Z_HARNESS_SLUG`, RUN, mkdir, version stamp, log `debug_run_start`, record `T0_DEBUG`, note `docs/llm/INDEX.json`).
2. **Auto-bail thresholds (softened — D10).** Trigger ONLY on multi-module / architectural / new public surface / new wire format / new schema. **Drop the >5-files trigger** (heavy path is for harder bugs). Cycle cap moves to 5 (D7). Cross-module bail still recommends `/z-plan`.
3. **Phase 0 — Wrong-tool gate.** `AskUserQuestion`: "Do you already have a concrete hypothesis for what's causing this?" Options: `no — proceed with /z-debug` (default), `yes — recommend /z-fix` (exits).
4. **Phase 1 — Problem statement.** Open the `DEBUG.md` artifact with the `## Problem` section (today's PROBLEM.md content as a section). Clarifying questions via `AskUserQuestion` as today.
5. **Phase 2 — Reproduce + evidence inventory.** Append `## Evidence Inventory` section to `DEBUG.md` (today's EVIDENCE.md content as a section). Same repro priority order (failing log → failing test → failing CLI → production logs → DB snapshot). Same "cannot reproduce" handling. **Each evidence entry gets a stable `EVID-NNN` ID at capture time** (zero-padded, 3 digits). Format: each Evidence Inventory entry is a bullet `- **EVID-001:** <text or quoted log line / fixture / metric>`. These IDs are referenced by Phase 7's Evidence coverage table.
6. **Phase 3a — Round 1 hypothesis generation (3 LLMs, parallel, independent).**
    1. Orchestrator writes its own hypothesis block to `archive/<run>/round1-orchestrator.md` BEFORE dispatching consultants (contamination mitigation per D4). Each row uses the Round-1 schema (claim / prediction_if_true / prediction_if_false / discriminating_test / test_cost / parallel_safe / reasoning).
    2. In a single message, dispatch `codex-consultant` and `gemini-consultant` in parallel with `MODE: generate-hypotheses-round1`. Each receives: full DEBUG.md content so far (Problem + Evidence Inventory only; never the orchestrator block); doc-fetcher synthesis if relevant. Each returns 3-5 independent hypotheses in the schema.
    3. After both return: orchestrator reads its checkpoint file from disk (not from conversation state), merges all three lists into a single `## Hypothesis Pool` section in DEBUG.md. Each row gets a stable ID `H<NNN>` (zero-padded, 3 digits) and is tagged `proposed_by: [models]` and `overlap_count: N`. **Semantic dedup uses the exact written text of each row, not the orchestrator's recall of intent** — two rows with the same `claim` text (or close paraphrase, judged by content not source) merge into one row with `overlap_count += 1`. The merge decision per dedupe is documented as a one-line note alongside the merged row.
7. **Phase 3b — Round 2 adversarial.** Single-message parallel dispatch to both consultants with `MODE: generate-hypotheses-round2-adversarial`. Each receives ONLY the merged `## Hypothesis Pool` section (surgical extraction per D2 mitigation), NOT the full DEBUG.md. Each returns:
    - **NEW** hypotheses (failure modes absent from the pool). Same Round-1 schema per row.
    - **CRITIQUES** of existing rows: which discriminating tests are non-discriminating, which mutate state but are tagged `parallel_safe: true`, which rows are duplicates that should merge.
    Orchestrator integrates additions, applies critiques (downgrades `parallel_safe` flags, merges duplicates with combined `overlap_count`, drops or refines weak-test rows). Final merged pool committed to DEBUG.md.
8. **Phase 4 — Build `## Test Matrix` section.** For each surviving hypothesis, write one matrix row with columns: `id | claim | proposed_by | overlap | prior | test | cost | parallel | status`. Schema header line documented at top of section per Codex's recommendation. Prior bucket assigned mechanically from overlap_count: `3→high, 2→med, 1→low`. Initial status = `active`.
9. **Phase 5 — Compute test order (consensus-first + outlier carve-out, D6).** Sort hypotheses by overlap_count descending. **Always insert** the top 2 unique-to-one-model (overlap=1) hypotheses near the front of the order, even if their prior is `low`. This is the groupthink mitigation.
10. **Phase 6 — Batch isolation cycle.** For the current cycle (start at cycle 1):
    1. Group active hypotheses by `parallel_safe`. Run all `parallel_safe: true` tests in a single batch (in parallel where the test environment permits — at minimum, run them in series without intervening edits to shared state). Run `parallel_safe: false` tests serially.
    2. **Orchestrator alone** reads raw test output and assigns a likelihood bucket per hypothesis from `{strongly_falsified, weakly_falsified, inconclusive, weakly_supported, strongly_supported}`. The likelihood-assignment rule and the test output snippet that drove it are recorded in `## Experiment Log` (cycle N section).
    3. Apply the **posterior lookup table** (D3, see below) per hypothesis. Update Test Matrix `status` column: `eliminated` (any row with likelihood=strongly_falsified), `active` otherwise. Record posterior in a new column or row annotation.
    4. Append to `## Score Updates` section: per-hypothesis prior → posterior + the rule that fired.
11. **Phase 6 loop logic.**
    - If any active hypothesis has posterior = `very_high` AND a written causal mechanism that explains every piece of evidence in DEBUG.md → **fix-gate open**, proceed to Phase 7.
    - Otherwise: increment cycle counter, return to Phase 6.
    - Hard cycle cap: **5**. Soft warning at cycle 3 via push-notification. If cycle 6 would be needed, halt and `AskUserQuestion`: `continue (override cap) | bail to /z-plan | abandon`.
    - If all hypotheses are eliminated mid-loop and no `very_high` survivor, optionally spawn a Round 3 generation pass (orchestrator + both consultants, given the `## Eliminated Alternatives` section as context — "given these were all wrong, what are we missing?"). Counts as one of the 5 cycles.
12. **Phase 7 — Root cause + fix (reuses `/z-plan-light` mechanics).** Promote winning hypothesis to `## Root Cause` section. **Required subsection: `### Evidence coverage`** (table per the Evidence coverage schema below — one row per `EVID-NNN`, status ∈ `{explained, falsifies_alternative, orthogonal_with_reason, unexplained}`). **Fix-gate precondition (hard):** zero rows with `status: unexplained`. If any unexplained, halt and either upgrade the root cause statement or return to Phase 6 for more experiments. Once gate is open: capture `PRE_FIX_SHA=$(git rev-parse HEAD)`. Dispatch bundled `light-fix` consult (existing mode) on the proposed fix per the Phase-visibility matrix (subagents see Problem + Evidence Inventory + winning Hypothesis Pool rows + Experiment Log + draft Root Cause + draft Evidence coverage table). One-reason-it-might-be-wrong pushback. Write `## Fix Plan` section. Inline implementation with implementer self-check. Codex review (non-negotiable). Auto-bail still active for architectural-change-during-fix.
13. **Phase 8 — Verification.** Append `## Verification` section. **Two mandatory items:** (a) at least one regression test tied to the winning hypothesis; (b) a sanity check that the top eliminated alternative wasn't fixed by coincidence (e.g., re-run that alternative's discriminating test and confirm it still produces the falsifying signal).
14. **Phase 9 — Post-mortem (mandatory for `/z-debug`).** Append `## Post-mortem` section using today's POSTMORTEM.md schema (Summary, Timeline, Root cause, Fix, Why we didn't catch it, Action items, Confidence). Optional `/z-mr-review` integration retained (`AskUserQuestion` as today). Convert action items to follow-up tasks / `/z-test` follow-ups as today.
15. **Phase 10 — Finalize.** Log `debug_run_end` with `{status, hypothesis_cycles, total_hypotheses_generated, action_items, postmortem_written: true}`. Push-notify.

**Artifact:** single `z-harness/<slug>/DEBUG.md` with sections in this order:
```
# Debug: <slug>
## Problem
## Evidence Inventory
## Hypothesis Pool
## Test Matrix
## Experiment Log
## Score Updates
## Eliminated Alternatives
## Root Cause
## Fix Plan
## Verification
## Post-mortem
```

**Posterior lookup table (locked):**

| prior \ likelihood | strongly_falsified | weakly_falsified | inconclusive | weakly_supported | strongly_supported |
|---|---|---|---|---|---|
| **high** (overlap=3) | eliminated | low | high | high | very_high |
| **med** (overlap=2) | eliminated | very_low | med | high | very_high |
| **low** (overlap=1) | eliminated | very_low | low | med | high |

Posterior order: `very_high > high > med > low > very_low > eliminated`.

**Hard rules:**
- Never debug without repro (same as today).
- Never skip post-mortem (same as today — `/z-debug` is the discipline path).
- Never skip Codex review on the fix.
- Always emit BOTH Round 1 and Round 2 hypothesis-generation consults (4 subagent calls total during generation: 2 in R1 + 2 in R2).
- Likelihood-bucket assignment is **orchestrator-only** — never delegated to a consultant.
- Orchestrator's Round 1 block MUST be checkpointed to disk before consultant dispatch.
- No emojis.

---

## File: `agents/codex-consultant.md` (MODE ADDITIONS)

**Path:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`

Two new entries in the "Modes" list (after `debug-hypotheses`):

- **`generate-hypotheses-round1`** (Phase 3a of `/z-debug`): caller hands you a problem statement + evidence inventory + relevant code (surgical sections from DEBUG.md). Ask Codex to **independently** propose 3-5 hypotheses, no awareness of any other model's list. Return ordered list, each row schema: `claim`, `prediction_if_true`, `prediction_if_false`, `discriminating_test` (concrete, executable where possible), `test_cost` (one of `free|cheap|medium|expensive`), `parallel_safe` (bool, true only if the test mutates no shared state), `reasoning` (one sentence). Mode `schema_version: hypothesis_round1_v1`. Return RAW (no standard wrapper).
- **`generate-hypotheses-round2-adversarial`** (Phase 3b of `/z-debug`): caller hands you Problem + Evidence Inventory + the merged Round-1 Hypothesis Pool (per the Phase-visibility matrix; NOT the full DEBUG.md). Ask Codex to return **two markdown tables in this exact order**:
    1. **NEW** rows (additions to the pool — orthogonality hunt) with columns `| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning | orthogonality_to |`. `orthogonality_to` is a comma-separated list of `H<NNN>` IDs this row fills a gap relative to.
    2. **CRITIQUES** with columns `| target_id | critique_type | problem | recommended_action | merge_with_id |`. `critique_type` MUST be one of: `non_discriminating_test`, `false_parallel_safe`, `duplicate`, `weak_claim`, `unclear_prediction`. `problem` cell must be concrete (no `"looks good"`, no `"agree"`); `false_parallel_safe` rows MUST cite the specific mutation in the `problem` cell (e.g., `"writes to ~/.cache/foo"`). `merge_with_id` populated only when `critique_type == duplicate`.
    The prompt MUST explicitly forbid mere agreement with existing pool entries: "Your value is orthogonality and critique, not endorsement. Do not return rows that merely restate existing pool entries." Mode `schema_version: hypothesis_round2_v1`. Return RAW.

Add corresponding lines to the "Ask" templates section:
- `generate-hypotheses-round1`: "Independently propose 3-5 hypotheses for the root cause. Each must include a discriminating test that confirms if true AND refutes if false. Do not assume any context outside the problem statement and evidence inventory provided."
- `generate-hypotheses-round2-adversarial`: "Given this merged hypothesis pool, return: (1) NEW hypotheses representing failure modes absent from the pool; (2) CRITIQUES of existing rows — non-discriminating tests, false parallel-safe tags, duplicate claims. Do not restate existing pool entries — your value is orthogonality and critique, not endorsement."

Add to "Returning to the caller": both new modes return **raw** (no wrapper). Document the schema versions.

## File: `agents/gemini-consultant.md` (MODE ADDITIONS)

**Path:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`

Mirror of the above — identical mode names, schemas, ask templates, return shapes. Whatever wording change is made to one MUST be mirrored to the other to keep the agents contract-equivalent.

---

## File: `docs/llm/commands.json` (UPDATE)

Add a new concept entry for `z-fix` and revise the `z-debug` entry to reflect the new heavy pipeline.

`z-fix` entry skeleton:
```json
{
  "slug": "z-fix",
  "source_file": ["commands/z-fix.md"],
  "last_updated": "2026-05-24",
  "confidence": "high",
  "depends_on": ["agents", "scripts", "z-plan-light"],
  "consumed_by": [],
  "summary": "Lightweight bug-fix command for the case where the user already has a diagnosis; single light-fix consult, inline implementation, non-negotiable Codex review, optional post-mortem."
}
```

`z-debug` entry: update `last_updated`, refresh `summary` to mention the hypothesis tournament + 3-LLM 2-round generation + ordinal Bayesian scoring + unified DEBUG.md artifact. Update `depends_on` to include the new consultant modes (still under `agents`).

## File: `docs/llm/agents.json` (UPDATE)

Update the `codex-consultant` and `gemini-consultant` entries: append the two new modes to their `entry_points` lists (or wherever modes are enumerated in the per-concept JSON schema). Refresh `last_updated`.

## File: `docs/llm/INDEX.json` (UPDATE)

Add the `z-fix` concept entry. Refresh `last_updated` and `generated_at` for `commands`, `agents`, and the new `z-fix` concept.

## File: `docs/human/z-fix.md` (NEW)

**Path:** `/Users/zeke/dev/z-harness/docs/human/z-fix.md`

Companion human doc for `/z-fix`. Structure following existing human-tier docs:
- One-paragraph overview ("what this command is for / not for").
- Phase-by-phase walkthrough (brief — link to `commands/z-fix.md` for full procedure).
- "When to pick `/z-fix` vs `/z-debug`" decision matrix.
- Example invocation + sample FIX.md.
- Hard rules summary.

## File: `docs/human/z-debug.md` (NEW)

**Path:** `/Users/zeke/dev/z-harness/docs/human/z-debug.md`

Net-new (no existing human doc per ls check). Same structure as `/z-fix` doc but covering the heavy tournament pipeline. Includes:
- The posterior lookup table (verbatim).
- Worked example showing: 9 hypotheses generated (3 per LLM, partial overlap), Round 2 adds 2 more + drops 1, Test Matrix with 10 rows, 2-cycle convergence on `very_high` posterior.
- "Why orchestrator interprets likelihood" sidebar.

---

## DRY / KISS / SOLID compliance

- **DRY:** `/z-fix` Phases 1, 5, 6, 7, 8 reuse `/z-plan-light` flow verbatim — same Setup boilerplate, same FIX.md schema, same inline-implementation self-check, same Codex review safety gate. New consultant modes are mirrored between Codex and Gemini agents (single source of truth = the mode contract; both agents implement it identically).
- **KISS:** No floating-point Bayesian probabilities (ordinal buckets only). No JSON sidecars (markdown table). No auto-routing / under-the-hood graduation (separate commands, user-picked). Posterior lookup table is a fixed 3×5 grid, not a computation.
- **SOLID:**
  - *Single Responsibility:* `/z-fix` does one thing (fix-with-known-cause); `/z-debug` does one thing (diagnose-then-fix); consultant agents do one thing per mode.
  - *Open/Closed:* New modes added by extension (additional mode entries in agent files), not by modifying existing modes. Existing `debug-hypotheses` mode untouched.
  - *Liskov:* The two consultant agents are interchangeable for every mode they both support.
  - *Interface Segregation:* Each mode has its own return-shape contract (Round-1 schema ≠ Round-2 schema); no mode forces callers to handle data they don't need.
  - *Dependency Inversion:* `/z-debug` depends on the mode contract (abstract), not on Codex or Gemini specifically — either consultant agent satisfies any mode.

## Edge cases / invariants

- **Orchestrator contamination:** Round 1 orchestrator block written to checkpoint file BEFORE consultant dispatch; never re-read from conversation state. **Merge rule:** semantic dedup uses the exact written text of each row, not the orchestrator's recall of intent. Two rows with the same `claim` text (or close paraphrase, judged by content not source) merge with `overlap_count += 1`.
- **Round 2 forbids agreement:** prompt template explicitly forbids re-stating pool entries. **Enforcement (orchestrator post-process):** (a) any Round-2 NEW row whose `claim` semantically duplicates a pool row is dropped; (b) any critique row missing `target_id: H<NNN>` is invalid and discarded; (c) any critique row whose `problem` cell is tautological ("agree", "looks good", empty) is discarded; (d) `false_parallel_safe` critiques without a concrete mutation cited in `problem` are discarded.
- **Likelihood is orchestrator-only:** no consultant ever assigns a likelihood bucket; consultants vote priors via independent generation overlap.
- **Pool collapse:** if all hypotheses eliminated mid-loop with no `very_high` survivor, optional Round 3 generation pass. **Round 3 consultant input is restricted to facts not judgments:** eliminated `claim` text + the `discriminating_test` that falsified each. Never the likelihood bucket nor the posterior. Counts as one of the 5 cycle slots.
- **Cycle cap halt:** at cycle 6, `AskUserQuestion` mandatory before continuing.
- **Wrong-tool gates are non-skippable:** Phase 0 in both commands is mandatory; user cannot bypass with a CLI flag.
- **Auto-bail divergence:** `/z-fix` retains today's >5-files / >2-decisions / cross-module triggers; `/z-debug` softens to multi-module / architectural / new-public-surface only.
- **Post-mortem divergence:** `/z-debug` mandatory; `/z-fix` optional default-off (auto-suggest YES if review cycles > 1).
- **Hypothesis IDs:** every Hypothesis Pool row gets a stable `H<NNN>` ID at Phase 3a merge time (zero-padded, 3 digits). Round 2 critiques cite `target_id: H<NNN>`. Test Matrix, Score Updates, and Eliminated Alternatives all reference rows by ID.
- **Evidence IDs:** every Evidence Inventory entry gets a stable `EVID-<NNN>` ID at capture time (Phase 2). Root Cause section's Evidence coverage table has one row per `EVID-NNN`.
- **Fix-gate is objective:** opens only when (a) winning hypothesis posterior == `very_high` AND (b) every `EVID-NNN` in the Evidence coverage table has status ∈ `{explained, falsifies_alternative, orthogonal_with_reason}` (zero `unexplained`).

## Phase-visibility matrix (consultant context discipline)

This table is the source of truth for what each subagent dispatch sees. Subagent prompts must never include sections outside the listed scope, and must never receive likelihood buckets or posteriors except where listed.

| Phase | Consultant call | Sections passed | Forbidden | Raw test output? |
|---|---|---|---|---|
| 3a (Round 1) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory; doc-fetcher synthesis | Hypothesis Pool (doesn't exist yet); any orchestrator-internal block | No |
| 3b (Round 2) | both, MODE `generate-hypotheses-round2-adversarial` | Problem; Evidence Inventory; Hypothesis Pool (full) | Test Matrix; Experiment Log; Score Updates | No |
| 6 (optional Round 3) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory; eliminated `claim` text + falsifying `discriminating_test` only | priors, likelihoods, posteriors, full Eliminated Alternatives section | No |
| 7 (fix consult) | both, MODE `light-fix` | Problem; Evidence Inventory; winning Hypothesis Pool rows; Experiment Log; draft Root Cause; draft Evidence coverage table | Eliminated Alternatives; Score Updates history | No |

Orchestrator alone reads raw test output and assigns likelihood buckets (Phase 6, step 2). This row never appears in the table.

## Evidence coverage table (Root Cause section)

Required subsection of `## Root Cause`. Markdown table with one row per evidence ID:

```markdown
### Evidence coverage

| evid_id | text | status | how_root_cause_handles_it |
|---|---|---|---|
| EVID-001 | <text from Evidence Inventory> | explained | <one sentence> |
| EVID-002 | <text> | falsifies_alternative | <which H-id, one sentence> |
| EVID-003 | <text> | orthogonal_with_reason | <reason it's noise not signal> |
```

Statuses: `explained` (the root cause directly produces this evidence); `falsifies_alternative` (this evidence eliminated a competing hypothesis and is consistent with the root cause); `orthogonal_with_reason` (unrelated to root cause; reason documents why it's noise); `unexplained` (placeholder — fix-gate cannot open while any row carries this).

## Round 2 critique table schema (locked)

The `generate-hypotheses-round2-adversarial` mode returns two markdown tables (NEW rows + CRITIQUES). Both agents mirror this schema.

**NEW rows** (additions to Hypothesis Pool — orthogonality hunt):

```markdown
| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning | orthogonality_to |
```

`orthogonality_to` is a comma-separated list of `H<NNN>` IDs this fills a gap relative to (which existing pool entries fail to cover the failure mode this row captures).

**CRITIQUES** (judgments on existing pool entries):

```markdown
| target_id | critique_type | problem | recommended_action | merge_with_id |
```

`critique_type` ∈ `{non_discriminating_test, false_parallel_safe, duplicate, weak_claim, unclear_prediction}`. `problem` cell must be concrete (`false_parallel_safe` rows MUST cite the specific mutation, e.g. `"writes to ~/.cache/foo"`). `merge_with_id` is populated only when `critique_type == duplicate`.
