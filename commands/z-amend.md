---
description: Amend an existing z-harness plan (INTENT.md, SPEC/PLAN/TASKS, or FIX.md) so a change is propagated consistently across all artifacts. In intent mode, re-opens the frozen contract and invalidates the current level's TASKS.md for regeneration. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendment is non-obvious.
argument-hint: <what to change about the plan> [--skip-user-gate]
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running the **z-harness `/z-amend`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What amendment should I make to the plan?" via their native channel and
     accept a text reply. Silent omission is forbidden. -->
**If the task above is empty** — use `AskUserQuestion` to ask "What amendment should I make to the plan?" before proceeding. Do not invent.

This command modifies an **already-produced** planning artifact set. It does NOT do exploration / consult-everywhere / full premise check — that's `/z-plan`. It does the surgical work of changing one or more decisions / scope items and making sure every downstream artifact (SPEC.md, PLAN.md, TASKS.md, or FIX.md) reflects the change consistently.

### `--skip-user-gate` flag

When `--skip-user-gate` is present in the arguments, Phase 4 (user gate) is skipped. The amendment proceeds directly from Phase 3 (impact analysis) to Phase 5 (consult, if triggered) then Phase 6 (propagate edits). This flag is intended for callers that have already validated the amendment via cross-LLM review (e.g. `/z-review-all` auto-amend). **Never** pass this flag in standalone invocations — it exists only for programmatic consumers.

## Phase 0 — Discover plan slug

Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. Determine which one to amend:

1. Enumerate candidates: immediate subdirs of `z-harness/` that contain **any** of `SPEC.md`, `PLAN.md`, `TASKS.md`, `INTENT.md`, or `FIX.md`. Also check for legacy flat layout.
2. Choose:
   - **One candidate** → use it. `export Z_HARNESS_SLUG=<slug>` (or leave unset for legacy).
   <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug
        selection question via their native channel. Silent omission is forbidden. -->
   - **Multiple candidates** → `AskUserQuestion` with each slug as an option (annotate each with mode: `intent` if INTENT.md present and no SPEC.md, `full` if SPEC.md exists, `light` if only FIX.md). Set `Z_HARNESS_SLUG` to chosen.
   - **Zero candidates** → tell the user there's no plan to amend; suggest `/z-plan` or `/z-plan-light`. Stop.
3. From here on, **`$BASE`** refers to `$Z_HARNESS_PLAN_DIR` (or `z-harness` if legacy).
4. Detect **mode**:
   - `intent` if `$BASE/INTENT.md` exists and `$BASE/SPEC.md` does NOT exist.
   - `full` if `$BASE/SPEC.md` exists.
   - `light` if only `$BASE/FIX.md` exists.

## Phase 1 — Setup + telemetry

1. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-amend-<slug>`
2. `mkdir -p $BASE/archive/$RUN/transcripts`
3. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["amendment"] = sys.argv[2]; v["mode"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>" "<intent|full|light>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_start "$START_PAYLOAD"
   ```
4. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).

## Phase 2 — Read the current plan

Read every artifact that exists for this slug:

- **intent mode:** `$BASE/INTENT.md`, `$BASE/LEDGER.md` (if present), `$BASE/TASKS.md` (if present)
- **full mode:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
- **light mode:** `$BASE/FIX.md`

For **intent mode**, note the current `frozen_at` value in INTENT.md frontmatter. If it holds a real ISO timestamp (not `pending` or absent), the contract is currently frozen; re-opening it is the core operation of Phase 6-INTENT.

For **full mode**, also snapshot completed task state. Run:
```bash
grep -E '^\- \[x\] T[0-9]+' $BASE/TASKS.md > $BASE/archive/$RUN/completed-tasks.txt || true
```
This is the source of truth for "what must NOT change ID or get deleted under our feet." If the amendment requires changing a task that's already `[x]`, you must surface that to the user in Phase 4 — completed work cannot be silently retracted.

## Phase 3 — Impact analysis

