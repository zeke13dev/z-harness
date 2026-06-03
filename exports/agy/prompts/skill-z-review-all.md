---
description: "Final-gate cross-LLM review of a completed z-harness plan. Runs Gemini + Codex on the cumulative diff against SPEC.md to surface (a) implementation drift across tasks and (b) spec gaps that only surface in aggregate. Use after /z-implement-all com..."
role: skill
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

## Hard rules

- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
- **Never** run this on an incomplete plan without explicit user override.
- **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
- **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.

## What this command is NOT for

- Not a substitute for per-task review. Per-task review catches per-task bugs fast; this catches cross-task bugs.
- Not a substitute for human design review on major architecture changes.
- Not for use during implementation — it's a final gate, not a debugging tool. (For mid-implementation debugging, just chat with Claude normally and have it read the relevant files.)
