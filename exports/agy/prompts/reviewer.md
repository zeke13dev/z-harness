---
description: Routes to the reviewer LLM (resolved via providers registry) to scrutinize a just-completed implementation task. Finds bugs, spec violations, missed edge cases, and DRY/KISS/SOLID violations.
role: rule
---

<!-- auto-generated shape: consultant-primary | consultant-secondary | reviewer differ only in ROLE below -->

You review a just-completed implementation task by delegating scrutiny to the configured reviewer provider via `scripts/resolve-provider.sh reviewer`.

## Role

`ROLE=reviewer`

## How to resolve and call the provider

```bash
DESCRIPTOR="$(bash scripts/resolve-provider.sh reviewer)"
# DESCRIPTOR is JSON: {"role","provider","command","args_template","stdin","timeout_s","model_label"}

COMMAND="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["command"])')"
ARGS="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" ".join(d["args_template"]))')"
USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["stdin"])')"
MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"

TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
  export Z_HARNESS_TIMEOUT_WARNED=1
fi

if [ "$USE_STDIN" = "True" ]; then
  if [ -n "$TIMEOUT_CMD" ]; then
    RESPONSE="$(printf '%s' "$PROMPT" | "$TIMEOUT_CMD" "$TIMEOUT" $COMMAND $ARGS)"
  else
    RESPONSE="$(printf '%s' "$PROMPT" | $COMMAND $ARGS)"
  fi
else
  if [ -n "$TIMEOUT_CMD" ]; then
    RESPONSE="$("$TIMEOUT_CMD" "$TIMEOUT" $COMMAND $ARGS "$PROMPT")"
  else
    RESPONSE="$($COMMAND $ARGS "$PROMPT")"
  fi
fi
```

If `resolve-provider.sh` exits non-zero, report the exact error line from stderr to the caller and stop.

## Inputs from caller

The caller will give you:
- Task ID and description (from TASKS.md)
- Absolute path to `diff.patch` for this task (preferred — scrutinize the change, not the whole file)
- Absolute paths of changed files (fallback / supplemental)
- Acceptance criteria for the task (verbatim from the task block)
- **`$BASE` path** — read SPEC.md yourself with the Read tool. Read the sections relevant to the changed files.
- **`relevant_docs`** (paths, may be empty) — `docs/llm/<concept>.json` files for concepts the diff touches. **Read these BEFORE composing the review prompt** — they state invariants and `consumed_by` relationships that may flag drift the diff alone can't show.
- Optional: **related downstream files** (paths only) — up to 3 related-consumer file paths to grep for contract drift if the diff touches a contract surface.

## Procedure

0. **Emit a `review_start` event** before doing anything else, and a `review_end` event before returning. Use the helper:

```bash
TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" start "tasks/<task-id>" review \
  "$(printf '{"id":"%s","cycle":%d}' "<task-id>" "<1 on first review, N on subsequent cycles>")")"
# ... do the work below ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$TOKEN" \
  "$(printf '{"id":"%s","cycle":%d,"blockers":%d,"majors":%d,"prompt_chars":%d,"response_chars":%d,"return_chars":%d}' \
     "<task-id>" "<cycle>" "$BLOCKERS" "$MAJORS" "${#PROMPT}" "${#RESPONSE}" "${#RETURN}")"
```

1. Read `diff.patch` (Read tool). This is the primary review artifact.
2. Read each changed file in full only as needed for surrounding context the diff doesn't show.
3. Read the relevant SPEC.md section.
4. Build a review prompt:

```
You are reviewing code that Claude just wrote for task <ID>: <title>.

Spec (excerpt):
<spec section verbatim>

Acceptance criteria:
<criteria>

Diff (primary artifact — focus your scrutiny on what changed):

<diff.patch contents>

Surrounding file context (only if relevant to evaluating the diff):

=== <path> ===
<excerpt>

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

**OUTPUT BUDGET — respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).
```

5. Call the provider:

```bash
if [ "$USE_STDIN" = "True" ]; then
  if [ -n "$TIMEOUT_CMD" ]; then
    RESPONSE="$(printf '%s' "$PROMPT" | "$TIMEOUT_CMD" "$TIMEOUT" $COMMAND $ARGS)"
  else
    RESPONSE="$(printf '%s' "$PROMPT" | $COMMAND $ARGS)"
  fi
else
  if [ -n "$TIMEOUT_CMD" ]; then
    RESPONSE="$("$TIMEOUT_CMD" "$TIMEOUT" $COMMAND $ARGS "$PROMPT")"
  else
    RESPONSE="$($COMMAND $ARGS "$PROMPT")"
  fi
fi
```

6. Archive the transcript and log the event:

```bash
TASK_ID="<task-id from caller>"
PROVIDER="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["provider"])')"
DIR="z-harness/archive/tasks/$TASK_ID"
mkdir -p "$DIR"
printf '%s\n' "$PROMPT"   > "$DIR/review.prompt.md"
printf '%s\n' "$RESPONSE" > "$DIR/review.response.md"

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/$TASK_ID" review \
  "$(printf '{"provider":"%s","model_label":"%s","prompt_chars":%d,"response_chars":%d,"return_chars":%d,"wall_ms":%d}' \
     "$PROVIDER" "$MODEL_LABEL" "${#PROMPT}" "${#RESPONSE}" "${#RETURN}" "$WALL_MS")"
```

7. **Extract a tight return payload — DO NOT return the raw response to the caller.** Build `$RETURN` by extracting **only** the findings section:

```bash
RETURN="$(printf '%s\n' "$RESPONSE" \
  | awk '/^\*\*Findings\*\*|^### Blockers|^### Major|^## [A-Za-z]+ review/{found=1} found' \
  | head -c 8000)"
```

If awk yields nothing (the provider returned the verbatim "No blockers or majors found." line), use the literal string. **Hard cap `$RETURN` at 8000 characters.**

8. Return `$RETURN` to the caller, grouped by severity. Do not soften, do not editorialize.

## Output format (the structured `$RETURN`, ≤8 KB)

```
## Reviewer review: task <ID>

### Blockers
<findings>

### Major
<findings>
```

Minors / nits are intentionally **dropped from the return** (blockers+majors only; the implementer self-check already handles minors). They remain in the on-disk transcript for retro analysis.

If the CLI errors, report the exact error in ≤200 chars.
