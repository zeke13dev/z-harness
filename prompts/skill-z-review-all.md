---
description: "Final-gate cross-LLM review of a completed z-harness plan. Runs Gemini + Codex on the cumulative diff against SPEC.md to surface (a) implementation drift across tasks and (b) spec gaps that only surface in aggregate. After findings are aggregated,..."
role: skill
---

You are running the **z-harness `/z-review-all`** final-gate review. This is a holistic cross-task cross-LLM review, intentionally distinct from the per-task review that `/z-implement-all` already performs. Per-task review catches per-task issues; this catches issues that only show up when looking at all tasks together.

<!-- NO_SESSION_GUARD -->
**Session persistence required.** This pipeline spans multiple phases, dispatches subagents, and may need to resume after a pause. If you are running in `--no-session` mode (session is not persisted to disk), stop immediately and tell the user: "`/z-review-all` requires a persistent session. Please restart pi without `--no-session`." Then halt. Do not proceed.

## Pre-Phase 0 — Resume check

**Before entering Phase 0**, check for an existing state file from a prior invocation that reached Phase 3.7:

```bash
# Resolve slug from --slug arg or by enumerating z-harness/plans/*/TASKS.md
# STATE_FILE="$Z_HARNESS_PLAN_DIR/.review_state.json"   (set after slug is known)
# Perform a lightweight slug resolution here only to find the state file path.
# If --slug was passed: EARLY_SLUG="<arg>"; EARLY_PLAN_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$EARLY_SLUG")"
# Otherwise: scan for a single TASKS.md candidate (same logic as Phase 0 step 1).
```

Once `EARLY_PLAN_DIR` is known:

1. If `$EARLY_PLAN_DIR/.review_state.json` **does not exist** → proceed to Phase 0 normally.
2. If it exists, attempt to parse it:
   - **If it fails to parse (invalid JSON):** treat as stale — delete the file, emit a `review_state_corrupt` event with `reason: "parse_error"`, and proceed to Phase 0:
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "pre-resume" review_state_corrupt \
       "$(jq -n --arg slug "$EARLY_SLUG" --arg reason 'parse_error' '{"slug":$slug,"reason":$reason}')"
     rm "$EARLY_PLAN_DIR/.review_state.json"
     ```
   - **If parsed successfully AND `halted: true` AND `halt_reason: "no_ask_blocked"`:** valid halted-state file. Do NOT delete it. Emit `review_resume_from_halt` event, delete the file (so Phase 3.7 re-evaluates fresh), and proceed to Phase 0 (full re-run — Phase 3.7 gate will re-check `check-no-ask`):
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "pre-resume" review_resume_from_halt \
       "$(jq -n --arg slug "$EARLY_SLUG" --arg halt_reason 'no_ask_blocked' '{"slug":$slug,"halt_reason":$halt_reason}')"
     rm "$EARLY_PLAN_DIR/.review_state.json"
     # → proceed to Phase 0 (full re-run)
     ```
   - **If parsed successfully AND `phase_3_7_acknowledged` is not `true` AND not a recognized halt state:** treat as stale — delete the file, emit `review_state_corrupt` with `reason: "missing_field"`, and proceed to Phase 0:
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "pre-resume" review_state_corrupt \
       "$(jq -n --arg slug "$EARLY_SLUG" --arg reason 'missing_field' '{"slug":$slug,"reason":$reason}')"
     rm "$EARLY_PLAN_DIR/.review_state.json"
     ```
3. If parsed successfully with `phase_3_7_acknowledged: true`, validate the state file:
   - Run `git rev-parse HEAD` and compare with `head_sha` in the file.
   - Check that the files at `cumulative_diff_path` **and** `cumulative_stat_path` both still exist on disk. If either is missing, treat as stale (delete state file, full re-run).
   - **If HEAD matches AND both artifact files are present:**
     - **Fast-forward environment restore** — set all variables Phase 4 requires from state-file fields:
       ```bash
       Z_HARNESS_SLUG="<slug from state or slug resolution>"
       Z_HARNESS_PLAN_DIR="$EARLY_PLAN_DIR"
       BASE="$EARLY_PLAN_DIR"
       BASE_REF="<base_ref from state file>"
       HEAD_SHA="<head_sha from state file>"
       RRUN="<run_id from state file>"
       cumulative_diff_path="<cumulative_diff_path from state file>"
       cumulative_stat_path="<cumulative_stat_path from state file>"
       ```
     - Emit `review_resume_fast_forward` event:
       ```bash
       bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_resume_fast_forward \
         "$(jq -n --arg slug "$Z_HARNESS_SLUG" --arg head_sha "$HEAD_SHA" --arg path "$cumulative_diff_path" \
           '{"slug":$slug,"head_sha":$head_sha,"cumulative_diff_path":$path}')"
       ```
     - Skip Phases 0–3.5. Jump directly to Phase 4.
   - **If HEAD has changed OR either artifact file is missing:**
     - Delete the stale state file: `rm "$EARLY_PLAN_DIR/.review_state.json"`
     - Proceed to Phase 0 for a full re-run.

## Phase 0 — Discover plan slug

Same logic as `/z-implement-all` / `/z-implement-next`:

1. Enumerate subdirs of `z-harness/` containing a `TASKS.md`. Also check legacy flat `z-harness/TASKS.md`.
2. Single candidate → use it. Multiple → `AskUserQuestion` to pick (or honor `--slug <slug>` argument). Zero → tell user nothing to review; stop.
3. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` (or leave unset for legacy flat).
4. `BASE = $Z_HARNESS_PLAN_DIR` (or `z-harness` for legacy).

**Clear the notify-dedup session file** (once per top-level invocation):
```bash
[[ -n "${BASE:-}" ]] && rm -f "$BASE/.notify-dedup-session"
```

Pick a review run id: `RRUN=$(date -u +%Y%m%dT%H%M%SZ)-review`. Create `$BASE/archive/$RRUN/`.

**Version stamp + log run start:**
```bash
VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
START_PAYLOAD="$(python3 -c '
import json, sys
v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
print(json.dumps(v))
' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_all_start "$START_PAYLOAD"
```

