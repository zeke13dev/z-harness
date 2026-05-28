---
name: z-plan-light
description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sideways, or to contextual bug workflows when light mode is not the best fit.
argument-hint: <fix description>
---

You are running **z-harness `/z-plan-light`** — a fast path for one-file-or-few-files fixes. Target: ≤10 min wall time end-to-end.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.

This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.

## Setup

1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Check for an existing slug collision first (`ls z-harness/` to detect matching dirs). **If a collision is found, prompt the user via `AskUserQuestion` to confirm or choose a different slug. This collision check runs UNCONDITIONALLY and is never bypassed by the resolver below.**

   After the collision check passes (no collision found, or the user confirmed a new slug), apply the soft non-obvious-slug confirmation gate:

   ```bash
   # Only reached after collision check has already passed.
   RESOLVED="$(python3 scripts/config.py resolve-question workflow.slug_confirm)"
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

   Branch on `$RESULT`:
   - `skip`: accept the derived slug silently — no AskUserQuestion. Emit `askuser_skipped` event with `{question_id: "workflow.slug_confirm", source: "$SOURCE"}`.
   - `prefill`: present the AskUserQuestion normally, pre-select the derived slug as the recommended option (label suffix: ` (Recommended — your preference)`).
   - `ask`: if non-obvious, confirm via `AskUserQuestion` normally. If `$SOURCE == "conflict"`, add to the question header: `(Note: config says <X>, memory says <Y> — your answer below will be offered as a conflict-resolution write target.)` After the user picks an answer that differs from both stored values, surface a one-shot follow-up: "Record your answer as the new preference? (config / memory:very_strong / memory:strong / no)".

   **Invariant:** the collision check above is a hard safety prerequisite that runs unconditionally regardless of resolver outcome. The resolver only governs the soft non-obvious-slug confirmation gate.
2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
6. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
   ```
7. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).
8. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.

## Plan Route Check

<!-- PLAN_ROUTE_CHECK_START -->
Run this check after quick exploration and before Phase 2 decision selection; run it again before inline implementation if scope grows. `/z-plan-light` may route down, up, sideways, or to contextual bug workflows only under the conditions below.

Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `plan_validation_intent`, `plan_amend_intent`, `has_fix_artifact`, and `docs_stale_or_drifted`. Set `plan_validation_intent`/`plan_amend_intent` only when the user re-enters this command on a slug with `SPEC.md`+`PLAN.md`+`TASKS.md` all present (see `agents/planning-router.md` for the language-match heuristic).

Deterministic routes:
- Route down to `/z-do <task>` only before writing `FIX.md` when this is a tiny implementation task with `candidate_files <= 3`, no non-obvious decisions, and no cross-module, schema, persistence, public API, or wire-format impact.
- Route up to `/z-plan <task>` when there are more than 5 candidate files, more than 2 non-obvious decisions, cross-module impact, schema/persistence impact, or public API/wire-format impact.
- Route sideways to `/z-map <topic>` when terrain is uncertain, source facts cannot yet be cited, or no-code terrain mapping is the next needed step.
- Route sideways to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
- Route contextually to `/z-fix <diagnosis>` only when the user already has a concrete bug hypothesis or diagnosis.
- Route contextually to `/z-debug <symptom>` only when there is an observed bug/symptom and the root cause is unknown.

Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.

At any phase, if you discover:

- **>5 candidate files** need editing
- **>2 non-obvious decisions** (per the rules `/z-plan` uses: new dep, public API change, algorithm with materially different tradeoffs, persistence change)
- **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
- **The user explicitly says** "this might be bigger than I thought"

→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.

`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.

Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase 1 — Premise + quick exploration (combined)

**Premise check.** Don't take the task description for granted:
- Is this actually a bug? Could it be config / expected behavior / a symptom of something else?
- Will the proposed fix (if the user named one) actually solve the underlying problem?
- Is there a materially better path the user hasn't considered?

If any concern surfaces → raise it with the user via `AskUserQuestion` before proceeding. Don't plan around a flawed premise.

**Quick exploration.**
1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
   ```
   Agent(subagent_type="doc-fetcher",
         description="Doc context for <slug>",
         prompt="query: <one-sentence fix description>\nrepo_root: <abs path>\ndepth: standard")
   ```
2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.

Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.

**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.

## Phase 2 — Identify the single key decision

Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.

If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.

## Phase 3 — Bundled cross-LLM consult

Spawn both consultants in parallel in a single message:

```
Agent(
  subagent_type="consultant-primary",
  description="Light-fix consult (Gemini) for <slug>",
  prompt="MODE: light-fix\n\nProblem: <1-paragraph>\nContext: <1-paragraph>\nKey decision: <statement>\nCandidate options (if any): <list with one-line tradeoffs>\nRelevant code snippets:\n<short quoted code with file:line markers>\n\nAsk: recommend an option with reasoning. Identify tradeoffs. Flag anything I haven't considered. Be concise — this is a single small fix, not a feature."
)
Agent(
  subagent_type="consultant-secondary",
  description="Light-fix consult (Codex) for <slug>",
  prompt="MODE: light-fix\n\n<same prompt body>"
)
```

Both transcripts archive themselves under `$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/`.

## Phase 4 — Synthesize + push back

When both return:

1. **One reason it might be wrong.** For each recommendation, articulate one concrete reason it could be wrong before accepting it. Mechanical, not optional.
2. **Synthesize.** Make the final call yourself, citing what you weighed.
3. **Flag shortcuts.** If any option is a shortcut over the robust long-lasting solution, mark it explicitly — needs Phase 5 user approval.
4. **Cross-LLM disagreement.** If Gemini and Codex disagree substantively, surface the disagreement to the user in Phase 5 — do not silently pick one.

## Phase 5 — Present + approve

Send `PushNotification` (if policy != `off`): "Light-mode decision ready for review."

Present a brief synthesis (3-5 bullets) via `AskUserQuestion`:
- "Approve fix as proposed"
- "Modify — I want to change <X>" (free-text follow-up)
- "Abandon — this isn't the right approach"

For any flagged shortcut: separate explicit approval via `AskUserQuestion` (default to robust if not approved).

If user picks **Abandon** → write nothing more; log `light_run_end` with `status: abandoned`; exit.

## Phase 6 — Write FIX.md

Write `$Z_HARNESS_PLAN_DIR/FIX.md`:

```markdown
# Fix: <slug>