Articulate, in plain prose, what the amendment changes. Write `$BASE/archive/$RUN/amendment.md`:

```markdown
# Amendment: <one-line summary>

**Run:** <RUN>
**Mode:** <intent|full|light>
**Requested change:** <verbatim $ARGUMENTS>

## What this affects

### INTENT.md  (intent mode only)
- **Current frozen_at:** <existing value or "pending">
- **Sections changed:** <bullet per INTENT section that changes: Intent / Not doing / Consider for this / Acceptance checklist; "no change" if none>
- **Criteria added/removed/modified:** <list; "none" if unchanged>
- **TASKS.md impact:** <"invalidated — regenerated on next /z-implement-all" if any section changed; "none" if only non-structural edits>
- **LEDGER.md:** preserved append-only; no changes.

### SPEC.md   (full mode only)
- <bullet per section that changes; "no change" if none>

### PLAN.md   (full mode only)
- <decisions added/changed/removed; phases reordered; non-goals added/dropped>

### TASKS.md  (full mode only)
- **New tasks:** T0NN, T0NN+1, ... (next IDs after current max)
- **Modified tasks:** T0NN (status `[ ]` → still `[ ]`, but acceptance/files/deps changed)
- **Removed tasks:** T0NN (only if status `[ ]`; never remove `[x]`)
- **Touched-but-completed tasks:** T0NN (status `[x]` — flag for user decision)

### FIX.md    (light mode only)
- <which sections change: Problem / Root cause / Approach / Files / Acceptance>

## Risk
- Does this change cross any auto-bail threshold (new external dep, public API change, schema change, cross-module)? If yes → flag for consult in Phase 5.
- For intent mode: if the amendment removes or weakens an acceptance criterion, note it explicitly — this changes the definition of done.
```

**ID-allocation rule:** new tasks always take fresh IDs (max existing + 1, ...). Never reuse a deleted task's ID.

**Completed-task rule:** if a `[x]` task's behavior is contradicted by the amendment, do NOT edit it in place. Instead, add a new `[ ]` task whose description explicitly says "supersedes T0NN: <reason>". The user sees both in the archive trail.

## Phase 4 — User gate

**If `--skip-user-gate` is present:** Skip this phase entirely. Strip the flag from `$ARGUMENTS`. Emit an `amend_user_gate_skipped` event:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_user_gate_skipped \
  '{"reason":"skip_user_gate_flag"}'
```
Proceed directly to Phase 5. The caller (e.g. `/z-review-all` auto-amend) has already validated the amendment via cross-LLM review.

**Otherwise** (normal invocation):

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the amendment
     approval question (Approve / Revise / Abandon) via their native channel and
     await a response. Silent omission is forbidden. -->
Show `amendment.md` to the user via `AskUserQuestion`:

- **Approve as drafted** → proceed to Phase 5
- **Revise** (free-text) → loop back to Phase 3 with their tweak
- **Abandon** → log `amend_run_end` with `status: abandoned`; exit

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the completed-task
     disposition question for each touched-but-completed task via their native channel.
     Silent omission is forbidden. -->
If `Touched-but-completed tasks` is non-empty, ask a **separate explicit** `AskUserQuestion` for each:
- "Add superseding task (recommended)"
- "Re-open T0NN (flip `[x]` → `[ ]`) — work needs to be redone"
- "Leave T0NN alone — amendment doesn't actually contradict it"

Block until answered. Send a `PushNotification` if policy ≠ `off`.

## Phase 5 — Optional cross-LLM consult (only if non-obvious)

If `amendment.md`'s Risk section flagged any of these triggers, run a **bundled** consult:

- New external dependency
- Public API / wire format / schema change
- Cross-module impact in full mode
- Algorithm swap with materially different Big-O / memory
- Persistence change (migration, retention, indexes)

Spawn both in parallel:
```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the Agent() call. The command cannot
     proceed without subagent support. -->
