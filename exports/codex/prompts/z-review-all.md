# /z-review-all

You are running the **z-harness `/z-review-all`** final-gate review. This is a holistic cross-task cross-LLM review, intentionally distinct from the per-task review that `/z-implement-all` already performs. Per-task review catches per-task issues; this catches issues that only show up when looking at all tasks together.

## Phase 0 — Discover plan slug

Same logic as `/z-implement-all` / `/z-implement-next`:

1. Enumerate subdirs of `z-harness/` containing a `TASKS.md`. Also check legacy flat `z-harness/TASKS.md`.
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

## Phase 4 — Spawn final-review consultants (parallel)

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->

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
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Final-review (Gemini) for plan <slug>",
  prompt="MODE: final-review-2pronged\n\n<full prompt with both prongs, plus paths to SPEC/PLAN/TASKS and cumulative.diff>"
)
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Final-review (Codex) for plan <slug>",
  prompt="MODE: final-review-2pronged\n\n<same>"
)
```

Both consultants are already on `model: haiku` — they just shell out to gemini/codex CLIs. The actual reasoning is done by Gemini and Codex themselves.

Transcripts are archived by each consultant under `$BASE/archive/$RRUN/transcripts/` per the consultant's own logging.

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

## Phase 6 — Present + ask what to do

Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps."

Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:

- **Open drift fixup tasks** → append new tasks (e.g. `T100-fixup-drift`) to `$BASE/TASKS.md`, mark them `[ ]`. User can then run `/z-implement-all` again.
- **Spec retro** → patch `$BASE/SPEC.md` to address the Prong B findings (you make the edits in-line; user reviews).
- **Both**
- **Ship as-is** — write a `$BASE/archive/$RRUN/shipped.md` acknowledging findings as acceptable; close out the plan.
- **Reject and re-plan** — escalate; recommend running `/z-plan` for the affected scope.

Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"user_action":"<choice>"}'`.

**On Ship as-is or after fixup tasks complete**, also push-notify the user:
```
Final review accepted. Recommended next:
  /z-maintain-docs   — refresh docs/human/ and docs/llm/ for any concepts touched by this plan
```
The implementation is done and reviewed; the docs are what's left.

## Hard rules

- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
- **Never** run this on an incomplete plan without explicit user override.
- **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
- **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.

## What this command is NOT for

- Not a substitute for per-task review. Per-task review catches per-task bugs fast; this catches cross-task bugs.
- Not a substitute for human design review on major architecture changes.
- Not for use during implementation — it's a final gate, not a debugging tool. (For mid-implementation debugging, just chat with Claude normally and have it read the relevant files.)
