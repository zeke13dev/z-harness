---
name: z-debug
description: Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases, then ship a fix using the /z-plan-light flow, then write a post-mortem with preventative action items. Cross-LLM consult at the hypothesis stage and again at the fix stage. Auto-bails to /z-plan when scope grows beyond architectural change.
argument-hint: <symptom description>
---

You are running **z-harness `/z-debug`** — heavy hypothesis-tournament pipeline for an existing bug whose root cause is unknown. This is the discipline path. If the user already has a working hypothesis they want to ship a fix for, Phase 0 will redirect them to `/z-fix`.

Symptom (from `$ARGUMENTS`):

$ARGUMENTS

**If empty** — `AskUserQuestion`: "What's the symptom?" before proceeding.

## Setup

1. **Derive slug** like `debug-<symptom-slug>` (e.g. "MLB doubleheaders mislabeled" → `debug-mlb-doubleheaders-mislabeled`). Confirm via `AskUserQuestion` if non-obvious or might collide.
2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
5. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["symptom"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_start "$START_PAYLOAD"
   ```
6. Record start time `T0_DEBUG=$(date -u +%Y-%m-%dT%H:%M:%SZ)` — used for post-mortem timeline.
7. If `docs/llm/INDEX.json` exists → note it. Phase 2 (Evidence) and Phase 3a (Round 1 hypotheses) will dispatch `doc-fetcher` (Haiku) instead of reading INDEX.json or per-concept JSONs from main thread. The orchestrator never reads `docs/llm/*.json` directly.

## Auto-bail thresholds (softened — heavy path)

If at any phase you discover that the root cause / fix requires any of:

- **Multiple modules** / cross-module impact
- **Architectural change**
- **New public surface** / new wire format / new schema

→ STOP. Write `$Z_HARNESS_PLAN_DIR/escalation.md` documenting findings so far. Push-notify: "Debug requires architectural change — recommend `/z-plan` to design properly." Do not improvise a sprawling fix.

The old `>5 files touched` trigger is **dropped** — `/z-debug` is the heavy path, larger localized fixes are expected. Cycle cap is enforced separately in Phase 6 (soft warning at 3, hard halt at 6).

## Phase 0 — Wrong-tool gate (non-skippable)

`AskUserQuestion`:

**"Do you already have a concrete hypothesis for what's causing this?"**

- **"no — proceed with /z-debug"** (default) — continue to Phase 1.
- **"yes — recommend /z-fix"** — exit with one-line recommendation: "You already have a diagnosis. Run `/z-fix <symptom>` for the lightweight fix-with-known-cause flow." Do not proceed.

This gate is mandatory. If the user picks "yes," exit cleanly even if `$ARGUMENTS` was non-empty.

## Phase 1 — Problem statement

Ask clarifying questions via `AskUserQuestion`:

- "What was the expected behavior?"
- "What actually happens?"
- "When did this start?" (last working commit / deploy if known)
- "Reproducible?" (always / sometimes / once)
- "Any recent changes that might be related?"

Free-text follow-ups are fine for any of these.

Open the unified artifact `$Z_HARNESS_PLAN_DIR/DEBUG.md`. Start with the header and the `## Problem` section:

```markdown
# Debug: <slug>

**Reported:** <T0_DEBUG>
**Reproducible:** <always | sometimes | once>
**Started:** <last-good ref or "unknown">

## Problem

### Expected behavior
<verbatim from user>

### Actual behavior
<verbatim from user>

### Suspected scope
<one-paragraph initial read of where the bug likely lives>

### Recent changes mentioned by user
<verbatim or "none">
```

All subsequent phases append sections to this **single `DEBUG.md` file**. There are no separate PROBLEM/EVIDENCE/ISOLATION/FIX/POSTMORTEM files.

## Phase 2 — Reproduce + Evidence Inventory

Try to reproduce. Methods (in priority order):

1. **Failing log/error already provided** by the user → read it.
2. **Failing test** → run it inline (or via `remote-runner` Haiku if remote build needed).
3. **Failing CLI/script** → run it; capture stdout/stderr.
4. **Production-only** → ask user for log timestamps; use `qt-bot-remote` skill (if available) or other log access to fetch the relevant slice. **DB queries** here stay with the main thread (interpretive), not `remote-runner` (which refuses DB).
5. **DB state snapshot** → if the bug involves data shape, query the DB read-only via `qt-bot-remote` to confirm the actual state matches the user's description.

Append `## Evidence Inventory` to `DEBUG.md`:

```markdown
## Evidence Inventory

### Repro steps
1. ...
2. ...

### Reproducibility confirmed
<yes | no | partial; if no, explain>

### Inventory
- **EVID-001:** <text or quoted log line / fixture / metric>
- **EVID-002:** <text>
- **EVID-003:** <text>
- ...
```

**Each evidence entry gets a stable `EVID-NNN` ID at capture time** (zero-padded, 3 digits). These IDs are referenced by Phase 7's Evidence coverage table — never renumber, never reuse.

**If cannot reproduce.** Halt and ask the user via `AskUserQuestion`:
- "Gather more evidence — what should I look at next?"
- "Proceed on inference only (risky — debug without repro is unreliable)"
- "Abandon — wait until repro is possible"

Default recommendation: gather more evidence. Debug-on-inference often fixes the wrong thing.

## Phase 3a — Round 1 hypothesis generation (3 LLMs, parallel, independent)

**Contamination mitigation:** the orchestrator (Claude main thread) writes its OWN hypothesis block to a checkpoint file BEFORE dispatching the consultants. This prevents the orchestrator from re-reading consultant output and laundering it as "its own" hypothesis at merge time.

1. **Orchestrator checkpoint (FIRST).** Independently propose 3-5 hypotheses using the Round-1 schema. Write to `$Z_HARNESS_PLAN_DIR/archive/$RUN/round1-orchestrator.md`:

   ```markdown
   # Round 1 — Orchestrator hypotheses (checkpoint)

   _Written BEFORE consultant dispatch — do not edit after Phase 3a merge._

   | claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning |
   |---|---|---|---|---|---|---|
   | ... | ... | ... | ... | free\|cheap\|medium\|expensive | true\|false | ... |
   ```

   `parallel_safe: true` only if the discriminating test mutates no shared state.

2. **Dispatch both consultants in parallel (single message, both calls).** Each receives ONLY the Problem + Evidence Inventory sections of DEBUG.md (plus doc-fetcher synthesis if relevant). Never share the orchestrator's checkpoint block.

   ```
   Agent(
     subagent_type="consultant-secondary",
     description="R1 hypothesis generation for <slug>",
     prompt="MODE: generate-hypotheses-round1\n\nProblem (verbatim):\n<## Problem section>\n\nEvidence Inventory (verbatim):\n<## Evidence Inventory section>\n\nRelevant code (quoted with file:line, brief):\n<short snippets>\n\ndoc-fetcher synthesis (if relevant):\n<synthesis>\n\nAsk: independently propose 3-5 hypotheses for the root cause. Each must include a discriminating test that confirms if true AND refutes if false. Do not assume any context outside the problem statement and evidence inventory provided."
   )
   Agent(
     subagent_type="consultant-primary",
     description="R1 hypothesis generation for <slug>",
     prompt="MODE: generate-hypotheses-round1\n\n<same prompt body>"
   )
   ```

3. **Merge.** After both return:
   - Read the orchestrator checkpoint FROM DISK (`archive/$RUN/round1-orchestrator.md`) — NOT from conversation state.
   - Merge all three lists into a single `## Hypothesis Pool` section in DEBUG.md.
   - Assign each row a stable ID `H<NNN>` (zero-padded, 3 digits).
   - Tag each row `proposed_by: [models]` and `overlap_count: N` (1, 2, or 3 — how many of the three lists contained this hypothesis).
   - **Semantic dedup uses the exact written text of each row, not the orchestrator's recall of intent.** Two rows with the same `claim` text (or close paraphrase, judged by content not source) merge into one row with `overlap_count += 1`. Each merge decision is documented as a one-line note alongside the merged row (e.g., `_merged: H003 (orchestrator) + H007 (codex) — same claim about cache key collision._`).

   Append to DEBUG.md:

   ```markdown
   ## Hypothesis Pool

   | id | claim | proposed_by | overlap_count | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe |
   |---|---|---|---|---|---|---|---|---|
   | H001 | ... | [orchestrator, codex] | 2 | ... | ... | ... | cheap | true |
   | H002 | ... | [gemini] | 1 | ... | ... | ... | medium | false |
   ```

## Phase 3b — Round 2 adversarial

Single-message parallel dispatch to both consultants with `MODE: generate-hypotheses-round2-adversarial`. Each receives ONLY the merged `## Hypothesis Pool` section (surgical extraction per the Phase-visibility matrix), plus Problem + Evidence Inventory. **Do NOT** include Test Matrix, Experiment Log, or Score Updates — those don't exist yet anyway.

```
Agent(
  subagent_type="consultant-secondary",
  description="R2 adversarial for <slug>",
  prompt="MODE: generate-hypotheses-round2-adversarial\nschema_version: hypothesis_round2_v1\n\nProblem (verbatim):\n<## Problem>\n\nEvidence Inventory (verbatim):\n<## Evidence Inventory>\n\nHypothesis Pool (verbatim, with H<NNN> IDs):\n<## Hypothesis Pool table>\n\nAsk: given this merged hypothesis pool, return exactly TWO markdown tables in this order. Do not restate existing pool entries — your value is orthogonality and critique, not endorsement.\n\nTABLE 1 — NEW hypotheses (orthogonality hunt — failure modes absent from the pool). Columns (exact, in order):\n| claim | prediction_if_true | prediction_if_false | discriminating_test | test_cost | parallel_safe | reasoning | orthogonality_to |\n  - `test_cost` ∈ {free, cheap, medium, expensive}\n  - `parallel_safe` ∈ {true, false} — true ONLY if the discriminating test mutates no shared state\n  - `orthogonality_to` — comma-separated list of H<NNN> IDs this row fills a gap relative to (e.g. `H001, H004`)\n\nTABLE 2 — CRITIQUES of existing pool rows. Columns (exact, in order):\n| target_id | critique_type | problem | recommended_action | merge_with_id |\n  - `target_id` — H<NNN> of the row being critiqued (required; rows missing this will be dropped)\n  - `critique_type` MUST be one of: `non_discriminating_test`, `false_parallel_safe`, `duplicate`, `weak_claim`, `unclear_prediction`\n  - `problem` — concrete description; no 'looks good', no 'agree', no empty cells, no pure restatement of the target row's claim\n  - `false_parallel_safe` rows MUST cite the specific mutation in the `problem` cell (e.g. 'writes to ~/.cache/foo'), not just 'mutates state'\n  - `merge_with_id` — populated ONLY when `critique_type == duplicate` (the H<NNN> the target should merge into)\n\nTag the response with `schema_version: hypothesis_round2_v1` at the top."
)
Agent(
  subagent_type="consultant-primary",
  description="R2 adversarial for <slug>",
  prompt="MODE: generate-hypotheses-round2-adversarial\n\n<same prompt body>"
)
```

**Orchestrator post-process (filter step) — apply each filter explicitly:**

For NEW rows:
- (a1) **Inter-consultant dedup (apply FIRST).** Merge the NEW tables from both consultants into a single candidate list. Before assigning H<NNN> IDs, dedup the candidate list against itself using the same text-only semantic dedup rule from Phase 3a (compare `claim` text / close paraphrase, judged by content). If both Codex and Gemini proposed the same NEW hypothesis, collapse into a single candidate row with `proposed_by: [codex, gemini]`; document each merge as a one-line note. Do NOT assign two separate H<NNN> IDs for the same claim.
- (a2) **Pool dedup (apply SECOND).** Drop any surviving candidate NEW row whose `claim` semantically duplicates an existing pool row (same dedup rule; document the drop).

For CRITIQUES:
- (b) Drop any critique row missing a `target_id: H<NNN>` cell.
- (c) Drop any critique row whose `problem` cell is tautological — `"agree"`, `"looks good"`, empty, or pure restatement of the target row's claim.
- (d) Drop any `false_parallel_safe` critique that does not cite a specific mutation in the `problem` cell (e.g., must say `"writes to ~/.cache/foo"`, not just `"mutates state"`).

**Apply surviving critiques and additions:**
- NEW rows: append each surviving candidate from step (a2) to Hypothesis Pool with a new `H<NNN>` ID. Set `proposed_by` to the merged list from step (a1) (e.g. `[codex]`, `[gemini]`, or `[codex, gemini]` if both proposed it). Recompute `overlap_count = len(set(proposed_by))` capped at 3 — never arithmetic-sum.
- `non_discriminating_test` / `weak_claim` / `unclear_prediction` critiques: refine the target row's `discriminating_test` / `claim` / `prediction_*` cells (or, if irreparable, drop the row and note in `## Eliminated Alternatives`).
- `false_parallel_safe` critiques: flip the target row's `parallel_safe` from `true` to `false`.
- `duplicate` critiques: merge `target_id` into `merge_with_id` — union the two rows' `proposed_by` lists (set-union, no duplicates), recompute `overlap_count = len(set(proposed_by))` capped at 3 (the number of unique independent sources from {orchestrator, codex, gemini}), then drop the duplicate row. Never arithmetic-sum the old `overlap_count` values — that can exceed 3, which the Phase 4 `prior` table does not support.

Commit the updated `## Hypothesis Pool` to DEBUG.md after Phase 3b.

## Phase 4 — Build the Test Matrix

Append `## Test Matrix` to DEBUG.md. Schema header documented at the top of the section:

```markdown
## Test Matrix

_Schema: `id` (H<NNN> from Hypothesis Pool); `claim` (one-line); `proposed_by` (model list);
`overlap` (1-3); `prior` (mechanical from overlap: 3→high, 2→med, 1→low);
`test` (the discriminating test); `cost` (free|cheap|medium|expensive);
`parallel` (true|false); `status` (active|eliminated)._

| id | claim | proposed_by | overlap | prior | test | cost | parallel | status |
|---|---|---|---|---|---|---|---|---|
| H001 | ... | [orchestrator, codex] | 2 | med | ... | cheap | true | active |
| H002 | ... | [gemini] | 1 | low | ... | medium | false | active |
```

**Prior assignment is mechanical from `overlap_count`:** `3 → high`, `2 → med`, `1 → low`. No subjective adjustment. Initial `status` is always `active`.

## Phase 5 — Compute test order (consensus-first + forced outlier carve-out)

Sort the active rows by `overlap` descending (consensus first — higher overlap reflects three independent LLMs converging on the same failure mode).

**Forced outlier carve-out (groupthink mitigation):** always insert the top 2 unique-to-one-model rows (`overlap == 1`) near the front of the test order — within the first 3-4 positions, even if their `prior` is `low`. The orthogonality these surface is exactly what consensus-only ranking destroys.

Document the chosen order in DEBUG.md as a one-line note under the Test Matrix (e.g., `_Test order (cycle 1): H001, H004, H002 (outlier carve-out), H005 (outlier carve-out), H003._`).

## Phase 6 — Batch isolation cycle (loop)

For the current cycle (start at cycle 1):

1. **Group active hypotheses by `parallel`.** Run all `parallel: true` tests as a batch — in parallel where the test environment permits, or at minimum in series without intervening edits to shared state. Run `parallel: false` tests serially.

2. **Likelihood assignment — orchestrator only.** The orchestrator (Claude main thread) ALONE reads raw test output and assigns each tested hypothesis a likelihood bucket from:

   ```
   {strongly_falsified, weakly_falsified, inconclusive, weakly_supported, strongly_supported}
   ```

   Never delegate this to a consultant. Never pass raw test output to a consultant. Record in DEBUG.md `## Experiment Log` (cycle N section):

   ```markdown
   ## Experiment Log

   ### Cycle 1
   - **H001:** test = `<command>`; output snippet:
     ```
     <≤10 lines verbatim>
     ```
     Likelihood = `strongly_supported`. Rule: <one-sentence justification — what in the output drove the bucket>.
   - **H002:** ...
   ```

3. **Apply the posterior lookup table** (verbatim — this is the locked scoring rule):

   | prior \ likelihood    | strongly_falsified | weakly_falsified | inconclusive | weakly_supported | strongly_supported |
   |---|---|---|---|---|---|
   | **high** (overlap=3)  | eliminated         | low              | high         | high             | very_high          |
   | **med** (overlap=2)   | eliminated         | very_low         | med          | high             | very_high          |
   | **low** (overlap=1)   | eliminated         | very_low         | low          | med              | high               |

   Posterior order: `very_high > high > med > low > very_low > eliminated`.

   Update Test Matrix `status` column: `eliminated` for any row whose likelihood was `strongly_falsified`; `active` otherwise. Record the posterior bucket as a per-row annotation (either a new column or a one-line note under the row).

4. **Append `## Score Updates`** (cumulative, one block per cycle):

   ```markdown
   ## Score Updates

   ### Cycle 1
   - H001: prior=med + likelihood=strongly_supported → posterior=very_high (rule fired: med×strongly_supported)
   - H002: prior=low + likelihood=strongly_falsified → posterior=eliminated (rule fired: any×strongly_falsified)
   ...
   ```

5. **Move eliminated rows** to a `## Eliminated Alternatives` section (preserve the row + the cycle that eliminated it + the falsifying test):

   ```markdown
   ## Eliminated Alternatives
   - **H002** (eliminated cycle 1): claim=`...`; falsified by `<discriminating_test>` — output showed `...`.
   ```

### Phase 6 loop logic

- **Fix-gate check:** if any active hypothesis has `posterior == very_high` AND there is a written causal mechanism (Phase 7's Root Cause draft) explaining every `EVID-NNN` in the Evidence Inventory → fix-gate open, proceed to Phase 7.
- **Otherwise:** increment cycle counter, return to Phase 6 step 1 with the remaining `active` rows in updated test order.
- **Soft warning at cycle 3** — push-notify: "z-debug cycle 3 reached without convergence. Two cycles remaining before hard halt."
- **Hard cycle cap: 5.** If cycle 6 would be needed, halt and `AskUserQuestion`:
  - `continue (override cap)` — explicit user override required to enter cycle 6+.
  - `bail to /z-plan` — write `escalation.md`, recommend `/z-plan`.
  - `abandon` — log `debug_run_end {status: "abandoned"}` and stop.
- **Pool collapse (all eliminated, no `very_high` survivor):** optionally spawn a **Round 3 generation pass**.

### Optional Round 3 (pool-collapse recovery)

Counts as one of the 5 cycle slots. Dispatch the orchestrator + both consultants per the Phase-visibility matrix:

- Consultant input is **restricted to facts, not judgments**: pass ONLY the eliminated `claim` text + the `discriminating_test` that falsified each. **Never** pass the likelihood bucket nor the posterior nor the full `## Eliminated Alternatives` section.
- MODE: `generate-hypotheses-round1` (re-use Round 1 schema — these are fresh hypotheses given the falsified-set context).
- Merge into Hypothesis Pool with new `H<NNN>` IDs; rebuild Test Matrix entries; continue Phase 6 loop.

## Phase 7 — Root cause + fix-gate + fix (reuses `/z-plan-light` mechanics)

Promote the winning hypothesis (the one with `posterior == very_high`) to a `## Root Cause` section in DEBUG.md:

```markdown
## Root Cause

**Winning hypothesis:** H<NNN>
**Posterior:** very_high
**Causal mechanism:** <paragraph explaining how this hypothesis produces every observed symptom>

### Evidence coverage

| evid_id | text | status | how_root_cause_handles_it |
|---|---|---|---|
| EVID-001 | <text from Evidence Inventory> | explained | <one sentence> |
| EVID-002 | <text> | falsifies_alternative | <which H-id, one sentence> |
| EVID-003 | <text> | orthogonal_with_reason | <reason it's noise not signal> |
```

**Statuses (locked):**
- `explained` — the root cause directly produces this evidence.
- `falsifies_alternative` — this evidence eliminated a competing hypothesis and is consistent with the root cause.
- `orthogonal_with_reason` — unrelated to root cause; the reason cell documents why it's noise.
- `unexplained` — placeholder; the fix-gate cannot open while any row carries this status.

**Fix-gate (hard, two preconditions — BOTH must hold):**
1. Winning hypothesis `posterior == very_high`.
2. Zero rows in the Evidence coverage table with `status == unexplained`.

If either fails: halt. Either upgrade the root cause statement (so it actually explains the unexplained row) or return to Phase 6 for additional experiments. Do not advance to fix on a partial story.

**Once the gate opens:**

1. Capture pre-fix SHA: `PRE_FIX_SHA=$(git rev-parse HEAD)`. Passed to `/z-mr-review` later as `--base`.
2. **Bundled `light-fix` consult on the proposed fix.** Dispatch both consultants in parallel per the Phase-visibility matrix (subagents see: Problem + Evidence Inventory + winning Hypothesis Pool rows + Experiment Log + draft Root Cause + draft Evidence coverage table; subagents must NOT see Eliminated Alternatives or Score Updates history):
   ```
   Agent(subagent_type="consultant-secondary", description="Fix consult for <slug>",
         prompt="MODE: light-fix\n\n<sections per Phase-visibility matrix row 7>")
   Agent(subagent_type="consultant-primary", description="Fix consult for <slug>",
         prompt="MODE: light-fix\n\n<same sections>")
   ```
3. **Synthesize + push back.** One reason it might be wrong per recommendation. Flag shortcuts.
4. **Present + approve.** `AskUserQuestion` with the synthesized fix.
5. **Write `## Fix Plan`** section to DEBUG.md (schema mirrors `/z-plan-light` Phase 6 FIX.md):

   ```markdown
   ## Fix Plan

   ### Approach
   ...

   ### Files to change
   - <path>: <what changes>

   ### Acceptance
   - ...

   ### Cross-LLM consensus
   ...

   ### Approved shortcuts
   ...

   ### Docs touched
   ...
   ```

6. **Inline implementation** (same as `/z-plan-light` Phase 7). Implementer self-check: no broad exception handlers, no scope expansion, no unsolicited validation, no new public surface, no stale comments.
7. **Codex review** (same as `/z-plan-light` Phase 8 — non-negotiable). Retry-once policy. Track `REVIEW_CYCLES`.

Auto-bail still active: if the fix turns out to require architectural change / new public surface / cross-module impact, halt and recommend `/z-plan`.

## Phase 8 — Verification

Append `## Verification` section to DEBUG.md. **Two mandatory items:**

1. **Regression test** tied to the winning hypothesis — at minimum, a test that fails on the pre-fix code and passes on the post-fix code. Record path + what it asserts.
2. **Coincidence check** — re-run the top eliminated alternative's discriminating test against the post-fix code and confirm it still produces the same falsifying signal it did during isolation. (Guards against accidentally "fixing" a parallel issue that masks the real one.)

```markdown
## Verification

### Regression test
- Path: <test file path>
- Asserts: <what it checks>
- Pre-fix: FAIL; Post-fix: PASS.

### Coincidence check (top eliminated alternative)
- Hypothesis re-tested: H<NNN> — `<claim>`.
- Discriminating test re-run: `<command>`.
- Pre-fix signal: `<falsifying signal>`. Post-fix signal: `<still same falsifying signal — confirms elimination wasn't a coincidence>`.
```

## Phase 9 — Post-mortem (mandatory)

Post-mortem is **non-negotiable** for `/z-debug`. Append `## Post-mortem` section to DEBUG.md:

```markdown
## Post-mortem

### Summary
<2-3 sentences: what happened, impact, time-to-resolution>

### Timeline
- <T0_DEBUG>            — symptom first observed
- <T_PHASE2>            — repro confirmed
- <T_ROOT_CAUSE>        — root cause identified (cycle <N>, posterior=very_high on H<NNN>)
- <T_FIX_SHIPPED>       — fix shipped (codex review passed)
- Total wall time: <delta>

### Root cause
<one-paragraph explanation, referencing H<NNN> and EVID-NNN IDs>

### Fix
- Files changed: <from Fix Plan>
- Summary: <one paragraph>

### Why we didn't catch it earlier
Pick at least one. Be honest:
- Spec gap — `<which spec section was missing or wrong>`
- Test gap — `<which test should have caught this>`
- Missing assertion — `<where>`
- Monitoring/alerting gap — `<what would have surfaced this in prod>`
- Doc gap — `<which docs/llm/ concept didn't mention this invariant>`
- Other — `<explain>`

### Action items (preventative)
- [ ] <regression test path + what it should cover>
- [ ] <SPEC.md / docs/llm/<concept>.json update with the invariant that was violated>
- [ ] <monitoring/alerting addition>
- [ ] <other follow-ups>

### Confidence
- **Root cause confidence:** <yes | partial — explain>
- **Similar bugs likely elsewhere?** <list any places worth auditing; or "none — this is localized">
```

After writing the Post-mortem section, ask the user via `AskUserQuestion` (before the action-item conversion prompts):

**"Run MR-style quality review on the fix diff?"**
- "Run MR-style review (Recommended)" — invoke `/z-mr-review` on the fix diff; P0/P1 findings will be appended to the post-mortem's preventative action items automatically.
- "Skip" — leave the post-mortem as-is and proceed to the action-item conversion prompts.

If user accepts:

1. Invoke `/z-mr-review` as a best-effort step (on any failure, append a note to the Post-mortem section and continue — do NOT halt the post-mortem):
   ```bash
   /z-mr-review --slug $Z_HARNESS_SLUG --base $PRE_FIX_SHA --force-on-trunk
   ```
   - `PRE_FIX_SHA` was captured at Phase 7. Pass it as `--base` so the diff covers exactly the fix changes.
   - `--force-on-trunk` allows the review to run on whatever branch `/z-debug` is operating from.
   - `/z-mr-review` already gates on `STYLE.md` existence and will refuse with "Run /z-style-init first." if it's missing. Do NOT try to handle this here — let it fail-fast. On failure, log "MR review skipped: STYLE.md missing" (or "MR review skipped: /z-mr-review failed — <reason>") and continue.
   - MR-REVIEW.md is written by `/z-mr-review` to the canonical path: `$(git rev-parse --show-toplevel)/$Z_HARNESS_PLAN_DIR/MR-REVIEW.md`.

2. If `/z-mr-review` succeeds, parse `$(git rev-parse --show-toplevel)/$Z_HARNESS_PLAN_DIR/MR-REVIEW.md` for P0/P1 findings using a defensive Python inline block (treat malformed/missing as "no findings" — never fall back to prose parsing):
   ```bash
   python3 - <<'PYEOF'
   import sys, yaml
   mr_path = "<abs_path_to_MR-REVIEW.md>"
   try:
       with open(mr_path) as f:
           raw = f.read()
       parts = raw.split("---")
       if len(parts) < 3:
           raise ValueError("No valid frontmatter found")
       fm = yaml.safe_load(parts[1])
       if not isinstance(fm, dict):
           raise ValueError("Frontmatter is not a mapping")
       findings = fm.get("findings_index")
       if not isinstance(findings, list):
           print("NOTE: findings_index missing or not a list — treating as no findings")
           sys.exit(0)
       for entry in findings:
           if not isinstance(entry, dict):
               continue
           sev = entry.get("severity", "")
           if sev in ("P0", "P1"):
               fid = entry.get("id", "T-MR-???")
               title = entry.get("title", entry.get("file", "<no title>"))
               print(f"- [ ] [{fid}] {title} (from MR-REVIEW.md quality review)")
   except FileNotFoundError:
       print("NOTE: MR-REVIEW.md not found — MR review produced no output")
   except (yaml.YAMLError, ValueError, KeyError) as e:
       print(f"NOTE: MR-REVIEW.md parse error ({e}) — treating as no findings")
   PYEOF
   ```
   Collect the printed lines. If no `- [ ]` lines were printed (no P0/P1 findings or parse fallback), use a single note: `- MR quality review found no P0/P1 findings.`

3. Append the collected finding lines (or the "no findings" note) to the Post-mortem section's "Action items (preventative)" list.

After writing, ask the user via `AskUserQuestion`:
- "Convert action items into follow-up tasks?" → If yes, the orchestrator appends them to a designated `TASKS.md` (user picks which slug, or creates a fresh `audit-<topic>` slug) and the user can later `/z-implement-all` them.
- "Convert regression-test action items into a /z-test follow-up" → For each action item shaped like `Add regression test ...`, record the invariant + failure-class + target-file hint into `$Z_HARNESS_PLAN_DIR/test-followups.md` (a flat list of seed entries shaped like Phase 2 drafts in `/z-test`). On the next `/z-plan` + `/z-test` cycle (or if the user re-runs `/z-test` on this same slug after seeding follow-up production tasks), these become mandatory TESTS.md entries. Closes the post-mortem loop automatically — the next plan run cannot ship without the regression test the post-mortem flagged.
- "Just record and move on" → leave the Post-mortem section as a standalone record.

Push-notify: "Post-mortem ready: `$Z_HARNESS_PLAN_DIR/DEBUG.md` Post-mortem section. Action items: <N> (converted to tasks: <yes/no>)."

## Phase 10 — Finalize

**Clear the notify-dedup session file** (once per top-level `/z-debug` invocation — ensures each fresh debug session gets its own notify de-dup state):
```bash
[[ -n "${Z_HARNESS_PLAN_DIR:-}" ]] && rm -f "$Z_HARNESS_PLAN_DIR/.notify-dedup-session"
```

### Branch: `status: shipped` (fix was applied and post-mortem written)

1. Log:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_end \
     "$(printf '{"status":"shipped","hypothesis_cycles":%d,"total_hypotheses_generated":%d,"action_items":%d,"postmortem_written":true}' "$CYCLES" "$N_HYPOTHESES" "$N_ACTIONS")"
   ```
2. Push-notify if policy != `off`: "Debug complete. Root cause: <one-line, H<NNN>>. DEBUG.md in `$Z_HARNESS_PLAN_DIR/`."

3. **Memory review (shipped branch only):**

   a. Run the memory-review helper and parse with `mapfile`:
      ```bash
      mapfile -t LINES < <(bash scripts/run-memory-review.sh "$RUN" "debug")
      STATUS_LINE="${LINES[0]:-}"
      ```

   b. **Skip path — first line is `STATUS: skipped <reason>`:**
      ```bash
      if [[ "$STATUS_LINE" == STATUS:\ skipped* ]]; then
        # Helper already emitted the memory_review_terminal event.
        # For state: skipped_broken_context → push-notify if Z_HARNESS_NOTIFY != off, deduped:
        SKIP_REASON="${STATUS_LINE#STATUS: skipped }"
        if [[ "$SKIP_REASON" == tags_missing || "$SKIP_REASON" == no_plan_dir || "$SKIP_REASON" == missing_args ]]; then
          DEDUP_FILE="$Z_HARNESS_PLAN_DIR/.notify-dedup-session"
          DEDUP_KEY="${Z_HARNESS_SLUG:-unknown}:${SKIP_REASON}"
          if [[ "${Z_HARNESS_NOTIFY:-approval_only}" != "off" ]] && ! grep -qxF "$DEDUP_KEY" "$DEDUP_FILE" 2>/dev/null; then
            PushNotification("Memory review skipped on \`${Z_HARNESS_SLUG:-unknown}\`: \`${SKIP_REASON}\`. Fix to re-enable memory candidates.")
            printf '%s\n' "$DEDUP_KEY" >> "$DEDUP_FILE"
          fi
        fi
        # exit memory-review sub-step quietly
      fi
      ```

   c. **Ready path — first line is `STATUS: ready`:** parse artifact paths:
      ```bash
      CUMULATIVE_DIFF_PATH="${LINES[1]:-}"
      SPEC_PATH="${LINES[2]:-}"
      TAGS_PATH="${LINES[3]:-}"
      DEBUG_MD_PATH="${LINES[4]:-}"
      RUN_DIR="$(dirname "$CUMULATIVE_DIFF_PATH")"
      SLUG_FOR_DESC="${Z_HARNESS_SLUG:-$(basename "$Z_HARNESS_PLAN_DIR")}"
      ```

   d. **Dispatch the review-agent:**
      ```
      Agent(
        subagent_type="review-agent",
        description="Memory review for <SLUG_FOR_DESC>",
        prompt="parent_command: debug
      debug_md_path: <DEBUG_MD_PATH>
      spec_path: <SPEC_PATH>
      cumulative_diff_path: <CUMULATIVE_DIFF_PATH>
      tags_path: <TAGS_PATH>
      index_path: docs/llm/INDEX.json
      run_id: <RUN>
      run_dir: <RUN_DIR>"
      )
      ```

   e. **Parse agent return — extract single fenced ```json block:**
      ```python
      import re, json
      raw = agent_return_text
      m = re.search(r'```json\s*([\s\S]*?)```', raw)
      if not m:
          raise ValueError("no_fenced_block")
      try:
          candidates = json.loads(m.group(1))
      except json.JSONDecodeError as e:
          raise ValueError("json_parse_error") from e
      ```

      - **Parse failure:** log `review_agent_malformed`; push-notify; exit memory-review sub-step.
      - **Agent error / no fenced block:** log `review_agent_failed`; push-notify; exit memory-review sub-step.

   f. **Empty candidates (`[]`):**
      ```bash
      SLUG_JSON="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]) if sys.argv[1] else "null")' \
        "${Z_HARNESS_SLUG:-}")"
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" memory_review_terminal \
        "$(printf '{"state":"ran_empty","skip_reason":null,"parent_command":"debug","candidates":0,"accepted":0,"slug":%s}' \
           "$SLUG_JSON")"
      ```
      Exit memory-review sub-step quietly — no push-notify.

   g. **Candidates ≥ 1:**

      i. Persist to JSONL:
         ```bash
         CANDIDATES_FILE="$RUN_DIR/memory-candidates.jsonl"
         python3 -c '
         import json, sys
         candidates = json.loads(sys.argv[1])
         with open(sys.argv[2], "w") as f:
             for c in candidates:
                 f.write(json.dumps(c) + "\n")
         ' "$CANDIDATES_JSON_STR" "$CANDIDATES_FILE"
         ```

      ii. Log `review_agent_call` and push-notify `memory_candidates_ready`:
          ```bash
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" memory_candidates_ready \
            "$(printf '{"run":"%s","candidates_emitted":%d}' "$RUN" "$N_CANDIDATES")"
          ```
          Push-notify: "Memory review produced `<N>` candidate(s) — please review."

      iii. **Sequential AskUserQuestion per candidate (hard cap: 3 candidates). Source: `incident:debug-<slug>-<RUN>`.**

           For each candidate (index `i`, 0-based; stop after 3):
           ```
           AskUserQuestion(
             title: "Memory candidate <i+1> of <total> — <candidate.candidate_kind>",
             body: "...",
             options: [
               { id: "accept", label: "Accept — persist this candidate" },
               { id: "edit",   label: "Edit — modify before persisting" },
               { id: "skip",   label: "Skip (provide one-word reason)" },
               { id: "skip_all", label: "Skip all remaining" }
             ]
           )
           ```

           - **Accept:** dispatch `/z-suggest-memory --from-candidate-json -` with source `incident:debug-<slug>-<RUN>`. Increment `ACCEPTED`.
           - **Edit:** collect edits, re-present as Accept, dispatch with edited JSON.
           - **Skip (one-word reason):** log `review_candidate_skipped`; increment `SKIPPED`.
           - **Skip-all-remaining:** log `review_skip_all`; break loop.

      iv. **Emit `memory_review_terminal` event (needs_user path only — after loop completes):**
          ```bash
          SLUG_JSON="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]) if sys.argv[1] else "null")' \
            "${Z_HARNESS_SLUG:-}")"
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" memory_review_terminal \
            "$(printf '{"state":"needs_user","skip_reason":null,"parent_command":"debug","candidates":%d,"accepted":%d,"slug":%s}' \
               "$N_CANDIDATES" "$ACCEPTED" "$SLUG_JSON")"
          ```

### Branch: `status: abandoned` (debug was inconclusive — no fix shipped)

Log:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" debug_run_end \
  "$(printf '{"status":"abandoned","hypothesis_cycles":%d,"total_hypotheses_generated":%d}' "$CYCLES" "$N_HYPOTHESES")"
```

Do NOT invoke `run-memory-review.sh` on the abandoned branch. No memory-review telemetry is emitted for inconclusive debug sessions.

## Artifacts produced

- `$Z_HARNESS_PLAN_DIR/DEBUG.md` — single unified artifact with sections:
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
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/round1-orchestrator.md` — pre-dispatch checkpoint of the orchestrator's independent Round 1 hypotheses (contamination mitigation).
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/transcripts/` — consultant transcripts.
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/diff.patch` — fix diff.
- `$Z_HARNESS_PLAN_DIR/MR-REVIEW.md` — optional, if user opted into MR-style review in Phase 9.

## Phase-visibility matrix (consultant context discipline)

Source of truth for what each subagent dispatch sees. Subagent prompts must never include sections outside the listed scope, and must never receive likelihood buckets or posteriors except where listed.

| Phase | Consultant call | Sections passed | Forbidden | Raw test output? |
|---|---|---|---|---|
| 3a (Round 1) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory; doc-fetcher synthesis | Hypothesis Pool (doesn't exist yet); any orchestrator-internal block | No |
| 3b (Round 2) | both, MODE `generate-hypotheses-round2-adversarial` | Problem; Evidence Inventory; Hypothesis Pool (full) | Test Matrix; Experiment Log; Score Updates | No |
| 6 (optional Round 3) | both, MODE `generate-hypotheses-round1` | Problem; Evidence Inventory; eliminated `claim` text + falsifying `discriminating_test` only | priors, likelihoods, posteriors, full Eliminated Alternatives section | No |
| 7 (fix consult) | both, MODE `light-fix` | Problem; Evidence Inventory; winning Hypothesis Pool rows; Experiment Log; draft Root Cause; draft Evidence coverage table | Eliminated Alternatives; Score Updates history | No |

Orchestrator alone reads raw test output and assigns likelihood buckets (Phase 6, step 2). This row never appears in the table.

## Hard rules

- **Never debug without repro.** If repro is impossible and user picks "proceed on inference," document that decision in the Problem section and flag in the Post-mortem Confidence section.
- **Never skip the post-mortem.** Even on a trivial bug — the preventative action-items habit is what makes `/z-debug` different from `/z-fix`.
- **Never skip Codex review on the fix** — the safety gate is non-negotiable.
- **Always emit BOTH Round 1 and Round 2 hypothesis-generation consults** — four subagent calls total during generation (2 in R1 + 2 in R2). Plus a fifth pair in Phase 7 for the fix consult.
- **Likelihood-bucket assignment is orchestrator-only.** Never delegate the `{strongly_falsified, …, strongly_supported}` call to a consultant. Never pass raw test output to a consultant.
- **Orchestrator's Round 1 block MUST be checkpointed to disk** (`archive/<run>/round1-orchestrator.md`) BEFORE consultant dispatch. Re-read from disk at merge time, not from conversation state.
- **Wrong-tool gate (Phase 0) is non-skippable.** If the user already has a hypothesis, exit with a `/z-fix` recommendation — do not proceed.
- **Never proceed past auto-bail thresholds** without explicit user override.
- **Fix-gate is objective and binary.** Opens only when (a) winning hypothesis posterior == `very_high` AND (b) every `EVID-NNN` in the Evidence coverage table has status ∈ `{explained, falsifies_alternative, orthogonal_with_reason}` (zero `unexplained`).
- **No emojis** anywhere in artifacts.