Agent(subagent_type="consultant-primary", description="Amend consult (Gemini) for <slug>",
      prompt="MODE: amend\n\nExisting plan: <inline brief — 2-3 paragraphs from SPEC/PLAN summary>\nAmendment: <amendment.md body>\nKey concern: <the risk trigger>\n\nAsk: is the amendment sound? what's likely to break? what did I miss?")
Agent(subagent_type="consultant-secondary", description="Amend consult (Codex) for <slug>",
      prompt="<same body>")
```

When both return: apply **one reason it might be wrong** to each recommendation. Synthesize. Update `amendment.md` with a `## Consult outcome` section.

If neither consult trigger fires, skip this phase entirely — the user already approved in Phase 4.

## Phase 6 — Propagate edits

Now apply the amendment to the actual artifacts. Use `Edit` (not `Write`) so diffs stay surgical and reviewable.

### Intent mode

0. **Snapshot INTENT.md before any mutation.** Read the current content into a pre-edit variable so it can be restored on abort, abandon, or fatal validation failure:
   ```bash
   INTENT_SNAPSHOT="$(cat "$BASE/INTENT.md")"
   ```
   If at any later point the user chooses "Abandon" (lint disposition or Phase 7 fatal inconsistency), restore the file before exiting:
   ```bash
   # Restore on abort
   printf '%s' "$INTENT_SNAPSHOT" > "$BASE/INTENT.md"
   ```

1. **Re-open the frozen contract.** Set `frozen_at` back to `pending` using the frontmatter-aware `reopen-intent` subcommand (parses only the YAML frontmatter block; never rewrites body text):
   ```bash
   REOPEN_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/intent-schema.py" \
     reopen-intent "$BASE/INTENT.md" 2>&1)"
   REOPEN_EXIT=$?
   if [ "$REOPEN_EXIT" != "0" ]; then
     echo "ERROR: reopen-intent failed: $REOPEN_OUT"
     printf '%s' "$INTENT_SNAPSHOT" > "$BASE/INTENT.md"
     exit 1
   fi
   ```
   `reopen-intent` is idempotent: if `frozen_at` is already `pending`, it prints `ALREADY_PENDING: pending` and exits 0 with no file change. `frozen_at: pending` signals that the contract will be re-frozen on the next `/z-implement-all`.

2. **Apply surgical edits to INTENT sections.** Using `Edit` (not `Write`), modify only the sections listed in `amendment.md`. Preserve all unrelated content byte-for-byte. The editable sections are:
   - `## Intent` — narrative of what the effort accomplishes
   - `## Not doing` — explicit scope boundaries
   - `## Consider for this` — situational constraints
   - `## Acceptance checklist` — observable `[ ]` criteria

3. **Re-run the acceptance-criterion lint.** After editing INTENT.md:
   ```bash
   LINT_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/intent-schema.py" \
     lint-criteria "$BASE/INTENT.md" 2>&1)"
   LINT_EXIT=$?
   LINT_SUPPRESSED=false
   ```
   If `$LINT_EXIT != 0` (lint failures found), surface them to the user:
   <!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the lint failures
        via their native channel and await a fix/proceed/abandon response.
        Silent omission is forbidden. -->
   `AskUserQuestion`: "Acceptance-criterion lint failures found after amendment:\n\n$LINT_OUT\n\nOptions:\n- Fix criteria now (describe the fix)\n- Proceed anyway (accept the lint warning)\n- Abandon this amendment"
   - **Fix criteria now** → apply the fix via `Edit`, then re-run lint until it passes. Loop maximum 3 times; if still failing after 3 loops, surface again and let the user choose Proceed or Abandon.
   - **Proceed anyway** → set `LINT_SUPPRESSED=true`; log a `lint_suppressed` event and continue:
     ```bash
     LINT_SUPPRESSED=true
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" lint_suppressed \
       "$(printf '{"failures_count":%d,"run":"%s"}' "$(echo "$LINT_OUT" | grep -c '^LINE')" "$RUN")"
     ```
   - **Abandon** → restore the pre-edit snapshot, then log `amend_run_end` with `status: abandoned`; exit:
     ```bash
     printf '%s' "$INTENT_SNAPSHOT" > "$BASE/INTENT.md"
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_end \
       '{"status":"abandoned","reason":"lint_failures"}'
     ```

