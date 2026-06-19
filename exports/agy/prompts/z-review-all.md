---
description: "Final-gate cross-LLM review of a completed z-harness plan. Runs Gemini + Codex on the cumulative diff against the plan contract (SPEC.md in legacy mode; frozen INTENT.md + LEDGER.md in INTENT mode) to surface (a) implementation drift across tasks ..."
role: workflow
---

You are running the **z-harness `/z-review-all`** final-gate review. This is a holistic cross-task cross-LLM review, intentionally distinct from the per-task review that `/z-implement-all` already performs. Per-task review catches per-task issues; this catches issues that only show up when looking at all tasks together.

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
   - **If it fails to parse (invalid JSON):** treat as stale — delete the file, emit a `review_state_corrupt` event with `reason: "parse_error"`, and proceed to Phase 0 for a full re-run:
     ```bash
     # RRUN is not yet established in pre-Phase-0; use a transient identifier
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "pre-resume" review_state_corrupt \
       "$(jq -n --arg slug "$EARLY_SLUG" --arg reason 'parse_error' '{"slug":$slug,"reason":$reason}')"
     rm "$EARLY_PLAN_DIR/.review_state.json"
     ```
   - **If parsed successfully AND `halted: true` AND `halt_reason: "no_ask_blocked"`:** this is a valid halted-state file from a prior Phase 3.7 no-ask block. Do NOT delete it. Emit `review_resume_from_halt` event and jump to Phase 3.7 retry (skip Phases 0–3.5, but re-run Phase 3.7 gate from scratch):
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "pre-resume" review_resume_from_halt \
       "$(jq -n --arg slug "$EARLY_SLUG" --arg halt_reason 'no_ask_blocked' '{"slug":$slug,"halt_reason":$halt_reason}')"
     # Restore enough environment for Phase 3.7: slug and plan dir are already known.
     # Phase 3.7 will re-run check-no-ask and either halt again or prompt the user.
     # NOTE: We do NOT restore RRUN/cumulative paths here because Phase 3.7 re-runs
     # the gate afresh — if no-ask is now cleared, the user will be prompted normally
     # and a full Phase 0–3.5 run is needed to rebuild artifacts.
     # Delete halt state file so Phase 3.7 writes a fresh one if needed.
     rm "$EARLY_PLAN_DIR/.review_state.json"
     # → jump to Phase 0 (full re-run; halt state cleared so Phase 3.7 gate re-evaluates)
     ```
   - **If parsed successfully AND `phase_3_7_acknowledged` is not `true` AND not a recognized halt state:** treat as stale — delete the file, emit a `review_state_corrupt` event with `reason: "missing_field"`, and proceed to Phase 0:
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

## Phase 0 — Concurrent follow-up consumer check

Before doing any plan discovery, check whether a follow-up consumer is actively running in this project. Running `/z-review-all` while a follow-up consumer is modifying files risks race conditions on shared state (plan dir, sink index).

```bash
SINK_LOCK="$HOME/.z-harness/.followup-vs-implement.lock"
PROJECT_SINK="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" followups_dir)/index.view.json"
if [ -f "$PROJECT_SINK" ]; then
  RUNNING_COUNT="$(python3 -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    entries_obj = data.get('entries', {})
    entries = list(entries_obj.values())
    running = [e for e in entries if e.get('status') == 'running']
    print(len(running))
except (json.JSONDecodeError, OSError, KeyError, AttributeError):
    print(0)
" "$PROJECT_SINK" 2>/dev/null || echo 0)"
  if [ "${RUNNING_COUNT:-0}" -gt 0 ]; then
    echo "halt: follow-up consumer is active ($RUNNING_COUNT running entry/entries in project sink)" >&2
    echo "Run /z-followup-status to see what is running. Wait for it to complete or dismiss before reviewing." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" review_halted_followup_running \
      "$(printf '{"running_count":%d,"sink_path":"%s"}' "$RUNNING_COUNT" "$PROJECT_SINK")" 2>/dev/null || true
    exit 1
  fi
fi
```

## Phase 0 — Discover plan slug

Same logic as `/z-implement-all` / `/z-implement-next`:

1. Enumerate subdirs of `z-harness/` containing a `TASKS.md`. Also check legacy flat `z-harness/TASKS.md`.
<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug-selection question via their native channel. Silent omission is forbidden. -->
2. Single candidate → use it. Multiple → `AskUserQuestion` to pick (or honor `--slug <slug>` argument). Zero → tell user nothing to review; stop.
3. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` (or leave unset for legacy flat).
4. `BASE = $Z_HARNESS_PLAN_DIR` (or `z-harness` for legacy).

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

**Run Brief init (immediately after `review_all_start`).** Registry: `/z-review-all`, profile `full`, outcome from `review_all_end` event payload at finalize.
```bash
export RUN="$RRUN"
CURRENT_ARCHIVE_DIR="$BASE/archive/$RRUN"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
REVIEW_INTENT="Final review of plan ${Z_HARNESS_SLUG}"
bash "$RB_SH" init --run "$RRUN" --command /z-review-all --slug "$Z_HARNESS_SLUG" --profile full --intent "$REVIEW_INTENT"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT=""
export RUN_BRIEF_ARTIFACT_FALLBACKS="$BASE/archive/$RRUN/findings.md:$BASE/REVIEW-TASKS.md"
```

**Kernel path resolution (once per run, immediately after review_all_start):**
```bash
KERNEL_PATH="$(bash scripts/resolve-kernel.sh 2>/dev/null || true)"
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

Log provider resolution (once per run, guarded against re-emission):
```bash
if [ ! -f "$BASE/archive/$RRUN/.providers-logged" ]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
  mkdir -p "$BASE/archive/$RRUN"
  touch "$BASE/archive/$RRUN/.providers-logged"
fi
```

**Mode detection (INTENT vs legacy):**

Detect which review contract to use. Mirror the detection convention from `/z-implement-all` (T008):

```bash
# INTENT mode: INTENT.md present and SPEC.md absent
INTENT_MODE=false
INTENT_FILE=""
LEDGER_FILE=""
INVARIANTS_PATH=""
STYLE_PATH=""

if [ -f "$BASE/INTENT.md" ] && [ ! -f "$BASE/SPEC.md" ]; then
  INTENT_MODE=true

  # Prefer the frozen snapshot from the most recent archive run; fall back to live INTENT.md
  LATEST_FROZEN="$(ls -t "$BASE/archive/"*/INTENT.frozen.md 2>/dev/null | head -1 || true)"
  if [ -n "$LATEST_FROZEN" ]; then
    INTENT_FILE="$LATEST_FROZEN"
  else
    INTENT_FILE="$BASE/INTENT.md"
  fi

  LEDGER_FILE="$BASE/LEDGER.md"

  # Durable tier
  INVARIANTS_PATH="docs/INVARIANTS.json"  # repo-root-relative; durable tier lives in the repo, not the plan dir $BASE
  if [ -f "STYLE.md" ]; then
    STYLE_PATH="STYLE.md"
  elif [ -f "docs/STYLE.md" ]; then
    STYLE_PATH="docs/STYLE.md"
  else
    STYLE_PATH=""
  fi

  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_mode_detected \
    "$(printf '{"mode":"intent","intent_file":"%s","ledger_file":"%s"}' "$INTENT_FILE" "$LEDGER_FILE")"