**Kernel path resolution (once per run, immediately after review_all_start):**
```bash
KERNEL_PATH="$(bash scripts/resolve-kernel.sh 2>/dev/null || true)"
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

## Phase 1 — Sanity check task status

Read `$BASE/TASKS.md`. Count `[ ]`, `[~]`, `[x]`, and skip-flagged tasks.

- If any `[~]` (in-progress) exist → abort with "Stop — task X is still in progress."
- If any `[ ]` (pending, not skip-flagged) exist → warn the user via `AskUserQuestion`:
  - **Review anyway** (incomplete plan)
  - **Cancel** (finish implementation first)
- If all `[x]` or only skip-flagged remain → proceed.

## Phase 2 — Determine the base git ref

The cumulative diff is `git diff <base-ref>..HEAD` across all the changes this plan introduced. Determine `<base-ref>`:

1. If user passed `--base <ref>` argument → use it.
2. Otherwise:
   - Find the first `task_start` event in `$BASE/metrics.jsonl` (or `events.jsonl` for the slug-namespaced events). That's the plan's start timestamp `T_start`.
   - `BASE_REF=$(git rev-list -n1 --before="$T_start" HEAD)`
   - If that fails or returns nothing, fall back to `BASE_REF=$(git log --oneline | head -50 | grep -i "before z-plan\|baseline\|pre-z" | head -1 | awk '{print $1}')` and if still nothing, **ask the user** for the base ref via `AskUserQuestion`.

Confirm the chosen base ref with the user before diffing, showing the short commit message: `git show --no-patch --format='%h %s' $BASE_REF`.

## Phase 3 — Build the cumulative diff

```bash
git diff "$BASE_REF"..HEAD > "$BASE/archive/$RRUN/cumulative.diff"
wc -l "$BASE/archive/$RRUN/cumulative.diff"
```

Also produce a per-file summary:
```bash
git diff --stat "$BASE_REF"..HEAD > "$BASE/archive/$RRUN/cumulative.stat"
```

If `cumulative.diff` exceeds ~500k lines, warn the user — the LLMs will be unable to ingest it; you may need to chunk by directory or by phase.

## Phase 3.5 — Run full test suite for affected modules (only if `$BASE/TESTS.md` exists)

If `$BASE/TESTS.md` was produced by `/z-test` and `$BASE/test-runner.json` was populated by `/z-implement-all`, run the full test suite for modules touched by `cumulative.diff` before spawning the consultants. Reasoning: per-task acceptance checks only ran each test in isolation; running the suite together catches inter-test ordering bugs and shared-state regressions that the per-task gate misses.

### Check TESTS.md version

```bash
VERSION="$(grep -m1 '^\*\*Version:\*\*' "$BASE/TESTS.md" 2>/dev/null | sed 's/.*Version:\*\* *//' | tr -d '[:space:]' || echo '1')"
```

### Run per-task tests

Always run the per-task tests first (same test suite the per-task acceptance checks ran, but together):

```bash
TEMPLATE="$(jq -r .cmd_template "$BASE/test-runner.json")"
FRAMEWORK="$(jq -r .framework "$BASE/test-runner.json")"
AFFECTED_DIRS="$(git diff --name-only "$BASE_REF"..HEAD | xargs -I{} dirname {} | sort -u)"
SUITE_LOG="$BASE/archive/$RRUN/suite.log"
: > "$SUITE_LOG"
SUITE_FAILED=0
for DIR in $AFFECTED_DIRS; do
  CMD="$(echo "$TEMPLATE" | sed "s|{TARGET_FILE}|$DIR|g; s|{TEST_NAME}||g")"
  echo "===== $CMD =====" >> "$SUITE_LOG"
  eval "$CMD" >> "$SUITE_LOG" 2>&1 || SUITE_FAILED=$((SUITE_FAILED+1))
done
```

### Run full-chain tests (v2 only)

If `$VERSION` is `2`, also check for full-chain test entries. For each TEST-NNN with `**Layer:** full-chain`, check whether the `**Target file:**` exists (it should have been written by T017 after all per-task implementation is complete):

```bash
if [ "$VERSION" = "2" ]; then
  FULL_CHAIN_LOG="$BASE/archive/$RRUN/full-chain-suite.log"
  : > "$FULL_CHAIN_LOG"
  FULL_CHAIN_FAILED=0
  FULL_CHAIN_TOTAL=0

  # Extract full-chain test targets from TESTS.md
  FULL_CHAIN_ENTRIES="$(awk '/^## TEST-/ { cur=$2 }
    /^\*\*Layer:\*\*/ && /full-chain/ { print cur }' "$BASE/TESTS.md")"

  for TID in $FULL_CHAIN_ENTRIES; do
    FULL_CHAIN_TOTAL=$((FULL_CHAIN_TOTAL+1))
    TARGET="$(awk -v id="$TID" '/^## /{cur=$0; found=0} cur ~ id {found=1} found && /^\*\*Target file:\*\*/{print $3; exit}' "$BASE/TESTS.md")"

    if [ -z "$TARGET" ] || [ ! -f "$TARGET" ]; then
      echo "[SKIP] $TID — target file $TARGET does not exist (full-chain test not yet written)" >> "$FULL_CHAIN_LOG"
      continue
    fi

    CMD="$(echo "$TEMPLATE" | sed "s|{TARGET_FILE}|$TARGET|g; s|{TEST_NAME}|$TID|g")"
    echo "===== $CMD =====" >> "$FULL_CHAIN_LOG"
    if eval "$CMD" >> "$FULL_CHAIN_LOG" 2>&1; then
      echo "[PASS] $TID" >> "$FULL_CHAIN_LOG"
    else
      echo "[FAIL] $TID — invariant violation detected" >> "$FULL_CHAIN_LOG"
      FULL_CHAIN_FAILED=$((FULL_CHAIN_FAILED+1))
    fi
  done

  if [ "$FULL_CHAIN_TOTAL" -eq 0 ]; then
    echo "No full-chain tests defined in TESTS.md" >> "$FULL_CHAIN_LOG"
  fi

  # Categorize full-chain failures as "invariant violations"
  if [ "$FULL_CHAIN_FAILED" -gt 0 ]; then
    echo "FULL-CHAIN INVARIANT VIOLATIONS: $FULL_CHAIN_FAILED test(s) failed." >> "$FULL_CHAIN_LOG"
  fi
fi
```

**Missing full-chain targets.** If full-chain test files don't exist yet, skip gracefully with an info-level log entry — this is not an error (they may not have been written yet by T017). Only existing full-chain test files are executed.

**Full-chain failures.** When full-chain tests fail, categorize them as a distinct category: **"full-chain invariant violations"** in the review output. These indicate that a system-level behavioral invariant was violated by the composed end-to-end path.

**Per-task failures.** Any per-task test failure is a blocker. Surface the failing log slice to the user before proceeding to Phase 4. Treat the same way as a Prong-A finding of severity `blocker` — `/z-review-all` cannot accept a plan whose own tests are broken.

**Legacy v1.** If TESTS.md has no `**Version:** 2` header, run all tests as before (legacy behavior — no full-chain distinction).

Skip this entire phase if either TESTS.md or test-runner.json is absent (no harm — older plans without /z-test predate this step).

## Phase 3.6 — Pre-review cycle (opt-in)

**Opt-in gate:** Only runs if `Z_HARNESS_PRE_REVIEW` is set to `1` (env var). Check at phase start:

```bash
if [ "${Z_HARNESS_PRE_REVIEW:-0}" != "1" ]; then
  echo "Pre-review cycle skipped (Z_HARNESS_PRE_REVIEW != 1)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" pre_review_skipped \
    '{"reason":"opt_in_disabled"}'
  # Jump to Phase 3.7
  return 0