4. **Preserve LEDGER.md.** Do NOT touch LEDGER.md. It is append-only (SPEC.md Invariant 3). Never rewrite, truncate, or edit it.

5. **Invalidate the in-progress level's TASKS.md.** If `$BASE/TASKS.md` exists (from a prior level-generation), it must be regenerated from the amended INTENT on the next run. Mark it stale by setting the `stale_reason` frontmatter field. Replace any existing `stale_reason` key to avoid duplicate YAML keys on repeated `/z-amend` invocations:
   ```bash
   python3 - "$BASE/TASKS.md" <<'PYEOF'
   import re, sys
   path = sys.argv[1]
   content = open(path).read()

   # Detect a real frontmatter block: must start with "---\n" and have a closing "---"
   fm_match = re.match(r"^(---\r?\n)(.*?)(\r?\n---\r?\n?)", content, re.DOTALL)
   if fm_match:
       open_delim = fm_match.group(1)
       fm_body    = fm_match.group(2)
       close_delim = fm_match.group(3)
       after_fm   = content[fm_match.end():]
       # Replace existing stale_reason if present; otherwise insert after opening ---
       if re.search(r"^stale_reason\s*:", fm_body, re.MULTILINE):
           fm_body = re.sub(
               r"^stale_reason\s*:.*$",
               "stale_reason: amended-intent",
               fm_body,
               count=1,
               flags=re.MULTILINE,
           )
       else:
           fm_body = "stale_reason: amended-intent\n" + fm_body
       new_content = open_delim + fm_body + close_delim + after_fm
   else:
       # No real frontmatter: prepend a minimal block
       new_content = "---\nstale_reason: amended-intent\n---\n" + content
   open(path, "w").write(new_content)
   PYEOF
   ```
   The task-tree-generator (T010) checks for `stale_reason: amended-intent` and regenerates rather than resuming. If TASKS.md does not exist (no level has been generated yet), skip this step.

6. **Add an amendment record to INTENT.md.** Append to the body (after the last section) a fenced block:
   ```markdown
   ## Amendments
   - <date> (<RUN>): <one-line summary of what changed and why>
   ```
   If an `## Amendments` section already exists, append a new bullet to it (never rewrite existing bullets).

### Full mode
1. **SPEC.md** — update only the affected sections. Preserve unrelated content byte-for-byte.
2. **PLAN.md** — update Decisions / Non-goals / Phases sections as listed in `amendment.md`. If a decision is reversed, add a `## Amendments` section at the bottom recording: date, what changed, why (one line each). This gives the archive trail.
3. **TASKS.md**:
   - Append new tasks with fresh IDs in the appropriate phase block.
   - Edit modified `[ ]` tasks in place.
   - Strike-through removed `[ ]` tasks: change `- [ ] T0NN` → `- [~] T0NN ~~<title>~~ (removed in <RUN>)`. Keep them visible — `/z-implement-next` skips `[~]`.
   - For superseded `[x]` tasks: leave them `[x]` and add the new superseding `[ ]` task whose title begins `Supersedes T0NN: ...`.
   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.

### Light mode
1. **FIX.md** — update the affected sections (Problem / Root cause / Approach / Files / Acceptance / Cross-LLM consensus). Add an `## Amendments` section at the bottom: date, what changed, why.

### Both modes
After every file edit, run:
```bash
diff -u <(git show HEAD:$BASE/<file> 2>/dev/null || echo) $BASE/<file> > $BASE/archive/$RUN/<file>.diff
```
(If not under git, snapshot the pre-edit content into `$BASE/archive/$RUN/before/<file>` before editing — Read first, copy via Write.)

## Phase 7 — Validate consistency

Run a self-check. Read each amended file fresh and verify:

