---
name: z-improve
description: "Post-run retrospective. Analyzes ONE z-harness run's events.jsonl + artifacts, identifies friction signals (slow phases, retries, doc drift, blocked askings, reviewer cycles), and opens a discussion with the user about concrete edits to the z-harn..."
---

You are running **z-harness `/z-improve`** — the self-improvement retro for a completed run.

This is read-mostly. You analyze logs and artifacts, propose specific edits to the **z-harness repo** (commands, agents, scripts) that would reduce future friction, then have a discussion with the user. Edits to the z-harness repo only happen with explicit per-suggestion approval.

Target (from `$ARGUMENTS`):

$ARGUMENTS

## Phase 0 — Resolve target run

`$ARGUMENTS` should name one of:
- `<slug>` → use the most recent run under `$Z_HARNESS_PLAN_DIR/archive/`
- `$Z_HARNESS_PLAN_DIR/<run-id>` → exact run
- `adhoc/<run-id>` → a `/z-do` run
- (empty) → list the 10 most recent runs across all slugs (covering both new layout `<base>/plans/*/archive/*` and legacy flat `<base>/*/archive/*` including adhoc):
  ```bash
  BASE="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir)"
  ls -dt "$BASE"/plans/*/archive/* "$BASE"/*/archive/* "$BASE"/adhoc/archive/* 2>/dev/null | awk '!seen[$0]++' | head -10
  ```
  Then `AskUserQuestion` to pick.

Resolve to absolute paths:
- `$RUN_DIR = $Z_HARNESS_PLAN_DIR/archive/<run-id>` (or `z-harness/adhoc/archive/<run-id>`)
- `$EVENTS = $RUN_DIR/events.jsonl`

If `$EVENTS` doesn't exist, tell the user this run has no telemetry and ask whether to proceed analyzing artifacts only.

Where the z-harness plugin itself lives — needed because proposed edits target it, not the target repo:
```bash
Z_HARNESS_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"
# Z_HARNESS_ROOT/commands/*.md, Z_HARNESS_ROOT/agents/*.md, Z_HARNESS_ROOT/scripts/*.sh
```

## Phase 1 — Load run data

Read (all from main thread — these are tight):

- `$EVENTS` — events.jsonl. Parse with `python3 -c 'import json; [print(json.loads(l)) for l in open(sys.argv[1])]'` or jq.
- `$RUN_DIR/manifest.json` if present
- The run's primary artifact, if present:
  - full plan: `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md`
  - light plan: `$Z_HARNESS_PLAN_DIR/FIX.md`
  - z-do: `$RUN_DIR/approach.md` + `$RUN_DIR/premise.md`
  - audit: `$Z_HARNESS_PLAN_DIR/REPORT.md`
  - debug: `$Z_HARNESS_PLAN_DIR/DEBUG.md ## Problem` and `DEBUG.md ## Post-mortem` if present
- Codex review transcripts (under `$RUN_DIR/transcripts/`) if present — read at most 2, the most recent.

Save a one-paragraph "run summary" to scratch (don't write it to disk yet).

## Phase 2 — Friction analysis

Scan the events stream for signals. Compute (and write to `$RUN_DIR/analysis.md` as a draft):

| Signal | How to compute | Threshold of interest |
|---|---|---|
| Slow phase | `max(phase_end.wall_ms) - min(phase_end.wall_ms)` outliers; phases taking >2x median | any phase taking >5 min, or >3x the run's median |
| User-wait dominance | `sum(user_wait_end.wall_ms) / total run wall` | >40% — suggests too many `AskUserQuestion` blocks |
| Review retry | count of `task_review_retry` or codex re-spawns | ≥1 |
| Doc drift | count of `doc_drift` events | ≥1 — INDEX.json needs refresh |
| Consult disagreement | gemini vs codex divergence noted in transcripts | any case where orchestrator had to pick a side |
| Escalation | `do_escalation` or auto-bail | any |
| Push-back failure | `no_change_on_retry` | any — means the orchestrator pushed back instead of editing |
| Implementation overshoot | `files_changed` > files declared in plan/approach | any divergence |
| Spec drift | `spec_precheck` returned `spec_problem` | any |

For each signal that fires, articulate:

1. **What happened** (one sentence with the event payload quoted)
2. **Likely root cause** (one sentence — what about the harness design contributed?)
3. **Candidate fix** (one sentence — concrete edit to a specific z-harness file)

This is the basis for the discussion.

## Phase 3 — Draft proposal

Write `$RUN_DIR/analysis.md` and (the deliverable) `$Z_HARNESS_ROOT/improvements/<YYYY-MM-DD>-<slug-or-adhoc-RUN>.md`:

```markdown
# Z-harness retro: <slug or adhoc/RUN>

**Run:** <RUN_DIR>
**Date:** <today>
**Status:** draft — under discussion

## Run summary
<1 paragraph: what command ran, what was accomplished, top-level wall time>

## Friction observed
<bulleted list, one per signal that fired in Phase 2>

## Proposed improvements

### Proposal 1: <one-line title>
- **Symptom:** <what friction signal triggered this>
- **Edit target:** <specific file path under z-harness/, e.g. commands/z-plan.md Phase 6>
- **Proposed change:** <2-3 sentence description of the edit>
- **Why this helps:** <rationale tied to the symptom>
- **Risk:** <what could go wrong with the edit>

### Proposal 2: ...
...

## Discussion log
<filled in during Phase 5>

## Decisions
<filled in during Phase 6 — per-proposal: accepted / deferred / rejected, with note>
```

Hard limit: ≤5 proposals per retro. If more candidates surface, pick the 5 with the highest "would this have shortened this run" score and list the rest in an "## Also considered" section at the bottom.

## Phase 4 — (Optional) cross-LLM consult on proposals

If any proposal touches a non-trivial part of the harness (cross-command behavior, new subagent, change to event schema, change to consultation rules), spawn a bundled consult:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
      description="z-improve consult — Gemini",
      prompt="MODE: harness-self-improvement\n\nObserved friction:\n<bulleted signals>\n\nProposed harness edits:\n<proposals 1..N>\n\nAsk: which proposals actually address the root friction? which create new problems? what did I miss?")
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
      description="z-improve consult — Codex",
      prompt="<same body>")