else
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_mode_detected \
    '{"mode":"legacy"}'
fi
```

In INTENT mode the realized-plan contract is: **frozen INTENT** (`$INTENT_FILE`) + **LEDGER** (`$LEDGER_FILE`) + **durable tier** (`$INVARIANTS_PATH`; `$STYLE_PATH` if present). SPEC.md and PLAN.md are not used. In legacy mode all existing behavior is preserved; the variables above remain unset and the command proceeds identically to today.

## Phase 1 — Sanity check task status

Read `$BASE/TASKS.md`. Count `[ ]`, `[~]`, `[x]`, and skip-flagged tasks.

- If any `[~]` (in-progress) exist → abort with "Stop — task X is still in progress."
<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the incomplete-plan warning (review anyway / cancel) via their native channel. Silent omission is forbidden. -->
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
   <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the base-ref question via their native channel. Silent omission is forbidden. -->
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

```bash
TEMPLATE="$(jq -r .cmd_template "$BASE/test-runner.json")"
FRAMEWORK="$(jq -r .framework "$BASE/test-runner.json")"
AFFECTED_DIRS="$(git diff --name-only "$BASE_REF"..HEAD | xargs -I{} dirname {} | sort -u)"
# Framework-specific: cargo → "cargo test -p <crate>"; pytest → "pytest <dir>"; etc.
# The template's {TARGET_FILE} placeholder is repurposed as the affected directory glob.
SUITE_LOG="$BASE/archive/$RRUN/suite.log"
: > "$SUITE_LOG"
SUITE_FAILED=0
for DIR in $AFFECTED_DIRS; do
  CMD="$(echo "$TEMPLATE" | sed "s|{TARGET_FILE}|$DIR|g; s|{TEST_NAME}||g")"
  echo "===== $CMD =====" >> "$SUITE_LOG"
  eval "$CMD" >> "$SUITE_LOG" 2>&1 || SUITE_FAILED=$((SUITE_FAILED+1))
done
```

**Any failure here is a blocker.** Surface the failing log slice to the user before proceeding to Phase 4. Treat the same way as a Prong-A finding of severity `blocker` — `/z-review-all` cannot accept a plan whose own tests are broken.

Skip this phase if either TESTS.md or test-runner.json is absent (no harm — older plans without /z-test predate this step).

## Phase 3.6 — Pre-review cycle (opt-in)

**Opt-in gate:** Only runs if `runtime.pre_review` is `true` in config. Check at phase start:

```bash
if [ "$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get runtime.pre_review 2>/dev/null)" != "true" ]; then
  echo "Pre-review cycle skipped (runtime.pre_review != true)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" pre_review_skipped \
    '{"reason":"opt_in_disabled"}'
  # Jump to Phase 3.7
  return 0
fi
```

When enabled, spawn **3 pre-reviewers in parallel** to do a fast first-pass scan. Each pre-reviewer runs on the cheapest available model (haiku). Their findings are collected and fed as additional context into the Phase 4 consultant prompts.

Each pre-reviewer gets the same inputs. The exact paths depend on the detected mode:

**Legacy mode:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`, cumulative diff + stat.

**INTENT mode:** `$INTENT_FILE` (frozen INTENT), `$LEDGER_FILE` (realized plan), `$BASE/TASKS.md`, cumulative diff + stat, durable tier (`$INVARIANTS_PATH`; `$STYLE_PATH` if present). SPEC.md and PLAN.md are not passed.

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

**In legacy mode**, use these prompts:

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

**In INTENT mode**, substitute SPEC/PLAN with INTENT/LEDGER and add durable tier. Adjust focus lines to cite the acceptance checklist and durable invariants rather than SPEC.md sections:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="pre-reviewer",
  description="Pre-review 1 — correctness & intent drift (Flash) for <slug>",
  prompt="MODE: final-review-prong-a
slug: <slug>
run_id: <RRUN>
review_contract: intent
Kernel path: <KERNEL_PATH>

INTENT.frozen.md: <$INTENT_FILE>
LEDGER.md: <$LEDGER_FILE>
TASKS.md: $BASE/TASKS.md
INVARIANTS: <$INVARIANTS_PATH>
[style_path: <$STYLE_PATH>  ← omit this line when STYLE_PATH is empty]
cumulative_diff_path: $BASE/archive/$RRUN/cumulative.diff
cumulative_stat_path: $BASE/archive/$RRUN/cumulative.stat

Focus: PRONG A — Implementation drift. Is the cumulative diff faithful to the acceptance checklist in INTENT.frozen.md and the decisions/deviations recorded in LEDGER.md? Look for acceptance criteria that are not met, cross-task drift, stale references, violations of INVARIANTS. Cite findings as 'fails acceptance criterion #N' where N is the 1-based index in the frozen INTENT ## Acceptance checklist. Be fast and cheap — surface only clear blockers and majors."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="pre-reviewer",
  description="Pre-review 2 — intent gaps & acceptance coverage (Flash) for <slug>",
  prompt="MODE: final-review-prong-b
slug: <slug>
run_id: <RRUN>
review_contract: intent
Kernel path: <KERNEL_PATH>

INTENT.frozen.md: <$INTENT_FILE>
LEDGER.md: <$LEDGER_FILE>
TASKS.md: $BASE/TASKS.md
INVARIANTS: <$INVARIANTS_PATH>
[style_path: <$STYLE_PATH>  ← omit this line when STYLE_PATH is empty]
cumulative_diff_path: $BASE/archive/$RRUN/cumulative.diff
cumulative_stat_path: $BASE/archive/$RRUN/cumulative.stat

Focus: PRONG B — Acceptance-checklist gaps. Now that the implementation is done, are there acceptance criteria in INTENT.frozen.md that the cumulative diff fails to satisfy? Deviations recorded in LEDGER.md that changed scope without updating the checklist? Edge cases the checklist missed? Be fast and cheap — surface only clear blockers and majors."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="pre-reviewer",
  description="Pre-review 3 — code quality & structural issues (Flash) for <slug>",
  prompt="MODE: final-review-quality
slug: <slug>
run_id: <RRUN>
review_contract: intent
Kernel path: <KERNEL_PATH>

INTENT.frozen.md: <$INTENT_FILE>
LEDGER.md: <$LEDGER_FILE>
TASKS.md: $BASE/TASKS.md
INVARIANTS: <$INVARIANTS_PATH>
[style_path: <$STYLE_PATH>  ← omit this line when STYLE_PATH is empty]
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
# check-no-ask is the fail-closed overnight gate. It returns halt|proceed and
# correctly handles Z_HARNESS_ASK_ALL=1 vs Z_HARNESS_NO_ASK=halt conflicts (exit 5).
NOASK_JSON="$(python3 scripts/config.py check-no-ask --question-id workflow.review_all_proceed)"
NOASK_EXIT=$?
NOASK_RESULT="$(echo "$NOASK_JSON" | jq -r .result)"

if [[ $NOASK_EXIT -eq 5 ]]; then
  # Config conflict (ASK_ALL=1 + NO_ASK=halt). check-no-ask already printed error JSON.
  # Surface to user and abort.
  echo "config_conflict: Z_HARNESS_ASK_ALL=1 and Z_HARNESS_NO_ASK=halt are mutually exclusive" >&2
  exit 5