- **Intent mode:**
  - `frozen_at` in INTENT.md is now `pending` (re-open succeeded).
  - INTENT.md passes `validate-intent` (schema check):
    ```bash
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/intent-schema.py" \
      validate-intent "$BASE/INTENT.md"
    ```
    If `validate-intent` exits non-zero (fatal schema error), restore the snapshot and surface the error:
    ```bash
    if [ "$VALIDATE_EXIT" != "0" ]; then
      printf '%s' "$INTENT_SNAPSHOT" > "$BASE/INTENT.md"
      # then surface to user via AskUserQuestion and log amend_run_end status:schema_error
    fi
    ```
  - **Lint-suppression audit:** If `$LINT_SUPPRESSED=true`, confirm this is recorded in `events.jsonl` (the `lint_suppressed` event logged in Phase 6 step 3) and append a durable note to the `## Amendments` section of INTENT.md indicating criteria were left with lint warnings. Phase 8's summary to the user must also call out that lint was suppressed.
  - LEDGER.md (if present) is byte-for-byte identical to its pre-amendment state (preserved).
  - If TASKS.md exists, it contains `stale_reason: amended-intent` in frontmatter, and the frontmatter has no duplicate `stale_reason` keys (parse with `_parse_frontmatter`; if duplicates detected, surface as inconsistency).
- **Full mode:**
  - Every task referenced in PLAN.md exists in TASKS.md (and vice versa for non-implicit refs).
  - Every file path in TASKS.md "files touched" appears in SPEC.md.
  - No `[x]` task was changed without an explicit user-approved supersede.
  - No duplicate task IDs.
- **Light mode:** every file in FIX.md "Files to change" exists or has a clear creation directive.

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the consistency
     error choice (Fix automatically / revise / abort) via their native channel.
     Silent omission is forbidden. -->
If any check fails, do **not** silently fix — surface to user via `AskUserQuestion` ("inconsistency found: <X>. Fix automatically / revise / abort").

## Phase 8 — Finalize

1. Log run end:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" amend_run_end \
     "$(printf '{"status":"applied","mode":"%s","tasks_added":%d,"tasks_modified":%d,"tasks_removed":%d,"tasks_superseded":%d,"consulted":%s,"intent_reopened":%s,"lint_suppressed":%s}' \
        "$MODE" "$N_ADDED" "$N_MOD" "$N_REM" "$N_SUP" "$CONSULTED" \
        "$([ "$MODE" = "intent" ] && echo "true" || echo "false")" \
        "$([ "$LINT_SUPPRESSED" = "true" ] && echo "true" || echo "false")")"
   ```
2. Push-notify (if policy ≠ `off`): "Amendment applied to `<slug>`. <N> tasks added, <M> modified, <K> removed, <S> superseded."
3. Brief summary to user (3-5 sentences): what changed, what's next.
4. Recommend next step:
   - **intent mode** → INTENT.md is now re-opened (`frozen_at: pending`). Run `/z-implement-all` to re-freeze and regenerate the next level's task batch from the amended INTENT.
   - **full mode with new/modified `[ ]` tasks** → `/z-implement-next` or `/z-implement-all`
   - **light mode** → `/z-plan-light` won't re-run; if the amendment is large enough to warrant re-implementation, suggest the user explicitly trigger that.

## Phase 9 — Elevation Proposer

After Phase 8 completes, run the preference elevation check:

```bash
PROPOSE_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/propose-prefs.py" --check z-amend 2>/dev/null)"
```

If `$PROPOSE_OUT` is non-empty, parse it as JSON and surface a one-shot preference proposal:

```python
import json
proposal = json.loads(PROPOSE_OUT)
qid = proposal["question_id"]
val = proposal["proposed_value"]
n   = len(proposal["evidence"])
scope_rec = proposal["scope_recommendation"]
```

Emit `proposal_surfaced`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_surfaced \
  "$(python3 -c '
import json, sys
print(json.dumps({"question_id": sys.argv[1], "proposed_value": sys.argv[2], "n_evidence": int(sys.argv[3]), "scope_recommendation": sys.argv[4]}))
' "$qid" "$val" "$n" "$scope_rec")"
```

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the preference
     elevation proposal question via their native channel and accept a reply.
     Silent omission is forbidden. -->