```

Apply the "one reason it might be wrong" check to each consultant suggestion before incorporating. Update the improvements doc's `## Discussion log` with cross-LLM input.

Skip this phase if all proposals are obvious one-line tweaks.

## Phase 5 — Discussion with the user

Present the proposals via `AskUserQuestion`. For EACH proposal separately (one question per proposal — do not batch multi-select for these, the user needs to evaluate them one at a time):

- "Accept — apply this edit"
- "Refine — let me change the proposal" (free-text follow-up)
- "Defer — note it but don't apply now"
- "Reject — this isn't the right fix"

Append the user's response (verbatim where they wrote free text) to the improvements doc's `## Discussion log`.

Loop: if the user picks "Refine", revise the proposal in place and re-ask. Cap at 3 refine cycles per proposal — if not converged, mark "Defer" and move on.

## Phase 6 — Record decisions

Fill in the improvements doc's `## Decisions` section. For each proposal:

- **Accepted** → apply the edit now (Phase 7) AND record it
- **Deferred** → record with reason
- **Rejected** → record with reason

## Phase 7 — Apply accepted edits

For each accepted proposal, apply the named edit to the z-harness file with `Edit`. After each edit, run:

```bash
diff -u <(git -C "$Z_HARNESS_ROOT" show HEAD:<file>) "$Z_HARNESS_ROOT/<file>" > "$RUN_DIR/improvement-<n>.diff"
```

**Do not commit.** Leave the working tree dirty so the user can review with `cd "$Z_HARNESS_ROOT" && git diff` and commit themselves.

If an edit fails sanity check (e.g. invalid yaml frontmatter, broken markdown structure), revert it and reclassify the proposal as "Deferred — needs manual application".

After all diffs are written, invoke `/z-suggest-memory`:

```
/z-suggest-memory
concept_hints: <space-separated slugs — see derivation rule below>
context: "z-improve retro for <slug>: accepted <N> proposal(s) — <one-sentence summary of what changed>"
```

**concept_hints derivation rule** — apply before invoking `/z-suggest-memory`:

```bash
# For each z-harness file path touched by accepted edits, derive a slug:
#   commands/z-plan.md        → z-plan
#   skills/z-plan/SKILL.md   → z-plan
#   agents/reviewer.md  → reviewer
# Rule: strip the parent directory prefix and strip the .md or /SKILL.md suffix.
# Deduplicate the resulting list.
# concept_hints = space-joined slug list

# Example (bash):
concept_hints=""
for path in "${touched_files[@]}"; do
  slug="${path##*/}"          # basename
  slug="${slug%.md}"          # strip .md
  slug="${slug%/SKILL}"       # strip /SKILL (already stripped by basename, no-op)
  # For skills/z-plan/SKILL.md the basename is SKILL.md → slug becomes SKILL; use dirname instead:
  # Re-derive: if basename == SKILL, use the parent dir name
  if [[ "$slug" == "SKILL" ]]; then
    slug="$(basename "$(dirname "$path")")"
  fi
  concept_hints="$concept_hints $slug"
done
concept_hints="${concept_hints# }"  # trim leading space
# Deduplicate:
concept_hints="$(echo "$concept_hints" | tr ' ' '\n' | sort -u | tr '\n' ' ' | sed 's/ $//')"
```

**Salience guidance — read before invoking:**

> **Default to Cancel** unless a genuinely novel anti-pattern, process insight, or non-obvious decision rationale surfaced during the retro discussion that would materially improve a future run of the same command. Cancel is a first-class outcome and should be chosen most of the time. Only persist memory when the insight is not already documented in the improvements doc or in existing docs/llm/ concepts — not just because edits were applied.

Log the outcome:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" suggest_memory_called \
  "$(printf '{"memories_written":%d,"concept":"%s"}' "$MEMORIES_WRITTEN" "$CONCEPT_SLUG")"
```

(`$MEMORIES_WRITTEN` = 0 if user chose Cancel; `$CONCEPT_SLUG` = primary slug derived from touched file paths.)

## Phase 8 — Finalize

1. Update the improvements doc's `**Status:**` to `complete`.
2. Log run end:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN-improve" improve_run_end \
     "$(printf '{"target_run":"%s","proposals":%d,"accepted":%d,"deferred":%d,"rejected":%d}' \
        "$RUN_DIR" "$N_PROPOSALS" "$N_ACC" "$N_DEF" "$N_REJ")"
   ```
3. Push-notify (if policy ≠ `off`): "z-improve complete. <N> proposals; <X> accepted (uncommitted in z-harness repo)."
4. Summary to user (3-5 sentences): top friction signal, top accepted change, what to commit in the z-harness repo.

## Hard rules

- **Read-only on the target repo.** This command analyzes a run; it never edits the target repo's code, only the z-harness plugin itself.
- **Never commit z-harness edits.** Leave the working tree dirty for user review.
- **Per-proposal user approval.** No batch-applying.
- **One run per invocation.** Patterns across many runs belong to a different (future) command — this is bounded retro.
- **No emojis.**
- **Cap proposals at 5.** Beyond that, the signal-to-noise drops sharply.