fi
```

When enabled, spawn **3 pre-reviewers in parallel** to do a fast first-pass scan. Each pre-reviewer runs on the cheapest available model (haiku). Their findings are collected and fed as additional context into the Phase 4 consultant prompts.

Each pre-reviewer gets the same inputs:
- `$BASE/SPEC.md`
- `$BASE/PLAN.md`
- `$BASE/TASKS.md`
- `$BASE/archive/$RRUN/cumulative.diff`
- `$BASE/archive/$RRUN/cumulative.stat`

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="pre-reviewer",
  description="Pre-review 1 — correctness & spec drift (Flash) for <slug>",
  prompt="MODE: final-review-prong-a
slug: <slug>
run_id: <RRUN>
Kernel path: <KERNEL_PATH>

SPEC.md: $BASE/SPEC.md
PLAN.md: $BASE/PLAN.md
TASKS.md: $BASE/TASKS.md
cumulative_diff_path: $BASE/archive/$RRUN/cumulative.diff
cumulative_stat_path: $BASE/archive/$RRUN/cumulative.stat

Focus: PRONG A — Implementation drift. Is the cumulative diff faithful to SPEC.md? Look for files that should have changed but didn't, files that changed wrong, cross-task drift (inconsistent naming/types), stale references, and missing tests called out in acceptance criteria. Be fast and cheap — surface only clear blockers and majors."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="pre-reviewer",
  description="Pre-review 2 — spec gaps & edge cases (Flash) for <slug>",
  prompt="MODE: final-review-prong-b
slug: <slug>
run_id: <RRUN>
Kernel path: <KERNEL_PATH>

SPEC.md: $BASE/SPEC.md
PLAN.md: $BASE/PLAN.md
TASKS.md: $BASE/TASKS.md
cumulative_diff_path: $BASE/archive/$RRUN/cumulative.diff
cumulative_stat_path: $BASE/archive/$RRUN/cumulative.stat

Focus: PRONG B — Spec gaps and missed edge cases. Now that the implementation is done, what's wrong with the spec itself? Decisions in PLAN.md that turned out wrong. Edge cases the spec missed. Public surfaces that should be broader/narrower. Be fast and cheap — surface only clear blockers and majors."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="pre-reviewer",
  description="Pre-review 3 — code quality & structural issues (Flash) for <slug>",
  prompt="MODE: final-review-quality
slug: <slug>
run_id: <RRUN>
Kernel path: <KERNEL_PATH>

SPEC.md: $BASE/SPEC.md
PLAN.md: $BASE/PLAN.md
TASKS.md: $BASE/TASKS.md
cumulative_diff_path: $BASE/archive/$RRUN/cumulative.diff
cumulative_stat_path: $BASE/archive/$RRUN/cumulative.stat

Focus: CODE QUALITY — defensive bloat, premature abstraction, DRY/KISS/SOLID violations, test noise, stale comments, over-engineering. Not correctness — assume the code works. Focus on maintainability and quality. Be fast and cheap — surface only clear blockers and majors."
)
```

**Collecting pre-review findings:** After all three return, read their outputs. Write a consolidated pre-review summary to `$BASE/archive/$RRUN/pre-review.md`:

```markdown
# Pre-review summary — <slug>
Run: <RRUN>

## Pre-review 1 — correctness & spec drift
<verbatim findings from pre-reviewer 1, or "CLEAN">

## Pre-review 2 — spec gaps & edge cases
<verbatim findings from pre-reviewer 2, or "CLEAN">

## Pre-review 3 — code quality & structural issues
<verbatim findings from pre-reviewer 3, or "CLEAN">
```

**Feeding into Phase 4:** The consolidated `$BASE/archive/$RRUN/pre-review.md` path is added as a context item in the Phase 4 consultant prompts. Each consultant's prompt gains a section:

```
Pre-review findings (3 × DeepSeek V4 Flash fast scan):
<contents of $BASE/archive/$RRUN/pre-review.md>

These are cheap pre-screener findings — validate them critically before accepting. The real work is your own analysis.
```

## Phase 3.7 — Pre-consult compaction breakpoint

**Always runs** between Phase 3.5 and Phase 4 (unless fast-forwarded via the Pre-Phase 0 resume check).

Emit the compaction pause event:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" compaction_pause \
  '{"trigger":"pre_consult","phase":"review_all_phase_4"}'
```

**No-ask gate — run first, before the resolver:**

```bash
NOASK_JSON="$(python3 scripts/config.py check-no-ask --question-id workflow.review_all_proceed)"
NOASK_EXIT=$?
NOASK_RESULT="$(echo "$NOASK_JSON" | jq -r .result)"

if [[ $NOASK_EXIT -eq 5 ]]; then
  echo "config_conflict: Z_HARNESS_ASK_ALL=1 and Z_HARNESS_NO_ASK=halt are mutually exclusive" >&2
  exit 5