fi
```

- **If `$NOASK_RESULT == "halt"`:** Emit `review_halt` event, write a partial `.review_state.json`, and exit cleanly — do NOT proceed to `resolve-question` or `AskUserQuestion`:
  ```bash
  if [[ "$NOASK_RESULT" == "halt" ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_halt \
      "$(printf '{"reason":"no_ask_blocked","question_id":"workflow.review_all_proceed","rule_id":"no_ask_halt"}')"
    echo "halt: no_ask_blocked on workflow.review_all_proceed" >&2
    # Write partial state file so /z-review-all resume check recognizes this as a
    # halted-state file (not stale/corrupt) on next invocation.
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
  On this halt path (after `run-brief.sh init`), run **Run Brief — halt finalize** below (substitute `<reason>` = `no_ask_blocked on workflow.review_all_proceed`) before `exit 0`.

- **If `$NOASK_RESULT == "proceed"`:** Overnight gate cleared — continue to the resolver for preference-based skip/prefill/ask:
  ```bash
  # check-no-ask returned proceed: run the full resolver to honor user preferences.
  RESOLVED="$(python3 scripts/config.py resolve-question workflow.review_all_proceed)"
  RESOLVE_EXIT=$?

  if [[ $RESOLVE_EXIT -ne 0 ]]; then
    # Exit codes: 2=bad invocation, 3=unknown question_id, 4=I/O error.
    # In all error cases, fall through to ask the user normally — never silently skip.
    echo "resolve-question failed (exit $RESOLVE_EXIT); falling back to ask" >&2
    RESULT="ask"; DEFAULT=""; SOURCE="error"
  else
    RESULT="$(echo "$RESOLVED" | jq -r .result)"
    DEFAULT="$(echo "$RESOLVED" | jq -r .default)"
    SOURCE="$(echo "$RESOLVED" | jq -r .source)"
  fi
  ```

  Branch on `$RESULT` from the resolver:

  - **`skip`:** Skip the `AskUserQuestion` and proceed as if the user picked `$DEFAULT`. Emit `askuser_skipped` event:
    ```bash
    if [[ "$RESULT" == "skip" ]]; then
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" askuser_skipped \
        "$(printf '{"question_id":"workflow.review_all_proceed","source":"%s"}' "$SOURCE")"
      # Fall through to the Proceed path below (write state file and continue to Phase 4).
    fi
    ```

  - **`prefill`:** Present the `AskUserQuestion` normally, pre-select `$DEFAULT` as the recommended option (append label suffix: ` (Recommended — your preference)`).
  - **`ask`:** Present the `AskUserQuestion` normally.

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the compaction-breakpoint decision (pause for /clear / proceed now) via their native channel. Silent omission is forbidden. -->
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

## Phase 3.7.5 — Route non-halting findings to follow-up sink

After the user picks "Proceed now" in Phase 3.7 (or the resolver auto-proceeds), before spawning consultants, check if the reviewer return from any prior per-task reviews produced `**FOLLOWUPS:**` blocks that haven't been routed yet. Additionally, at the end of Phase 5 (after `findings.md` is built), route non-halting minor/major findings from the cumulative review into the sink.

**After Phase 5 findings are aggregated**, for each finding in `findings.md` that is NOT in the `Blockers` sections (i.e. severity is `major` or `minor`), invoke `scripts/parse-followups-block.py` on the findings text to extract any `**FOLLOWUPS:**` block written by the consultants, then route via `scripts/sink-add.sh`:

```bash
# Route non-halting findings from cumulative review to sink
FINDINGS_FILE="$BASE/archive/$RRUN/findings.md"
if [ -f "$FINDINGS_FILE" ] && [ -f "scripts/parse-followups-block.py" ] && [ -f "scripts/sink-add.sh" ]; then
  FOLLOWUPS_JSON="$(python3 scripts/parse-followups-block.py --reviewer-output "$FINDINGS_FILE" 2>/dev/null || echo '[]')"
  FOLLOWUP_COUNT="$(printf '%s' "$FOLLOWUPS_JSON" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)"
  if [ "${FOLLOWUP_COUNT:-0}" -gt 0 ]; then
    printf '%s' "$FOLLOWUPS_JSON" | python3 -c "
import json, subprocess, sys

entries = json.load(sys.stdin)
source_artifact = sys.argv[1]
script = sys.argv[2]

for i, e in enumerate(entries):
    cited = ','.join(e.get('cited_paths', []))
    args = [
        'bash', script,
        '--sink=project',
        f'--priority={e[\"priority\"]}',
        f'--name={e[\"name\"]}',
        f'--recommended-command={e[\"recommended_command\"]}',
        f'--source-artifact={source_artifact}',
        f'--cited-paths={cited}',
    ]
    if e.get('auto_close_eligible'):
        args.append('--auto-close-eligible')
    if e.get('recommended_command_safe_to_retry'):
        args.append('--safe-to-retry')
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode not in (0, 3):  # 3 = dedup-skip (ok)
        print(f'warn: sink-add.sh exit {result.returncode} for entry {i}: {result.stderr[:200]}', file=sys.stderr)
" "$FINDINGS_FILE" "scripts/sink-add.sh" 2>/dev/null || true
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" followups_routed_to_sink \
      "$(printf '{"count":%d,"source":"review_all_findings"}' "$FOLLOWUP_COUNT")" 2>/dev/null || true
  fi
fi
```

Per-entry errors are logged + skipped. This step never blocks the review pipeline. If `scripts/sink-add.sh` is not yet present (deps not implemented), this step is silently skipped.

## Phase 4 — Spawn final-review consultants (parallel)

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

### Legacy mode inputs

Each consultant gets:

- `$BASE/SPEC.md` (the spec)
- `$BASE/PLAN.md` (the plan with decisions)
- `$BASE/TASKS.md` (what was supposed to happen, with completion notes)
- `$BASE/archive/$RRUN/cumulative.diff` (what actually happened)
- `$BASE/archive/$RRUN/cumulative.stat` (file-touch overview)
- **`docs/llm/INDEX.json` (if exists)** + the concept JSONs for any `source_file` that appears in `cumulative.stat`. The LLM-tier docs state invariants that span tasks; a "drift" finding from the consultant carries more weight if it cites a specific invariant from a docs/llm/ entry.

### INTENT mode inputs

In INTENT mode, SPEC.md and PLAN.md are replaced by the frozen INTENT + realized LEDGER + durable tier. Each consultant gets:

- `$INTENT_FILE` (frozen INTENT.md snapshot — the contract)
- `$LEDGER_FILE` (LEDGER.md — the realized-plan audit trail of decisions + deviations)
- `$BASE/TASKS.md` (the task batches that were executed)
- `$BASE/archive/$RRUN/cumulative.diff` (what actually happened)
- `$BASE/archive/$RRUN/cumulative.stat` (file-touch overview)
- `$INVARIANTS_PATH` (durable tier — docs/INVARIANTS.json)
- `$STYLE_PATH` if non-empty (durable style guide)
- **`docs/llm/INDEX.json` (if exists)** + concept JSONs for files in `cumulative.stat`.

### Prong framing

**Legacy mode:**

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

**INTENT mode:**

**Prong A — Acceptance-checklist faithfulness.** Does the cumulative diff satisfy every `[ ]` acceptance criterion in the frozen INTENT? Cite findings as "fails acceptance criterion #N". Also check:
- Decisions and deviations in LEDGER.md that changed scope without a corresponding criterion update.
- Cross-task drift visible in the diff versus the LEDGER record.
- Violations of durable invariants in `$INVARIANTS_PATH`.
- Missing tests / assertions the criterion wording requires.

**Prong B — INTENT completeness.** Now that the implementation is done, are there gaps in the frozen INTENT itself?
- Acceptance criteria that are ambiguous, unobservable, or that the implementation can satisfy trivially.
- Deviations recorded in LEDGER.md that the original checklist didn't anticipate.
- Edge cases the frozen INTENT missed that the code either handles silently or breaks on.
- Scope the "## Not doing" section should have excluded but didn't.

### Calling pattern

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

**Legacy mode:**

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

**INTENT mode:**

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Final-review (Gemini) for plan <slug> [INTENT mode]",
  prompt="MODE: final-review-2pronged
review_contract: intent
slug: <slug>
run_id: <RRUN>
[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]

INTENT.frozen.md: <$INTENT_FILE>
LEDGER.md: <$LEDGER_FILE>
TASKS.md: $BASE/TASKS.md
INVARIANTS: <$INVARIANTS_PATH>
[style_path: <$STYLE_PATH>  ← omit this line when STYLE_PATH is empty]
cumulative_diff_path: $BASE/archive/$RRUN/cumulative.diff
cumulative_stat_path: $BASE/archive/$RRUN/cumulative.stat

<full two-pronged prompt using INTENT-mode framing above>"
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Final-review (Codex) for plan <slug> [INTENT mode]",
  prompt="<same as consultant-primary above>"
)
```

Both consultants are already on `model: haiku` — they just shell out to gemini/codex CLIs. The actual reasoning is done by Gemini and Codex themselves.

Transcripts are archived by each consultant under `$BASE/archive/$RRUN/transcripts/` per the consultant's own logging.

## Finding promotion contract

Review-family commands produce two artifact classes:

- **Evidence artifacts** preserve every reviewed finding and the pushback that was applied before trusting it.
- **Promotion artifacts** contain only actionable candidate work in a `/z-implement-all`-compatible task shape. Users prune or approve these artifacts once, then run `/z-implement-all --tasks <path>` to apply survivors.

Every promoted finding must carry:

- **Source:** the originating run, consultant(s), prong, and finding text or ID.
- **Class:** `implementation_drift`, `spec_gap`, `completed_task_contradiction`, `premise_failure`, or `observation`.
- **Severity:** `blocker`, `major`, or `minor`.
- **Evidence:** path/line citations or diff/spec references.
- **Pushback:** one concrete reason the finding might be wrong.
- **Files:** expected edit targets, or `none` if the item is not directly implementable.
- **Disposition:** `candidate_task`, `amendment_proposal`, `superseding_task`, `escalation`, or `report_only`.
- **Acceptance:** verifiable completion criteria for executable tasks.

Promotion rules:

- `implementation_drift` → candidate fixup task.
- `spec_gap` → amendment proposal task that routes through `/z-amend`; never a direct `SPEC.md` edit.
- `completed_task_contradiction` → fresh superseding task; never mutate a completed `[x]` task in place.
- `premise_failure` → escalation section, not implementer work.
- `observation` → remain in the evidence artifact only.

## Phase 5 — Aggregate findings

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

### Phase 5.5 — Tier 2 review patterns accumulation

After `findings.md` is built, extract aggregate review patterns and append to tier2-context.json:

```bash
python3 scripts/append-tier2-context.py --phase review --field review_patterns \
  --json '<extracted patterns JSON>'
```

Pattern format: `{"pattern": "...", "source": "consultant-primary|consultant-secondary|consensus", "finding": "...", "recommendation": "..."}`.

Extract: patterns that appeared across both consultant returns, consensus/disagreement themes, architectural observations that span multiple tasks.

Non-fatal: failure logs event, continues.

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

### Phase 6.6 — Render amendment brief

After Phase 6.5 completes, build the renderer input from BOTH finding streams and write a unified brief into the run-brief artifact pipeline. This replaces the passive "## Escalations" bullet as the active presentation surface for premise_failure findings.

**Source mapping:**
- **`corrections`** — every `spec_gap` amendment proposal that Phase 6.5 successfully auto-amended. For each, supply `title` (the task title from REVIEW-TASKS.md), `why` (the source finding reference), and `target` (the amended artifact path, e.g. SPEC.md).
- **`approach_concerns`** — every `premise_failure` escalation from the `## Escalations` section of REVIEW-TASKS.md. For each, supply `concern` (the finding text) and, when identifiable, `affected` (the affected scope or file). The `suggestion` field is optional. When `affected` is absent the brief falls back to "rework this, or proceed?".

**Procedure:**

1. Build the brief JSON. Capture it in `BRIEF_JSON`:

```bash
BRIEF_JSON="$(python3 - "$BASE/REVIEW-TASKS.md" "$BASE/archive/$RRUN/auto-amend-log.md" <<'PY'
import json, re, sys
from pathlib import Path

review_tasks_path = sys.argv[1]
amend_log_path = sys.argv[2]

corrections = []
approach_concerns = []

# --- corrections: spec_gap tasks successfully auto-amended ---
# Read the auto-amend log to get the title, source, and artifact for each applied amendment.
if Path(amend_log_path).exists():
    log_text = Path(amend_log_path).read_text(encoding="utf-8")
    # Match each "### T-REV-NNN — [severity] <title>" block in the Amendments applied section.
    block_re = re.compile(
        r'###\s+(T-REV-\S+)\s+—\s+\[.*?\]\s+(.+?)\n'
        r'.*?- \*\*Source:\*\*\s+(.+?)\n'
        r'.*?- \*\*Result:\*\*\s+applied\b'
        r'.*?- \*\*Artifacts changed:\*\*\s+(.+?)\n',
        re.DOTALL,
    )
    matches = list(block_re.finditer(log_text))
    # Warn only when the log exists AND records that amendments were applied but the regex
    # matched zero blocks — this indicates a format drift / parse failure, not a clean run.
    # A clean run either has no log file or has a log with zero "Result: applied" entries.
    applied_count_re = re.search(r'Amendments applied:\s*(\d+)', log_text)
    expected_applied = int(applied_count_re.group(1)) if applied_count_re else None
    if not matches and expected_applied:
        print(
            f"z-review-all Phase 6.6 WARNING: auto-amend-log.md records {expected_applied} applied"
            " amendment(s) but the block regex matched 0 — format may have drifted."
            " corrections list will be empty; verify auto-amend-log.md format.",
            file=sys.stderr,
        )
    for m in matches:
        corrections.append({
            "title": m.group(2).strip(),
            "why": m.group(3).strip(),
            "target": m.group(4).strip(),
        })

# --- approach_concerns: premise_failure escalations ---
if Path(review_tasks_path).exists():
    rt_text = Path(review_tasks_path).read_text(encoding="utf-8")
    # Locate the ## Escalations section and extract Premise failure bullets.
    esc_match = re.search(r'^## Escalations\s*\n(.*?)(?=^##|\Z)', rt_text, re.MULTILINE | re.DOTALL)
    if esc_match:
        esc_block = esc_match.group(1)
        for line in esc_block.splitlines():
            line = line.strip()
            if line.startswith('- **Premise failure:**'):
                # Strip the "- **Premise failure:** " prefix.
                text = re.sub(r'^-\s+\*\*Premise failure:\*\*\s*', '', line)
                # Try to extract an "affected" scope from "Recommended next: /z-plan <scope>"
                affected = None
                plan_match = re.search(r'/z-plan\s+(\S+)', text)
                if plan_match:
                    affected = plan_match.group(1)
                # Strip the recommended-next trailer for the concern text.
                concern = re.sub(r'\s*Recommended next:.*$', '', text).strip()
                entry = {"concern": concern}
                if affected:
                    entry["affected"] = affected
                approach_concerns.append(entry)

print(json.dumps({"corrections": corrections, "approach_concerns": approach_concerns}))
PY
)"
```

2. **Skip gate**: parse `BRIEF_JSON` and skip Phase 6.6 (no brief file, no pipeline registration) if BOTH `corrections` and `approach_concerns` are empty:

```bash
_BRIEF_SKIP="$(python3 -c '
import json, sys
d = json.loads(sys.argv[1])
print("1" if not d.get("corrections") and not d.get("approach_concerns") else "0")
' "$BRIEF_JSON")"
if [[ "$_BRIEF_SKIP" == "1" ]]; then
  : # nothing to brief — skip to Phase 6.7
else
```

3. Render the brief and write it to the archive (inside the `else` block from step 2):

```bash
  AMENDMENT_BRIEF_FILE="$BASE/archive/$RRUN/amendment-brief.md"
  # BRIEF_JSON was captured in step 1 — pipe it directly to the shared renderer.
  printf '%s' "$BRIEF_JSON" \
    | python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/amendment-brief.py" \
    > "$AMENDMENT_BRIEF_FILE"
  # Phase 6.6 only WRITES amendment-brief.md to the archive. Registration with run-brief.json
  # is handled by Finalize's APPROACH_FILE resolution, which prefers amendment-brief.md over
  # findings.md when the file exists (see the Finalize set-section calls in the section below).
fi
```

**Note:** The `## Escalations` heading in REVIEW-TASKS.md remains as the structured archive record of premise_failure entries for artifact traceability. The run-brief pipeline (amendment-brief.md → approach bullets in run-brief.json → Finalize render) is the *active* presentation layer.

### Phase 6.7 — Tier 2 context finalization + significance gate

After Phase 6.5 cleanup, finalize tier2-context.json and evaluate the three-signal OR gate:

```bash
# Mark finalized
python3 -c "
import json, os, datetime
dir = os.environ.get('Z_HARNESS_PLAN_DIR', '')
if not dir: exit(0)
path = os.path.join(dir, 'tier2-context.json')
if not os.path.exists(path): exit(0)
d = json.load(open(path))
d['finalized'] = True
d['generated_at'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
gaps = []
for ov in d.get('human_overrides', []):
    if not ov.get('reason'):
        gaps.append({'field': 'human_overrides[].reason', 'status': 'missing', 'note': 'Override missing reason'})
d['gaps'] = gaps
json.dump(d, open(path, 'w'), indent=2)
"

# Three-signal OR gate
SIGNIFICANT=$(python3 -c "
import json, os
dir = os.environ.get('Z_HARNESS_PLAN_DIR', '')
path = os.path.join(dir, 'tier2-context.json')
if not os.path.exists(path): print('false'); exit(0)
d = json.load(open(path))
consult = len(d.get('consultant_findings', [])) > 0
breaking = len(d.get('breaking_changes', [])) > 0
devis = len(d.get('deviations', [])) > 0
print('true' if (consult or breaking or devis) else 'false')
")
```

**If significant** (any signal fires): push-notify "Pipeline complete. Tier 2 context captured. Run /z-doc-rationale." Add `/z-doc-rationale` to recommendations.

**If not significant:** "Pipeline complete. No significant design decisions. Tier 2 skipped."

**Archive:** Copy `tier2-context.json` to `$BASE/archive/$RRUN/tier2-context.json`.

## Finalize

1. **Log run end** (must precede brief outcome parse — registry `primary_artifact` is this event kind, not a file):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_all_end \
  "$(printf '{"slug":"%s","drift_findings":%d,"spec_gap_findings":%d,"review_tasks":%d,"escalations":%d,"user_action":"%s"}' \
     "$Z_HARNESS_SLUG" "<a>" "<b>" "<t>" "<k>" "<artifact_promoted|shipped_clean>")"
```

2. **Run Brief finalize (registry Finalize).** Parse the last `review_all_end` from `$CURRENT_ARCHIVE_DIR/events.jsonl`, set `outcome`/`next`, then include the shared fragment. Chat and push text are rendered from `run-brief.json` only — do not author independent completion prose.

```bash
export RUN="$RRUN"
CURRENT_ARCHIVE_DIR="$BASE/archive/$RRUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT=""
export RUN_BRIEF_ARTIFACT_FALLBACKS="$BASE/archive/$RRUN/findings.md:$BASE/REVIEW-TASKS.md"
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"

RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

read -r _RB_DRIFT _RB_SPEC_GAPS _RB_REVIEW_TASKS _RB_ESCALATIONS _RB_USER_ACTION <<EOF
$(python3 - "$EVENTS" <<'PY'
import json, sys
last = None
with open(sys.argv[1], encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        if ev.get("kind") == "review_all_end":
            last = ev
if not last:
    raise SystemExit("review_all_end not found in events.jsonl")
print(
    last.get("drift_findings", 0),
    last.get("spec_gap_findings", 0),
    last.get("review_tasks", 0),
    last.get("escalations", 0),
    last.get("user_action", "unknown"),
)
PY
)
EOF

_RB_OUTCOME="${_RB_DRIFT} drift, ${_RB_SPEC_GAPS} spec gaps — ${_RB_USER_ACTION}"
bash "$RB_SH" set-section --run "$RRUN" --section outcome --value "$_RB_OUTCOME"

if [[ "${_RB_USER_ACTION}" == "shipped_clean" || "${_RB_REVIEW_TASKS:-0}" -eq 0 ]]; then
  _RB_NEXT_LABEL="Refresh affected docs via /z-maintain-docs"
  _RB_NEXT_CMD="/z-maintain-docs"
else
  _RB_NEXT_LABEL="Apply review tasks via /z-implement-all --tasks REVIEW-TASKS.md"
  _RB_NEXT_CMD="/z-implement-all"
fi
bash "$RB_SH" set-section --run "$RRUN" --section next --json /dev/stdin <<JSON
{"label": "${_RB_NEXT_LABEL}", "command": "${_RB_NEXT_CMD}"}
JSON

APPROACH_FILE=""
if [[ -f "$BASE/archive/$RRUN/amendment-brief.md" ]]; then
  # Phase 6.6 wrote amendment-brief.md — prefer it so Finalize's approach bullets reflect the brief.
  APPROACH_FILE="$BASE/archive/$RRUN/amendment-brief.md"
elif [[ -f "$BASE/archive/$RRUN/findings.md" ]]; then
  APPROACH_FILE="$BASE/archive/$RRUN/findings.md"
elif [[ -f "$BASE/REVIEW-TASKS.md" ]]; then
  APPROACH_FILE="$BASE/REVIEW-TASKS.md"
fi
if [[ -n "$APPROACH_FILE" ]]; then
  _RB_APPROACH_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_APPROACH_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RRUN" --section approach --file "$APPROACH_FILE" || true
  else
    _RB_SEED="$CURRENT_ARCHIVE_DIR/run-brief-approach-seed.md"
    printf '%s\n' \
      "- Cross-LLM final review (Gemini + Codex) against cumulative diff" \
      "- Prong A: implementation drift; Prong B: spec gaps" \
      "- Findings promoted to REVIEW-TASKS.md when actionable" \
      > "$_RB_SEED"
    bash "$RB_SH" set-section --run "$RRUN" --section approach --file "$_RB_SEED" || true
  fi
fi
```

<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).

3. **Suggest `/z-improve` when this review had friction.** After finalize, run the nudge helper — it prints a one-line `/z-improve` suggestion only if friction signals fired (escalations, degraded consult, …) and stays silent otherwise:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/improve-nudge.sh" "$RRUN" "$Z_HARNESS_SLUG"
```
If it emits a line, include it verbatim in the chat render follow-up to the user (after the Run Brief block).

Artifact paths for the user's reference (not duplicated in push digest — push uses `render-run-brief.py --format push` from the fragment):

- `$BASE/archive/$RRUN/findings.md`
- `$BASE/REVIEW-TASKS.md`, if generated

## Run Brief — halt finalize

Before exit on any halt after `run-brief.sh init` (e.g. `review_halt` / `no_ask_blocked`). Substitute `<reason>` in the outcome line. Fragment auto-downgrades to **lite** when no artifact/fallback file exists.

```bash
export RUN="$RRUN"
CURRENT_ARCHIVE_DIR="$BASE/archive/$RRUN"
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT=""
export RUN_BRIEF_ARTIFACT_FALLBACKS="$BASE/archive/$RRUN/findings.md:$BASE/REVIEW-TASKS.md"
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RRUN" --section outcome --value "Halted: <reason>"
bash "$RB_SH" set-section --run "$RRUN" --section next --json /dev/stdin <<'JSON'
{"label": "Clear halt condition and re-run /z-review-all", "command": "/z-review-all"}
JSON
```

<!-- RUN-BRIEF-FINALIZE: shared finalize block — included via `<!-- include: commands/_fragments/run-brief-finalize.md -->` in registry commands; `/z-export` inlines this body (T007). -->

## Run Brief finalize (shared fragment)

Emit the terminal **Run Brief** before `deregister` / `*_run_end`. Chat and push text are **renders only** — never author completion prose independently; always render from `run-brief.json`.

**Prerequisite:** `run-brief.sh init` ran earlier in this command (after the registry `init_after` anchor). `$CURRENT_ARCHIVE_DIR/run-brief.json` must exist before this block runs.

### Placeholders (set by the host command before including this fragment)

| Placeholder | Meaning |
|-------------|---------|
| `$RUN` | Run id (same value passed to `log-event.sh` and `run-brief.sh --run`) |
| `$CURRENT_ARCHIVE_DIR` | Absolute path to `archive/$RUN/` for this command |
| `$RUN_BRIEF_ARTIFACT` | Primary artifact for approach/outcome derivation (absolute or plan-relative path). May be empty on early halt. |
| `$RUN_BRIEF_PROFILE` | `full` or `lite` — must match the profile passed to `init` (see `docs/llm/run-brief-registry.json`). `/z-do` uses `lite`; all other v1 registry commands use `full`. |
| `$RUN_BRIEF_ARTIFACT_FALLBACKS` | Optional colon-separated fallback paths (same `$RUN` expansion rules as `run-brief.sh`). Example: `PLAN.md:SPEC.md`. Exported before finalize; consumed by `run-brief.sh finalize` via `RUN_BRIEF_ARTIFACT_FALLBACKS` env. |

Host commands also export artifact env for finalize resolution:

```bash
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"
```

---

### Finalize sequence (mandatory order)

Run these steps **in order** at the command's registry `finalize` anchor (before `deregister` and before replacing any legacy "Brief summary" prose).

#### 1. Aggregate decisions → `run-brief.json`

For **`$RUN_BRIEF_PROFILE=full`** only: if `decisions` is empty or absent, aggregate from `$CURRENT_ARCHIVE_DIR/events.jsonl` and append via `run-brief.sh append-decision` (last wins per `question_id`). Skip when `decisions` already has rows (orchestrator may have appended mid-run).

```bash
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
BRIEF="$CURRENT_ARCHIVE_DIR/run-brief.json"
EVENTS="$CURRENT_ARCHIVE_DIR/events.jsonl"

PROFILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("profile",""))' "$BRIEF")"
DEC_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("decisions") or []))' "$BRIEF")"

if [[ "$PROFILE" == "full" && "$DEC_COUNT" -eq 0 && -f "$EVENTS" ]]; then
  while IFS= read -r row; do
    [[ -z "$row" ]] && continue
    QID="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["question_id"])' "$row")"
    CHOSEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["chosen"])' "$row")"
    WHY="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("why",""))' "$row")"
    SRC="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("source","event"))' "$row")"
    AD_ARGS=(--run "$RUN" --question-id "$QID" --chosen "$CHOSEN" --source "$SRC")
    [[ -n "$WHY" ]] && AD_ARGS+=(--why "$WHY")
    bash "$RB_SH" append-decision "${AD_ARGS[@]}"
  done < <(python3 - "$RB_PY" "$EVENTS" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("render_run_brief", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for entry in mod.aggregate_decisions(sys.argv[2]):
    print(json.dumps(entry, ensure_ascii=False))
PY
)
fi
```

Event kinds aggregated: `user_choice`, `user_override`, `plan_route_decision`, `next_step_choice` (see `render-run-brief.py`).

#### 2. Derive from artifact / fallbacks

**Author the approach (required on full-profile success).** You hold the full run context, so before calling `finalize` you MUST set a crisp high-level **How** describing the *solution* — what you actually did, not a table of contents of the plan artifact. This renders as the Briefing "How" line (the renderer joins bullets with ` → `). Substitute your own summary into one of:

```bash
# One crisp sentence (most runs):
bash "$RB_SH" set-section --run "$RUN" --section approach --value "<one-line summary of what you did>"

# 2-4 distinct steps — write a bullet file, pass --file (each "- " line becomes a
# bullet; lines containing file paths or "file.ext:" tokens are dropped):
#   printf '%s\n' '- <step one>' '- <step two>' '- <step three>' > /tmp/approach.md
#   bash "$RB_SH" set-section --run "$RUN" --section approach --file /tmp/approach.md
```

Skip authoring only on halt/abort paths (where there is no meaningful approach) — the lite downgrade handles those. The `extract_approach_bullets` scrape below is the **empty-only fallback** for when authoring was skipped: it runs only when `approach` is still unset (the `APPROACH_COUNT -eq 0` guard), so an authored approach always wins. The scrape regex-greps bullet/numbered lines out of the artifact and tends to produce a plan table-of-contents, which is exactly what authoring avoids.

Resolve the first existing file in `$RUN_BRIEF_ARTIFACT` → `$RUN_BRIEF_ARTIFACT_FALLBACKS` (finalize re-resolves the same chain internally). When a file exists and profile is `full`, seed `approach` from it only if still empty:

```bash
APPROACH_FILE=""
if [[ -n "$RUN_BRIEF_ARTIFACT" && -f "$RUN_BRIEF_ARTIFACT" ]]; then
  APPROACH_FILE="$RUN_BRIEF_ARTIFACT"
elif [[ -n "$RUN_BRIEF_ARTIFACT_FALLBACKS" ]]; then
  IFS=':' read -ra _RB_FB <<< "$RUN_BRIEF_ARTIFACT_FALLBACKS"
  for _cand in "${_RB_FB[@]}"; do
    [[ -z "$_cand" ]] && continue
    _expanded="${_cand//\$RUN/$RUN}"
    if [[ -f "$_expanded" ]]; then APPROACH_FILE="$_expanded"; break; fi
  done
fi

APPROACH_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("approach") or []))' "$BRIEF")"

if [[ "$RUN_BRIEF_PROFILE" == "full" && -n "$APPROACH_FILE" && "$APPROACH_COUNT" -eq 0 ]]; then
  _RB_EXTRACT_N="$(python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rrb", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(len(mod.extract_approach_bullets(sys.argv[2])))
' "$RB_PY" "$APPROACH_FILE")"
  if [[ "$_RB_EXTRACT_N" -gt 0 ]]; then
    bash "$RB_SH" set-section --run "$RUN" --section approach --file "$APPROACH_FILE" || true
  fi
fi
```

Set **`outcome`** / **`next`** when the host command already knows them (recommended on halt paths before finalize):

```bash
# Example — host supplies halt outcome before including this fragment:
# bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
# bash "$RB_SH" set-section --run "$RUN" --section next --json /path/to/next.json
```

If `outcome` is still `Pending finalize`, `run-brief.sh finalize` fills it from `run-status.sh classify`.

#### 3. Finalize → validate JSON + emit `run_brief_end`

```bash
bash "$RB_SH" finalize --run "$RUN"
```

`finalize` classifies terminal status (via `run-status.sh` when unset), resolves artifact/fallback env, auto-downgrades to **lite** when no artifact exists on a full-profile brief (see halt-safe below), validates against `docs/llm/run-brief-contract.json`, and emits `run_brief_end`.

#### 3.5. Cost summary render → stdout (non-fatal, before chat)

```bash
COST_SUMMARY_TEXT=""
COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
  COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
fi
```

#### 4. Chat render → user (replaces hand-authored "Brief summary")

Print rendered chat text to the user — **do not** write independent summary prose:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat ${COST_SUMMARY_TEXT:+--cost-summary-text "$COST_SUMMARY_TEXT"}
```

#### 5. Push render (when notify policy allows)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
  PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  PushNotification("$PUSH_BODY")
fi
```

Push format: `{intent[:80]} · {outcome[:60]} · Next: {next.label}` (from JSON).

#### 5.5. Discord render (when notify policy + webhook URL allow)

```bash
if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
  DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
  DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
fi
```

Discord uses enriched embed format — includes cost summary when available (not identical to PushNotification content). Non-fatal on failure.

#### 6. Hard gate — `--require` before deregister

Run **after** chat/push renders, **before** `active-plan-registry.py deregister` or any terminal `FINALIZE_STATUS` handoff:

```bash
python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
RB_REQUIRE_RC=$?
if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
  echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  FINALIZE_STATUS=aborted
  # Do not deregister as complete — fix brief or abort run
fi
```

On `--require` failure: set `FINALIZE_STATUS=aborted` and do not deregister with `complete`.

---

### Halt-safe: missing artifact → lite brief

Early halt / abort paths often have **no** primary artifact (`FIX.md`, `REPORT.md`, `approach.md`, …). The brief is still **required** before deregister, but may be **lite** (Intent + Outcome + Next only — `approach` and `decisions` keys omitted).

| Condition | Behavior |
|-----------|----------|
| `$RUN_BRIEF_PROFILE=full` and no artifact/fallback file exists at finalize | `run-brief.sh finalize` auto-downgrades to `profile: lite`, drops `approach`/`decisions` **only on halt/aborted paths** — never when status is `complete` or `shipped` |
| `${FINALIZE_STATUS:-}` is `aborted` or classify → `halted` | Ensure `intent` (from init) + `outcome` (set-section or finalize default `"Halted before completion"`) + `next`; lite profile is valid |
| `render-run-brief.py --require` on lite brief | Passes when intent, outcome, next validate — **does not** require approach/decisions |

**Host command responsibilities on halt:**

1. Still include this fragment before deregister (unless the command is on the registry `skip_brief_on` list, e.g. `/z-implement-all` `compaction_pause` only).
2. Set a concrete `outcome` when possible: `bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"`.
3. Do not treat missing artifact as skip-brief — finalize produces lite JSON instead.

---

### Invariants

1. Chat and push text are always rendered from `run-brief.json` — never independently authored at finalize.
2. `--require` runs on every terminal exit that includes this fragment (complete, halted, aborted) before deregister.
3. Empty `decisions: []` is valid for full profile when no decision events occurred.
4. `/z-stats` is not auto-invoked here.
5. Optional debug mirror: `Z_HARNESS_RUN_BRIEF_DEBUG=1` writes `run-brief.md` beside JSON (see `run-brief.sh finalize`).

---

## Phase 7 — Memory review (auto)

1. Call `bash scripts/run-memory-review.sh "$RRUN" "review-all"`. Capture stdout.
2. If the first line is `STATUS: skipped <reason>` — emit `phase_end` with `phase: 7, name: "memory_review", skipped: true, skip_reason: "<reason>"` and exit phase quietly (no push-notify):
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" phase_end \
     "$(jq -n --argjson phase 7 --arg name 'memory_review' --arg skip_reason '<reason>' \
        '{"phase":$phase,"name":$name,"skipped":true,"skip_reason":$skip_reason}')"
   ```
3. If the first line is `STATUS: ready`, parse the three paths printed on subsequent lines:
   - Line 2: `<RUN_DIR>/cumulative.diff` (cumulative diff path)
   - Line 3: `<BASE>/SPEC.md` (spec path; in INTENT mode use `$INTENT_FILE` instead)
   - Line 4: `docs/llm/TAGS.txt` (tags path)
4. Dispatch:
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

   **Legacy mode:**
   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="review-agent",
     description="Memory review for <slug>",
     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: $BASE/SPEC.md\ntags_path: docs/llm/TAGS.txt\nindex_path: docs/llm/INDEX.json\nrun_id: <RRUN>\nparent_command: review-all"
   )
   ```

   **INTENT mode** (substitute `$INTENT_FILE` as the contract path):
   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="review-agent",
     description="Memory review for <slug> [INTENT mode]",
     prompt="run_dir: <RUN_DIR>\ncumulative_diff_path: <cumulative.diff path>\nspec_path: <$INTENT_FILE>\ntags_path: docs/llm/TAGS.txt\nindex_path: docs/llm/INDEX.json\nrun_id: <RRUN>\nparent_command: review-all\nreview_contract: intent\nledger_path: <$LEDGER_FILE>"
   )
   ```
4a. **Optionally dispatch the axiom-extractor (if `AXIOM_READY` was emitted):**

    If `run-memory-review.sh` output contains a line starting with `AXIOM_READY`, parse the artifact path from that line and dispatch the axiom-extractor **alongside** the review-agent (parallel, fresh context):

    ```bash
    AXIOM_READY_LINE="$(printf '%s' "$MEMORY_REVIEW_OUT" | grep '^AXIOM_READY ' || true)"
    ```

    ```
    <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
      subagent_type="axiom-extractor",
      description="Axiom extraction for <slug>",
      prompt="mode: post-run <RRUN>
    repo_root: <REPO_ROOT>"
    )
    ```

    **Proposes only — no auto-approve:** the axiom-extractor returns ≤5 candidate axioms as a fenced JSON array; nothing is written to the axiom store and no axiom is approved automatically. The candidates surface opportunities for later `/z-axiom-scan` / `/z-axiom-approve` review. Do not block on the axiom-extractor's return or error if it is unavailable.

5. Parse the agent's return: extract the single fenced ```json block. On parse failure → emit `review_agent_malformed` event, soft-skip with a push-notify hint, and exit phase:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_agent_malformed \
     "$(jq -n --arg reason 'no_fenced_json_block' '{"reason":$reason}')"
   # Push-notify: "Memory review output was malformed — no valid fenced json block found. Check events.jsonl for review_agent_malformed."
   ```
6. If the candidates array is empty (`[]`) → emit `phase_end` with `candidates_emitted: 0`, exit phase quietly (no push-notify):
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" phase_end \
     "$(jq -n --argjson phase 7 --arg name 'memory_review' --argjson candidates 0 \
        '{"phase":$phase,"name":$name,"candidates_emitted":$candidates}')"
   ```