Present a single `AskUserQuestion`:

> "You've done `<cmd_a> → z-amend` **N times** — add `<val>` as your preference for `<qid>`?"
>
> Options:
> - **config** — write to project config (or global if `scope_recommendation=global`)
> - **memory:very_strong** — store as a very-strong routing-preference memory entry
> - **memory:strong** — store as a strong routing-preference memory entry
> - **no** — suppress this prompt for 30 days

Branch on the user's choice:

**`config` branch:**
```bash
SCOPE_FLAG="--scope=project"
[ "$scope_rec" = "global" ] && SCOPE_FLAG="--scope=global"
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" set workflow.audit_to_amend amend $SCOPE_FLAG
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_accepted \
  "$(printf '{"question_id":"%s","via":"config","scope":"%s"}' "$qid" "$scope_rec")"
```

**`memory:very_strong` or `memory:strong` branch:**

Dispatch `/z-suggest-memory` with `--kind routing-preference`:
```
/z-suggest-memory --kind routing-preference \
  --question-id <qid> \
  --value <val> \
  --strength <very_strong|strong> \
  --scope <scope_recommendation>
```

Then emit:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_accepted \
  "$(printf '{"question_id":"%s","via":"memory","strength":"%s","scope":"%s"}' "$qid" "$strength" "$scope_rec")"
```

**`no` branch:**

Write suppression entry with 30-day expiry:
```python
import json, os, time
from pathlib import Path
suppress_path = Path(".z-harness") / ".propose-suppress"
suppress_path.parent.mkdir(parents=True, exist_ok=True)
data = {}
if suppress_path.exists():
    try:
        data = json.loads(suppress_path.read_text())
    except (json.JSONDecodeError, OSError):
        data = {}
expiry = time.time() + 30 * 86400
data[qid] = str(expiry)
suppress_path.write_text(json.dumps(data))
```

Then emit:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" proposal_rejected \
  "$(printf '{"question_id":"%s","suppressed_until_epoch":"%s"}' "$qid" "$expiry")"
```

If `$PROPOSE_OUT` is empty, skip this phase entirely — no question is asked.

---

## Hard rules

- **Never delete or silently mutate a `[x]` task.** Supersede instead.
- **Never reuse a task ID.** New tasks always get fresh IDs.
- **Never rewrite an artifact wholesale with `Write`** when surgical `Edit` will do. Preserve byte-for-byte content outside the amendment scope.
- **Never skip Phase 4 (user gate) when invoked standalone.** The `--skip-user-gate` flag may only be used by callers (e.g. `/z-review-all` auto-amend) that have already validated the amendment via cross-LLM review.
- **Cross-LLM consult only when triggered** — amendments are surgical; full consult is overkill for "rename this field".
- **If the amendment grows past ~30% of the plan** (e.g. >5 new tasks, or the core premise of SPEC.md changes), STOP and recommend `/z-plan` from scratch instead — at that point you're not amending, you're replanning.
- **In intent mode: never touch LEDGER.md.** It is append-only (SPEC.md Invariant 3). Re-freeze happens on the next `/z-implement-all`, not here.
- **In intent mode: re-open always sets `frozen_at: pending`.** Do not delete the field or set it to an empty string; `pending` is the signal T009's freeze idempotency check reads.
- **No emojis** anywhere in artifacts.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 5 consultant-primary and consultant-secondary Agent() calls |
| `ask_user` | yes | Empty arguments gate; Phase 0 multiple-candidates slug selection; Phase 4 amendment approval; Phase 4 completed-task disposition; Phase 6 intent-mode lint failure disposition; Phase 7 consistency error choice; Phase 9 preference elevation proposal |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