fi
```

- **If `$NOASK_RESULT == "halt"`:** Emit `review_halt` event, write partial `.review_state.json`, and exit cleanly — do NOT invoke `AskUserQuestion`:
  ```bash
  if [[ "$NOASK_RESULT" == "halt" ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_halt \
      "$(printf '{"reason":"no_ask_blocked","question_id":"workflow.review_all_proceed","rule_id":"no_ask_halt"}')"
    echo "halt: no_ask_blocked on workflow.review_all_proceed" >&2
    python3 -c "
import json, datetime, sys
state = {
  'phase_3_7_acknowledged': False,
  'halted': True,
  'halt_reason': 'no_ask_blocked',
  'halted_at': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
}
path = sys.argv[1]
with open(path, 'w') as f:
    json.dump(state, f, indent=2)
" "$Z_HARNESS_PLAN_DIR/.review_state.json" 2>/dev/null \
      || echo "warn: could not write .review_state.json" >&2
    exit 0
  fi
  ```

- **If `$NOASK_RESULT == "proceed"`:** Run the full resolver for preference-based skip/prefill/ask:
  ```bash
  RESOLVED="$(python3 scripts/config.py resolve-question workflow.review_all_proceed)"
  RESOLVE_EXIT=$?
  if [[ $RESOLVE_EXIT -ne 0 ]]; then
    RESULT="ask"; DEFAULT=""; SOURCE="error"
  else
    RESULT="$(echo "$RESOLVED" | jq -r .result)"
    DEFAULT="$(echo "$RESOLVED" | jq -r .default)"
    SOURCE="$(echo "$RESOLVED" | jq -r .source)"
  fi
  ```

  - **`skip`:** Skip the `AskUserQuestion`. Emit `askuser_skipped` event:
    ```bash
    if [[ "$RESULT" == "skip" ]]; then
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" askuser_skipped \
        "$(printf '{"question_id":"workflow.review_all_proceed","source":"%s"}' "$SOURCE")"
    fi
    ```
  - **`prefill`:** Present AskUserQuestion with `$DEFAULT` pre-selected.
  - **`ask`:** Present AskUserQuestion normally.

When resolver result is `prefill` or `ask`, present an `AskUserQuestion` with exactly two options:

> **Compaction breakpoint — pre-consultant spawn**
>
> You are about to dispatch the cross-LLM consultant subagents (Phase 4). These are context-heavy; starting them on a fresh context window improves quality.
>
> **Options:**
> - **(a) Pause for /clear** — exit now so you can run `/clear`, then re-invoke `/z-review-all` to resume. No state file is written; Phase 3.7 will prompt again on the next invocation (correct — you wanted to re-evaluate).
> - **(b) Proceed now** — continue into Phase 4 immediately. A state file will be written so a subsequent re-invocation (e.g. after an interruption) can fast-forward past Phases 0–3.5.

**If the user picks (a) — Pause for /clear:**
- Exit cleanly. Do **not** write `.review_state.json`.
- The next `/z-review-all` invocation will run Phase 0–3.7 again.

**If the user picks (b) — Proceed now:**
- Write `$Z_HARNESS_PLAN_DIR/.review_state.json` with this schema:
  ```json
  {
    "phase_3_7_acknowledged": true,
    "run_id": "<RRUN — the current review run id, e.g. 20260524T120000Z-review>",
    "base_ref": "<BASE_REF captured in Phase 2>",
    "head_sha": "<output of git rev-parse HEAD at this moment>",
    "cumulative_diff_path": "<absolute path to $BASE/archive/$RRUN/cumulative.diff>",
    "cumulative_stat_path": "<absolute path to $BASE/archive/$RRUN/cumulative.stat>",
    "acknowledged_at": "<ISO-8601 timestamp>"
  }
  ```
  If the write fails, log a warning to stderr and proceed (do not block on a filesystem hiccup).
- Continue to Phase 4.

## Phase 4 — Spawn final-review consultants (parallel)

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

- `$BASE/SPEC.md` (the spec)
- `$BASE/PLAN.md` (the plan with decisions)
- `$BASE/TASKS.md` (what was supposed to happen, with completion notes)
- `$BASE/archive/$RRUN/cumulative.diff` (what actually happened)
- `$BASE/archive/$RRUN/cumulative.stat` (file-touch overview)
- **`docs/llm/INDEX.json` (if exists)** + the concept JSONs for any `source_file` that appears in `cumulative.stat`. The LLM-tier docs state invariants that span tasks; a "drift" finding from the consultant carries more weight if it cites a specific invariant from a docs/llm/ entry.

Each is asked the **two-pronged** review:

**Prong A — Implementation faithfulness.** Does the cumulative diff implement SPEC.md as written? List drift:
- Files that should have changed per SPEC but didn't.
- Files that changed but don't match the spec'd surface/behavior.
- Cross-task drift (e.g. T010 created `key_x`, T020 reads a similar-but-different `key_y`).
- Stale references introduced (deleted callees, refactors that didn't propagate).
- Missing tests / assertions called out in spec acceptance criteria.

**Prong B — Spec correctness.** Now that the implementation is done, is the spec itself correct/sufficient? List spec gaps:
- Decisions made in PLAN.md that turned out wrong when implemented.
- Invariants the spec asserted that the code can't actually satisfy.
- Edge cases the spec missed (and that the code either silently handles or breaks on).
- Public surfaces the spec defined that should have been broader/narrower.
- Whole categories of behavior the spec failed to anticipate.

### Calling pattern

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Final-review (Gemini) for plan <slug>",
  prompt="MODE: final-review-2pronged\n\n<full prompt with both prongs, plus paths to SPEC/PLAN/TASKS and cumulative.diff>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Final-review (Codex) for plan <slug>",
  prompt="MODE: final-review-2pronged\n\n<same>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

Both consultants are already on `model: haiku` — they just shell out to gemini/codex CLIs. The actual reasoning is done by Gemini and Codex themselves.

Transcripts are archived by each consultant under `$BASE/archive/$RRUN/transcripts/` per the consultant's own logging.

## Phase 5 — Aggregate findings

Before promotion, classify each accepted finding using the shared review-family promotion contract:

- `implementation_drift` → candidate fixup task.
- `spec_gap` → amendment proposal task that routes through `/z-amend`; never edit `SPEC.md` directly.
- `completed_task_contradiction` → fresh superseding task; never mutate a completed `[x]` task in place.
- `premise_failure` → escalation section, not implementer work.
- `observation` → keep in `findings.md` only.

Every promoted finding must include source, severity, evidence, the "one reason this might be wrong" pushback, files, disposition, and acceptance criteria.

Read both consultants' returns. Build `$BASE/archive/$RRUN/findings.md` with this structure:

```markdown
# Final review — <slug>
Run: <RRUN>
Base ref: <BASE_REF>
Diff stats: <X files, Y additions, Z deletions>

## Prong A — Implementation drift

### Severity: blocker
- [from gemini | from codex | both] <finding>
- ...

### Severity: major
- ...

### Severity: minor
- ...

## Prong B — Spec gaps

### Severity: blocker (spec must be corrected before shipping)
- ...

### Severity: major (spec should be amended; existing implementation may stand)
- ...

### Severity: minor (worth noting for future plans)
- ...

## Consensus vs disagreement
- Items both LLMs flagged: <list> (high confidence)
- Items only one flagged: <list> (worth manual scrutiny)
```

Apply the **one-reason-it-might-be-wrong** rule from `/z-plan` to every finding before listing it. Push back on weak findings.

## Phase 5.5 — Invariant + error-point extraction from review findings

**Gate:** Runs if EITHER `docs/INVARIANTS.json` or `docs/ERROR_POINTS.json` exists, AND `$BASE/archive/$RRUN/findings.md` contains findings with severity ≥ major. If only ERROR_POINTS.json exists, skip invariant extraction but still run error-point extraction. If only INVARIANTS.json exists, run invariant extraction only.

**Rate-limiting constants:**
```bash
Z_HARNESS_ERROR_POINT_MAX_NEW=10      # max new error points per review run
Z_HARNESS_ERROR_POINT_PRUNE_DAYS=90   # idle days before eligible error point is pruned
Z_HARNESS_ERROR_POINT_PRUNE_MAX_FREQ=3  # max frequency for pruning eligibility
SIGHTINGS_RING_BUFFER_MAX=20          # max sightings entries per error point
```

Goal: (a) Match review findings against existing invariants to increment `sighting_count`/`last_sighting`/`anchor_module`, (b) match review findings against existing error points by deterministic `pattern_signature`, (c) extract NEW invariant candidates from unmatched findings, (d) create NEW error point candidates from unmatched findings. Turns real-world review discoveries into durable per-repo data for `/z-test`.

**Procedure:**

1. **Read structured findings.** Parse `$BASE/archive/$RRUN/findings.md`. Collect all findings with severity ≥ major (blocker or major). Skip minor findings and observations.

2. **Read existing registries.**
   - If `docs/INVARIANTS.json` exists: load all invariants (`id`, `description`, `tags`, `failure_class`, `sighting_count`, `last_sighting`, `anchor_module`, `severity`).
   - If `docs/ERROR_POINTS.json` exists: load all error points — both active AND archived (`ep_id`, `pattern`, `pattern_signature`, `anchor_module`, `failure_class`, `severity`, `frequency`, `sightings`, `tests_targeting`, `archived`, `archived_at`).

3. **Pre-Haiku deterministic pattern_signature matching (orchestrator computes).** For each finding with severity ≥ major:

   a. Extract `module_path` from the finding's evidence (first file path cited).
   b. Truncate to first 3 path segments: `"/".join(module_path.split("/")[:3])` (e.g., `skills/z-test/SKILL.md` → `skills/z-test`).
   c. Normalize `finding_class`: lowercase, strip all punctuation (keep alphanumerics and spaces).
   d. Compute the deterministic `pattern_signature` using SHA-256 of the concatenation:
      `sha256(module_path_prefix :: normalized_finding_class :: severity)[:16]`
      where:
      - `module_path_prefix` = first 3 path segments of the finding's evidence file
      - `normalized_finding_class` = the finding's `failure_class` (or `finding_class`) text, lowercased and punctuation-stripped
      - `severity` = the finding's severity as-is (`blocker`, `major`, or `minor`)
      ```python
      import hashlib
      sig = hashlib.sha256(f"{module_prefix}::{finding_class_norm}::{severity}".encode()).hexdigest()[:16]
      ```
   e. Look up this `pattern_signature` in existing ERROR_POINTS.json entries (both active AND archived).

   **Deterministic match on ACTIVE error point:**
   - Increment `frequency` (capped: max +1 per error point per review run — if already incremented this run, skip).
   - Append to `sightings[]` (ring-buffer: prepend, keep newest 20, drop oldest).
   - Update `last_seen` to current timestamp.
   - Update `anchor_module` if the new finding's module_path differs (track pattern migration).
   - Mark finding as `matched` — exclude from Haiku prompt.

   **Deterministic match on ARCHIVED error point (resurrection):**
   - Set `archived: false`, `archived_at: null`.
   - Reset `frequency` to 1.
   - Reset `sightings` to a single entry for this finding.
   - Update `last_seen`, `first_seen`, `anchor_module`.
   - Mark finding as `matched` — exclude from Haiku prompt.

   Findings WITHOUT deterministic matches proceed to the Haiku subagent.

4. **Dispatch Haiku subagent for LLM matching + candidate extraction.** One-shot call. The Haiku only sees findings NOT already deterministically matched. Prompt structure:

   ```
   MODE: extract-invariants-and-error-points

   You have N unmatched review findings (severity ≥ major) from a /z-review-all run.
   For each finding, determine if it matches an existing invariant OR existing error point,
   OR if neither, draft a new candidate.

   Review findings (unmatched):
   <list each finding: severity, class, description, evidence, module_path>

   Existing invariants (for matching by failure_class similarity):
   <list: id, description, failure_class, sighting_count, last_sighting, severity>

   Existing error points (for fuzzy matching — deterministic matches already handled):
   <list: ep_id, pattern, pattern_signature, failure_class, frequency>

   Return a JSON object with three arrays:

   1. invariant_matches: findings that match an EXISTING invariant.
      [{"finding_ref": "<short ref>", "invariant_id": "inv_NNN", "match_type": "llm"}]

   2. invariant_candidates: findings WITHOUT a covering invariant — draft new invariant.
      [{"finding_ref": "<short ref>", "invariant_description": "<1-line>", "tags": ["t1","t2"],
        "failure_class": "<violation description>", "severity": "blocker"|"major"}]

   3. error_point_candidates: findings that don't match any invariant — draft new error point.
      [{"finding_ref": "<short ref>", "pattern": "<1-line pattern>",
        "failure_class": "<violation description>", "severity": "blocker"|"major"}]
   ```

5. **Write processing (orchestrator after Haiku returns).**

   **5a. Apply invariant matches (from Haiku's `invariant_matches`):**
   - For each match, increment `sighting_count` on the invariant (capped: max +1 per invariant per review run).
   - Update `last_sighting` to current timestamp.
   - Set `anchor_module` from the finding's module_path (first match wins per run).

   **5b. Apply invariant candidates (from Haiku's `invariant_candidates`):**
   - Unchanged from prior behavior. Assign `id` sequentially (`inv_NNN`).
   - Present for user approval (step 6).

   **5c. Apply error-point candidates (from Haiku's `error_point_candidates`):**
   - For each candidate, compute `pattern_signature` deterministically (same formula as step 3).
   - Check the signature against ALL existing error points (Haiku may propose a candidate that should have matched deterministically — deduplicate silently, increment existing entry instead).
   - Cap new entries at `Z_HARNESS_ERROR_POINT_MAX_NEW` (default 10). Overflow candidates are logged to `$BASE/archive/$RRUN/error-point-overflow.log` and dropped for this run.
   - For each new entry:
     - Assign `ep_id` sequentially starting after highest existing ID.
     - Set `frequency: 1`, `first_seen: <now>`, `last_seen: <now>`.
     - Set `sightings: [{run_id, finding_id, module_path}]`.
     - Compute `novelty_score = 1 / (1 + frequency)` = 0.5.
     - Set `archived: false`, `last_test_pass: null`, `last_test_fail: null`, `tests_targeting: []`.

   **5d. Atomic write + validate both registries:**
   - Write INVARIANTS.json (tmpfile → flush → fsync → os.replace()).
   - Validate: `python3 scripts/validate-invariants.py --file docs/INVARIANTS.json`.
   - Write ERROR_POINTS.json (same atomic discipline).
   - Validate: `python3 scripts/validate-error-points.py --file docs/ERROR_POINTS.json`.

   **5e. Pruning (after all writes):**
   - Scan ERROR_POINTS.json for entries where ALL of:
     - `tests_targeting` has ≥ 1 entry (a test was written for this pattern)
     - `last_seen` is older than `Z_HARNESS_ERROR_POINT_PRUNE_DAYS` days ago (default 90)
     - `frequency ≤ Z_HARNESS_ERROR_POINT_PRUNE_MAX_FREQ` (default 3 — don't prune hot patterns)
   - For eligible entries: set `archived: true`, `archived_at: <now>`.
   - Log pruned count. Archived entries remain in the matching index for resurrection.

6. **Batch user approval.** Present the extracted invariant candidates (unchanged from prior behavior):

   > "N invariant candidates extracted from review findings. Promote to INVARIANTS.json?"
   > - (a) Accept all — write candidates and approve automatically
   > - (b) Let me pick — show each candidate with accept/skip
   > - (c) Skip all — discard candidates

   Note: error-point candidates are auto-written without user approval (they're empirical, not declared). The user gate applies only to invariant candidates (declared truths require human judgment).

7. **On accept-all (a):** Write all invariant candidates to INVARIANTS.json using atomic write discipline. Validate with `scripts/validate-invariants.py`. Regenerate INVARIANTS.md. Log to archive.

8. **On let-me-pick (b):** Show each candidate individually with accept/skip. After all decisions, write the accepted subset to INVARIANTS.json atomically.

9. **On skip-all (c):** Log "Invariant extraction skipped by user" to archive log. Continue.

10. **Hard rule (preserved and extended):** Extraction failure MUST NOT halt the review pipeline. If any phase errors (bad JSON from Haiku, file read failure, validation failure), log the error to `$BASE/archive/$RRUN/invariant-extraction-error.log` and continue to Phase 6. Error-point extraction failures are also soft phases — log and continue. The review pipeline is ALWAYS the priority.

## Phase 6 — Promote findings to review tasks

Build `$BASE/REVIEW-TASKS.md` and snapshot the same content to `$BASE/archive/$RRUN/REVIEW-TASKS.md`. This is a candidate artifact: the user deletes anything they reject before applying it.

Use this structure:

```markdown
---
artifact: review-tasks
slug: <slug>
run_id: <RRUN>
source_findings: archive/<RRUN>/findings.md
drift_findings: <n>
spec_gap_findings: <m>
escalations: <k>
---

# Review Tasks — <slug>

Findings promoted from `/z-review-all`. Delete any candidate you do not want fixed, then run:

`/z-implement-all --tasks $BASE/REVIEW-TASKS.md`

## Candidate fixup tasks

### [ ] T-REV-001 — [blocker] <short title>
- **Class:** implementation_drift
- **Source:** Prong A; <gemini|codex|both>; finding <stable reference or short quote>
- **Pushback:** <one reason this might be wrong>
- **Files:** `<path>:<line>` (modified)
- **Depends on:** none | T-REV-00N
- **Acceptance:** <verifiable criteria>

## Amendment proposals

### [ ] T-REV-002 — [major] Amend spec: <short title>
- **Class:** spec_gap
- **Disposition:** amendment_proposal
- **Source:** Prong B; <gemini|codex|both>; finding <stable reference or short quote>
- **Pushback:** <one reason this might be wrong>
- **Files:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
- **Depends on:** none | T-REV-00N
- **Acceptance:** run `/z-amend "<specific amendment>"`; resulting SPEC/PLAN/TASKS reflect the amendment and preserve completed-task state.

## Superseding tasks

### [ ] T-REV-003 — [major] Supersedes T0NN: <short title>
- **Class:** completed_task_contradiction
- **Disposition:** superseding_task
- **Source:** <finding reference>
- **Pushback:** <one reason this might be wrong>
- **Files:** <files to revisit>
- **Depends on:** none | T-REV-00N
- **Acceptance:** new work corrects or replaces the completed task behavior without editing the completed `[x]` task in place.

## Escalations

- **Premise failure:** <finding>. Recommended next: `/z-plan <affected scope>`.

## Report-only observations

- <minor/speculative finding left in findings.md only>
```

If there are no actionable findings and no escalations, write `$BASE/archive/$RRUN/shipped.md` acknowledging the clean final review and omit `REVIEW-TASKS.md`.

## Phase 6.5 — Auto-amend review findings (severity-based)

After `REVIEW-TASKS.md` is built, auto-apply amendment proposals based on severity. The cross-LLM review already validated these findings — asking "do you want to amend?" per finding wastes tokens. Plan-artifact amendments (spec_gap) are applied automatically via `/z-amend --skip-user-gate`. Implementation changes (implementation_drift) stay as candidate fixup tasks for the user to review and prune before `/z-implement-all`.

**Hard rules for this phase:**
- Do NOT ask "do you want to amend?" for blocker/major/minor amendment proposals. Just do it.
- Do NOT auto-amend if the amendment would touch a `[x]` (completed) task — those are `superseding_task` items and stay in REVIEW-TASKS.md for user disposition.
- Do NOT auto-implement code changes — only auto-amend plan artifacts (SPEC.md, PLAN.md, TASKS.md).
- Log everything: write `$BASE/archive/$RRUN/auto-amend-log.md`.

**Procedure:**

1. **Skip if no REVIEW-TASKS.md** — a clean review produced `shipped.md` instead. Nothing to auto-amend. Continue to Cleanup.

2. **Read `$BASE/REVIEW-TASKS.md`** and identify every task block where `**Disposition:** amendment_proposal`. These are spec_gap findings routed through `/z-amend`. Candidate fixup tasks (`**Disposition:** candidate_task`) and superseding tasks (`**Disposition:** superseding_task`) are left alone.

3. **For each amendment proposal:**
   - Read its `**Class:**` — if `completed_task_contradiction` (superseding_task), **skip it** (touches completed work; user must decide disposition).
   - Read its `**Severity:**` — `blocker`, `major`, or `minor` all get auto-amended.
   - Read its `**Acceptance:**` line — it contains the `/z-amend` command (e.g. `run /z-amend "Add error-handling invariants to SPEC.md §3.2"`).
   - Extract the amendment text (the quoted string after `/z-amend`).
   - Invoke `/z-amend --skip-user-gate "<amendment text>"` inline (not via subagent — same session). Follow the `/z-amend` pipeline (Phase 0–8) for this slug, with Phase 4 (user gate) skipped per the flag.
   - After the amendment lands, verify by re-reading the affected artifacts (SPEC.md, PLAN.md, TASKS.md) to confirm the changes took effect.
   - Log each amendment to `$BASE/archive/$RRUN/auto-amend-log.md`.

4. **Escalations and report-only observations** — remain in findings.md only. No auto-action.

5. **Write the auto-amend log** to `$BASE/archive/$RRUN/auto-amend-log.md`:

   ```markdown
   # Auto-amend log — <slug>
   Run: <RRUN>
   Auto-amended at: <ISO-8601 timestamp>

   ## Amendments applied

   ### T-REV-00N — [<severity>] <title>
   - **Source:** Prong <A|B>; <gemini|codex|both>; <finding reference>
   - **Command:** `/z-amend --skip-user-gate "<amendment text>"`
   - **Result:** applied
   - **Artifacts changed:** <SPEC.md | PLAN.md | TASKS.md — whichever were modified>

   ## Amendments skipped
   <list any proposals that were skipped and why, or "None">

   ## Not amendable
   - Candidate fixup tasks (implementation_drift) left in REVIEW-TASKS.md: <count>
   - Escalations left in findings.md: <count>
   ```

6. **Emit an `auto_amend_applied` event** for each successful amendment:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" auto_amend_applied \
     "$(jq -n --arg finding_id "T-REV-00N" --arg severity "<severity>" \
        '{"finding_id":$finding_id,"severity":$severity}')"
   ```

7. **If no amendment proposals are amendable** (all findings are fixup tasks, superseding tasks, or the review was clean), skip this entire phase — no log file, no events. Continue to Cleanup.

**What stays in REVIEW-TASKS.md after this phase:**
- **Candidate fixup tasks** (implementation_drift) — NEVER auto-implemented. User reviews and prunes before `/z-implement-all --tasks $BASE/REVIEW-TASKS.md`.
- **Superseding tasks** (completed_task_contradiction touching `[x]` tasks) — user must decide disposition.
- **Premise failure escalations** — user decides next step.
- **Any amendment that failed to apply** — logged with reason in auto-amend-log.md, left in REVIEW-TASKS.md for manual resolution.

**Cleanup (unconditional — applies to both success outcomes: REVIEW-TASKS.md generated OR clean shipped.md):** Delete `$Z_HARNESS_PLAN_DIR/.review_state.json` before emitting the final response:
```bash
rm -f "$Z_HARNESS_PLAN_DIR/.review_state.json"
```
This ensures a subsequent `/z-review-all` starts a full fresh run rather than fast-forwarding into a stale Phase 4.

Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps, review tasks=<t>, escalations=<k>."

Present a short summary to the user:

- `findings.md` path
- `REVIEW-TASKS.md` path, if generated
- top blockers/escalations
- next command: `/z-implement-all --tasks $BASE/REVIEW-TASKS.md` after deleting rejected candidates, or `/z-amend` for amendment proposals that should be applied first

Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"review_tasks":<t>,"escalations":<k>,"user_action":"artifact_promoted"}'`.

**On a clean review or after promoted tasks complete**, also push-notify the user:
```
Final review accepted. Recommended next:
  /z-maintain-docs   — refresh docs/human/ and docs/llm/ for any concepts touched by this plan
```
The implementation is done and reviewed; the docs are what's left.

## Phase 7 — Memory review (auto)

This phase fires once per run, after Phase 6, before the session ends. It is a soft phase: all failure paths are silent skips — no halt, no retry.

**Clear dedup file at phase start:**
```bash
[[ -n "${BASE:-}" ]] && rm -f "$BASE/.notify-dedup-session"
```

1. **Run the memory-review helper:**

   ```bash
   mapfile -t LINES < <(bash scripts/run-memory-review.sh "$RRUN" "review-all")
   STATUS_LINE="${LINES[0]:-}"
   ```

2. **Skip path — first line is `STATUS: skipped <reason>`:**

   ```bash
   if [[ "$STATUS_LINE" == STATUS:\ skipped* ]]; then
     # Helper (run-memory-review.sh) already emitted the memory_review_terminal event
     # for all skip states. Phase 7 exits silently — no duplicate event.
     # For state: skipped_broken_context → push-notify if Z_HARNESS_NOTIFY_LEVEL != off, deduped:
     SKIP_REASON="${STATUS_LINE#STATUS: skipped }"
     if [[ "$SKIP_REASON" == tags_missing || "$SKIP_REASON" == no_plan_dir || "$SKIP_REASON" == missing_args ]]; then
       DEDUP_FILE="$BASE/.notify-dedup-session"
       DEDUP_KEY="${Z_HARNESS_SLUG:-unknown}:${SKIP_REASON}"
       if [[ "${Z_HARNESS_NOTIFY_LEVEL:-approval_only}" != "off" ]] && ! grep -qxF "$DEDUP_KEY" "$DEDUP_FILE" 2>/dev/null; then
         PushNotification("Memory review skipped on \`${Z_HARNESS_SLUG:-unknown}\`: \`${SKIP_REASON}\`. Fix to re-enable memory candidates.")
         printf '%s\n' "$DEDUP_KEY" >> "$DEDUP_FILE"
       fi
     fi
     # exit phase quietly — no push-notify for not_applicable states
     return 0
   fi
   ```

3. **Ready path — first line is `STATUS: ready`:** parse the artifact paths from subsequent lines:

   ```bash
   CUMULATIVE_DIFF_PATH="${LINES[1]:-}"
   SPEC_PATH="${LINES[2]:-}"
   TAGS_PATH="${LINES[3]:-}"
   RUN_DIR="$(dirname "$CUMULATIVE_DIFF_PATH")"
   SLUG_FOR_DESC="${Z_HARNESS_SLUG:-$(basename "$BASE")}"
   ```

4. **Dispatch the review-agent:**

   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="review-agent",
     description="Memory review for <SLUG_FOR_DESC>",
     prompt="run_dir: <RUN_DIR>
   cumulative_diff_path: <CUMULATIVE_DIFF_PATH>
   spec_path: <SPEC_PATH>
   tags_path: <TAGS_PATH>
   index_path: docs/llm/INDEX.json
   run_id: <RRUN>
   parent_command: review-all"
   )
   ```

5. **Parse agent return — extract single fenced ```json block:**

   ```python
   import re, json
   raw = agent_return_text
   m = re.search(r'```json\s*([\s\S]*?)```', raw)
   if not m:
       # no fenced block → review_agent_failed
       raise ValueError("no_fenced_block")
   try:
       candidates = json.loads(m.group(1))
   except json.JSONDecodeError as e:
       raise ValueError("json_parse_error") from e
   ```

   - **Agent errored / no fenced block (`review_agent_failed`):**

     Condition: `m` is `None` (regex found no fenced block).

     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_agent_failed \
       "$(printf '{"run":"%s","reason":"no_fenced_block"}' "$RRUN")"
     ```
     Exit phase silently — no push-notify, no `memory_review_terminal` (agent failures are orthogonal failure classes per SPEC §`/z-stats` Phase 4b, not terminal states). `return 0`

   - **Fenced block present but `json.loads` raised `JSONDecodeError` (`review_agent_malformed`):**

     Condition: `m` matched but `json.loads(m.group(1))` raised.

     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_agent_malformed \
       "$(printf '{"run":"%s","excerpt":"%s"}' "$RRUN" "$(printf '%s' "$raw" | head -c 200 | tr '"' "'")")"
     ```
     Exit phase silently — no push-notify, no `memory_review_terminal` (agent failures are orthogonal failure classes per SPEC §`/z-stats` Phase 4b, not terminal states). `return 0`