7. If candidates ≥ 1:
   - Write the raw candidates array to `$RUN_DIR/memory-candidates.jsonl` (one JSON object per line).
   - Emit `review_agent_call` event:
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" review_agent_call \
       "$(jq -n --arg model 'haiku' --argjson in_tok '<input_tokens>' --argjson out_tok '<output_tokens>' --argjson n '<N>' \
          '{"subagent_model":$model,"subagent_input_tokens":$in_tok,"subagent_output_tokens":$out_tok,"candidates_emitted":$n}')"
     ```
   - **Push-notify** (`memory_candidates_ready`): "`<N>` memory candidate(s) ready for review."
   <!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface per-candidate memory review questions (accept / edit / skip / skip-all) via their native channel. Silent omission is forbidden. -->
   - **Sequential AskUserQuestion per candidate** (iterate the candidates array, one prompt per candidate; stop early if user picks Skip-all-remaining):
     - Show: `candidate_kind`, `type`, `text`, `tags`, `suggested_concept_slug`, `rationale`.
     - Options:
       - **Accept** — dispatch `/z-suggest-memory --concept <suggested_concept_slug> --from-candidate-json <tmp_path> --source "incident:<RRUN>"`. On `STATUS: ok`, increment `accepted` counter. On `STATUS: skipped` or `STATUS: bad_input`, log `review_agent_suggest_failed` with reason and continue.
       - **Edit** — surface candidate fields for the user to modify inline, then dispatch as Accept with the edited values.
       - **Skip (one-word reason)** — capture the reason, log `review_candidate_skipped {reason}`, continue to next candidate.
       - **Skip-all-remaining** — log `review_skip_all`, break the loop.
8. Final accounting: emit `phase_end`:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" phase_end \
     "$(jq -n --argjson phase 7 --arg name 'memory_review' \
           --argjson wall_ms '<wall_ms>' \
           --argjson accepted '<accepted>' \
           --argjson edited '<edited>' \
           --argjson skipped '<skipped>' \
           --argjson emitted '<candidates_emitted>' \
        '{"phase":$phase,"name":$name,"wall_ms":$wall_ms,"accepted":$accepted,"edited":$edited,"skipped":$skipped,"candidates_emitted":$emitted}')"
   ```