**Run:** <RUN>
**Status:** approved (not yet shipped)
**Plugin version:** <z_harness_version from setup>

## Problem
<1 paragraph>

## Root cause
<1 paragraph>

## Approach
<concrete plan: what files change, what stays the same>

## Files to change
- `<abs path 1>`
- `<abs path 2>`

## Acceptance
- [ ] <criterion 1>
- [ ] <criterion 2>

## Cross-LLM consensus
- Gemini: <one-line recommendation>
- Codex:  <one-line recommendation>
- Synthesized call: <your decision + brief rationale>

## Approved shortcuts
<list each shortcut + why approved; or "none">

## Docs touched
<slug(s) from docs/llm/ matching changed files, or "none"; consumed by /z-maintain-docs later>
```

No SPEC.md / PLAN.md / TASKS.md generated. FIX.md is the whole plan.

## Phase 7 — Inline implementation (NO implementer subagent)

The orchestrator (you, in main thread) reads the files listed in FIX.md "Files to change" and applies the edits directly with the Edit / Write tools. For 1-5 file edits the main thread already has all the context — spawning a fresh implementer just doubles token cost.

**Apply the same self-check the implementer subagent would** (from `agents/implementer.md`):
1. No broad exception handlers added.
2. No scope expansion outside FIX.md's "Files to change" list.
3. No unsolicited validation / error paths.
4. No new public surface beyond what FIX.md describes.
5. No stale docstrings / comments left behind.

If you applied any fix from the checklist, note it in the user-facing summary later.

**Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
- "Switch to the recommended routed command"
- "Continue in light mode — update FIX.md and proceed" (only if no hard threshold forbids continuation)
- "Spawn implementer subagent for isolation — keep light mode but isolate the implementation"

Hard limit: if you find yourself touching >7 files inline, halt regardless — that's no longer a light-mode fix.

## Phase 8 — Codex review (safety gate, kept)

This step is non-negotiable. Even in light mode, post-implementation review is the correctness guarantee.

```bash
git diff > $Z_HARNESS_PLAN_DIR/archive/$RUN/diff.patch
```

Spawn the reviewer:

```
Agent(
  subagent_type="reviewer",
  description="Codex review of <slug>",
  prompt="task id: <slug>\ntask description: <FIX.md Approach summary>\nacceptance criteria: <FIX.md Acceptance list>\ndiff.patch path: <abs path>\nchanged files: <abs paths from FIX.md>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths from FIX.md Docs touched>\n$BASE: $Z_HARNESS_PLAN_DIR  (read FIX.md yourself if you need more context)"
)
```

Parse the return (already capped at 8 KB, blockers + majors only).

**On blockers or majors:**
- **First failure**: re-edit inline based on findings. Re-run `git diff`; if byte-identical to prior diff (you pushed back instead of editing), halt with `no_change_on_retry`. Otherwise re-spawn `reviewer` once.
- **Second failure**: halt; `AskUserQuestion` — proceed anyway / patch manually / abandon.

**No blockers/majors** → accept.

## Phase 9 — Finalize

1. Update FIX.md `Status:` to `shipped` and check off the acceptance boxes you verified.
2. Mark the run done:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_end \
     "$(printf '{"status":"shipped","files_changed":%d,"review_cycles":%d}' "$N_FILES" "$CYCLES")"
   ```
3. Push-notify (if policy != `off`): "Fix complete. <N> files changed; review passed (<N> blockers/<M> majors resolved across <C> cycles)."
4. **If FIX.md "Docs touched" is non-empty**, suggest: "Run `/z-maintain-docs --audit` to refresh affected concepts."
5. Brief summary to user (3-5 sentences): what changed, what the reviewer flagged, what's next.

## Hard rules

- **Never skip the codex review.** Light mode is about cutting planning overhead, not correctness.
- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
- **Always emit cross-LLM consult** — both Gemini and Codex, in parallel.
- **Never overwrite an existing `$Z_HARNESS_PLAN_DIR/` directory** without asking the user.
- **No emojis** anywhere in artifacts.