6. **Empty candidates (`[]`):**

   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_agent_call \
     "$(printf '{"run":"%s","parent_command":"review-all","candidates_emitted":0,"accepted":0}' "$RRUN")"
   SLUG_JSON="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]) if sys.argv[1] else "null")' \
     "${Z_HARNESS_SLUG:-}")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" memory_review_terminal \
     "$(printf '{"state":"ran_empty","skip_reason":null,"parent_command":"review-all","candidates":0,"accepted":0,"slug":%s}' \
        "$SLUG_JSON")"
   ```
   Exit phase quietly — no push-notify. `return 0`

7. **Candidates ≥ 1:**

   a. **Persist to JSONL:**
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

   b. **Log `review_agent_call`** (with token counts from Agent return usage block):
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_agent_call \
        "$(printf '{"run":"%s","parent_command":"review-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d,"accepted":"<filled-in-later>"}' \
           "$RRUN" "$INPUT_TOKENS" "$OUTPUT_TOKENS" "$N_CANDIDATES")"
      ```

   c. **Push-notify `memory_candidates_ready`:**
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" memory_candidates_ready \
        "$(printf '{"run":"%s","candidates_emitted":%d}' "$RRUN" "$N_CANDIDATES")"
      ```
      Push-notify: "Memory review produced `<N>` candidate(s) — please review."

   d. **Sequential AskUserQuestion per candidate (max 3 candidates):**

      For each candidate (index `i`, 0-based; stop after 3):
      ```
      <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
        title: "Memory candidate <i+1> of <total> — <candidate.candidate_kind>",
        body: "**Suggested concept:** `<candidate.suggested_concept_slug>`\n\n**Type:** `<candidate.type>`\n\n**Text:** <candidate.text>\n\n**Tags:** <candidate.tags joined by ', '>\n\n**Rationale:** <candidate.rationale>\n\n**Evidence:** <candidate.evidence_citations joined by ', '>",
        options: [
          { id: "accept", label: "Accept — persist this candidate" },
          { id: "edit",   label: "Edit — modify before persisting" },
          { id: "skip",   label: "Skip (provide one-word reason)" },
          { id: "skip_all", label: "Skip all remaining" }
        ]
      )
      ```

      - **Accept:** dispatch the `/z-suggest-memory` skill, piping `$CANDIDATE_JSON` to its stdin:
        ```
        /z-suggest-memory --concept "<candidate.suggested_concept_slug>" --source "incident:<RRUN>" --from-candidate-json -
        ```
        On `STATUS: ok` → increment `ACCEPTED`.
        On `STATUS: skipped` or `STATUS: bad_input` → log:
        ```bash
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_agent_suggest_failed \
          "$(printf '{"run":"%s","candidate_index":%d,"reason":"%s"}' "$RRUN" "$i" "<reason>")"
        ```
        Continue to next candidate.

      - **Edit:** Surface the candidate fields. Collect user edits. Apply edits to the candidate JSON in-memory. Re-present as Accept and dispatch `/z-suggest-memory` with the edited JSON piped via `--from-candidate-json -`.

      - **Skip (one-word reason):** Ask the user for the reason word (follow-up prompt or inline if the UI allows). Then:
        ```bash
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_candidate_skipped \
          "$(printf '{"run":"%s","candidate_index":%d,"reason":"%s"}' "$RRUN" "$i" "<user_reason>")"
        ```
        Increment `SKIPPED`. Continue to next candidate.

      - **Skip-all-remaining:**
        ```bash
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_skip_all \
          "$(printf '{"run":"%s","candidates_remaining":%d}' "$RRUN" "$((N_CANDIDATES - i))")"
        ```
        Break the loop.

8. **Final `memory_review_terminal` event (only for `needs_user` path — candidates ≥ 1):**

   After the AskUserQuestion loop completes (all candidates reviewed, or `skip_all` chosen), emit exactly one terminal event. **This step applies ONLY to the `needs_user` path (candidates ≥ 1, step 7). The `ran_empty` path already emitted its terminal event in step 6 and must NOT execute step 8.**

   ```bash
   SLUG_JSON="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]) if sys.argv[1] else "null")' \
     "${Z_HARNESS_SLUG:-}")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" memory_review_terminal \
     "$(printf '{"state":"needs_user","skip_reason":null,"parent_command":"review-all","candidates":%d,"accepted":%d,"slug":%s}' \
        "$N_CANDIDATES" "$ACCEPTED" "$SLUG_JSON")"
   ```

   This is the single terminal event for the `needs_user` path (candidates ≥ 1). The mid-phase `memory_candidates_ready` push-notify in step 7c is a separate signal and is NOT the terminal event — do not conflate them.

**Event-kind reference for this phase:**

| Event kind | When emitted |
|---|---|
| `memory_review_terminal` | Once per invocation: after user gate (`state: needs_user` or `ran_empty`); skip path terminal events are emitted by helper, not here |
| `review_agent_call` | Agent returned candidates (including empty-array case) |
| `review_agent_failed` | Agent returned without a fenced block |
| `review_agent_malformed` | Agent returned with a fenced block that failed `json.loads` |
| `memory_candidates_ready` | N ≥ 1 candidates; push-notify fired (mid-phase signal, distinct from terminal event) |
| `review_candidate_skipped` | User skipped a single candidate with a reason |
| `review_skip_all` | User chose Skip-all-remaining |
| `review_agent_suggest_failed` | `/z-suggest-memory` dispatch failed for an Accepted candidate |

## Behavioral rules

- **Review-mining backfill:** After every `/z-review-all` run, extract new invariant candidates AND error-point candidates from findings (severity >= major) via Phase 5.5. If `docs/INVARIANTS.json` does not exist, skip invariant extraction (log `invariant_store_missing`). If `docs/ERROR_POINTS.json` does not exist, skip error-point extraction (log `error_point_store_missing`). At least one registry must exist for Phase 5.5 to run.
- **Findings classification:** Each extracted invariant candidate must include `source: "review"` and the plan slug from which it was extracted. Candidates extracted from review findings carry stronger provenance than those inferred from spec alone. Error-point candidates are auto-accepted (empirical data doesn't require human review).
- **One-reason pushback:** If the reviewer pushes back on a candidate invariant (i.e., a finding was flagged as potentially incorrect or the extraction over-fits), document the one-line reason in the candidate's rejection log. This preserves institutional memory about why a candidate was refused.
- **Error-point rate-limiting:** A single error point's `frequency` increments at most once per review run, even if multiple findings match its `pattern_signature`. New error points created per run are capped at `Z_HARNESS_ERROR_POINT_MAX_NEW` (default 10).
- **Deterministic matching first:** Pattern signature matching (sha256 of module_prefix::finding_class::severity) runs before any LLM dispatch. This is zero-token, zero-latency, perfectly reproducible. Only unmatched findings are sent to Haiku for fuzzy matching.

## Hard rules

- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
- **Never** run this on an incomplete plan without explicit user override.
- **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
- **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.
- **Invariant and error-point extraction must never halt the pipeline.** If Phase 5.5 fails for any reason (bad JSON, file read error, subagent crash, validation failure), log the error to `$BASE/archive/$RRUN/invariant-extraction-error.log` and continue to Phase 6. The review pipeline is the priority.
- **Always validate INVARIANTS.json after writing.** After any Phase 5.5 write to INVARIANTS.json, run `scripts/validate-invariants.py --file docs/INVARIANTS.json`. If validation fails, log the failure and roll back the edit (restore from backup), but do NOT block the pipeline — continue to Phase 6.
- **Always validate ERROR_POINTS.json after writing.** After any Phase 5.5 write to ERROR_POINTS.json, run `scripts/validate-error-points.py --file docs/ERROR_POINTS.json`. If validation fails, log the failure and roll back the edit, but do NOT block the pipeline.
- **Both registries must use atomic writes.** Always write to tempfile → fsync → os.replace(). Never write directly to the target path. This applies to both INVARIANTS.json and ERROR_POINTS.json.
- **Phase 5.5 is gated on findings.md content.** If findings.md has no severity ≥ major entries, skip Phase 5.5 entirely — no Haiku dispatch, no AskUserQuestion.

## What this command is NOT for

- Not a substitute for per-task review. Per-task review catches per-task bugs fast; this catches cross-task bugs.
- Not a substitute for human design review on major architecture changes.
- Not for use during implementation — it's a final gate, not a debugging tool. (For mid-implementation debugging, just chat with Claude normally and have it read the relevant files.)