**Event-kind reference for this phase:**

| Event kind | When emitted |
|---|---|
| `review_agent_call` | Agent returned candidates (including empty-array case) |
| `review_agent_failed` | Agent returned without a fenced block |
| `review_agent_malformed` | Agent returned with a fenced block that failed `json.loads` |
| `memory_candidates_ready` | N ≥ 1 candidates; push-notify fired |
| `review_candidate_skipped` | User skipped a single candidate with a reason |
| `review_skip_all` | User chose Skip-all-remaining |
| `review_agent_suggest_failed` | `/z-suggest-memory` dispatch failed for an Accepted candidate |

## Decision emission (standing instruction)

After **any** `AskUserQuestion` resolves, emit a normalized decision event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-decision.sh" \
  "$RRUN" "<question_id>" "<chosen_label>" \
  --options '["<opt1>","<opt2>",...]' \
  [--tentative "<recommended_option>"]
```

- `<question_id>` — stable kebab-case identifier for this decision point (e.g. `workflow.implement_all_proceed`, `workflow.slug_confirm`).
- `<chosen_label>` — the option label the user selected, verbatim.
- `--options` — full list of offered option labels as a JSON array.
- `--tentative` — the orchestrator's recommended option label; omit when the orchestrator had no recommendation.

Emission is gated by `axioms.auto_extract_post_run` (default `true`); when `false`, the script exits silently — no guard is needed here. Do **not** modify existing structured gate events (`cost_gate_decision`, `critique_failure_decision`, `map_collision_decision`, `shared_concerns_ack_override`); those are normalized separately by the extractor. This emission **records signal only** — it never approves, overrides, or influences any decision (proposes-only invariant).

## Hard rules

- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
- **Never** run this on an incomplete plan without explicit user override.
- **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
- **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.

## What this command is NOT for

- Not a substitute for per-task review. Per-task review catches per-task bugs fast; this catches cross-task bugs.
- Not a substitute for human design review on major architecture changes.
- Not for use during implementation — it's a final gate, not a debugging tool. (For mid-implementation debugging, just chat with Claude normally and have it read the relevant files.)

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 4 consultant-primary + consultant-secondary (parallel); Phase 7 review-agent (memory review) |
| `ask_user` | yes | Phase 0 slug selection; Phase 1 incomplete-plan warning; Phase 2 base-ref fallback question; Phase 3.7 compaction-breakpoint decision (resolver `prefill`/`ask` only); Phase 7 per-candidate memory review |
| `check-no-ask` | yes | Phase 3.7 fail-closed overnight gate — `halt` → emit `review_halt`, write partial state, exit; `proceed` → fall through to `resolve-question` |
| `resolve-question` | yes | Phase 3.7 `workflow.review_all_proceed` (only reached when `check-no-ask` returns `proceed`) — may `skip` (emit `askuser_skipped`, fall through to proceed path) or `prefill`/`ask` (show AskUserQuestion) |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
