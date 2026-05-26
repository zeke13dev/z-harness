---
description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Routes to the right planning/debug workflow when scope or bug signals exceed direct execution.
argument-hint: <small task description>
---

You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If empty**, use `AskUserQuestion`: "What's the task?" Block until answered.

## Setup

1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
2. `export Z_HARNESS_SLUG=adhoc`
3. `mkdir -p z-harness/adhoc/archive/$RUN`
4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
5. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
   ```
6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).

## Plan Route Check

<!-- PLAN_ROUTE_CHECK_START -->
Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.

Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
- Route to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.

Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.

If at any point you discover:

- **>3 files** need editing
- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
- **Cross-module / cross-crate impact** OR **schema change**
- User says "this might be bigger than I thought"

→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.

`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.

Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase 1 — Premise check (mandatory, quick)

One paragraph in main thread: is the stated task actually the right problem? Could it be config, expected behavior, or symptom of something else? Is there a materially better path?

If a concern surfaces → raise via `AskUserQuestion` before proceeding. Otherwise, write a single-sentence "premise accepted: <restated goal>" and continue.

Save to `z-harness/adhoc/archive/$RUN/premise.md`.

## Phase 2 — Ground (doc-fetcher first)

Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:

```
Agent(subagent_type="doc-fetcher",
      description="Doc context for: <task>",
      prompt="query: <one-sentence task>\nrepo_root: <abs path>\ndepth: standard")
```

Use its return to constrain what files you read next. If `STATUS: no_docs` / `no_match` / `partial`, fall back to direct Read/Grep/Glob — do NOT spawn Explore in `/z-do` (too expensive for this command).

Read at most 3-5 files from main thread to fill gaps.

If a `DRIFT WARNING` came back, log `doc_drift` and continue.

## Phase 3 — Inline approach note (NO decisions.md, NO upfront consult)

In a single short message to yourself, state:
- What you're about to change (2-3 sentences)
- Files to touch (list)
- Acceptance: how you'll know it worked

Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.

**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.

## Phase 4 — Implement inline

Edit / Write the files. Apply the implementer self-check:

1. No broad exception handlers added.
2. No scope expansion outside `approach.md` "Files to touch".
3. No unsolicited validation / error paths.
4. No new public surface beyond what `approach.md` describes.
5. No stale docstrings / comments left behind.

If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
- "Switch to the recommended routed command"
- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
- "Abandon"

Hard limit: if you find yourself touching >5 files inline, halt regardless.

## Phase 5 — Codex review (MANDATORY safety gate)

Non-negotiable. This is what makes `/z-do` z-harness rather than freewheeling.

```bash
git diff > z-harness/adhoc/archive/$RUN/diff.patch
```

Spawn the reviewer:

```
Agent(
  subagent_type="reviewer",
  description="Codex review of /z-do <run>",
  prompt="task id: <RUN>\ntask description: <approach.md body, ≤500 chars>\nacceptance criteria: <approach.md Acceptance line>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\n$BASE: z-harness/adhoc/archive/$RUN  (read approach.md and premise.md yourself if you need more context)"
)
```

Parse the return (capped at 8 KB, blockers + majors only).

**On blockers/majors:**
- First failure: re-edit inline. Re-run diff; if byte-identical → halt `no_change_on_retry`. Else re-spawn reviewer once.
- Second failure: `AskUserQuestion` — proceed anyway / patch manually / abandon.

**No blockers/majors** → accept.

## Phase 6 — (Optional) end-of-run cross-LLM consult

This phase is **off by default**. Only run if any of:

- User explicitly asked for a consult ("get a second opinion")
- A non-obvious decision DID surface mid-run but you continued (rare — usually you'd escalate)
- The implementation diverges meaningfully from the stated approach.md

If running, spawn one or both consultants on the **diff + approach**, framed as "review this small change — anything wrong?":

```
Agent(subagent_type="consultant-secondary",
      description="End-of-run consult for /z-do <RUN>",
      prompt="MODE: post-do-review\n\nTask: <approach summary>\nDiff: <inline or path>\nCodex-reviewer findings: <accepted / what was waived>\n\nAsk: is this change sound? Anything the reviewer missed?")
```

Apply the "one reason it might be wrong" check to each finding. If it raises a real concern, halt and ask the user.

## Phase 7 — Finalize

1. Log run end:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_end \
     "$(printf '{"status":"shipped","files_changed":%d,"review_cycles":%d,"consult_at_end":%s}' \
        "$N_FILES" "$CYCLES" "$DID_CONSULT")"
   ```
2. Push-notify (if policy ≠ `off`): "z-do complete. <N> files changed; review passed."
3. Brief 2-3 sentence summary to user: what changed, what's next.
4. If non-trivial friction surfaced during the run (auto-bail considered, doc_drift, retry on review), suggest: "Consider `/z-improve adhoc/$RUN` to retro this run."

## Hard rules

- **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
- **No upfront cross-LLM consult.** Only at the end, only if triggered.
- **Codex review is non-negotiable.** Skipping it makes /z-do not-z-harness.
- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
- **Never read `docs/llm/*.json` from main thread.**
- **Always log to `z-harness/adhoc/archive/$RUN/`** — `/z-improve` reads this.
- **No emojis.**

### Git history-rewrite safety

Before recommending any `git reset --hard HEAD~N`, `git commit --amend`, or interactive-rebase squash on a branch tracking an upstream: for each commit being rewritten, run `git branch -r --contains <sha>`. If the upstream ref appears, STOP — recommend rebase or new-commit instead, never silent rewrite. Force-push to main requires explicit per-incident user authorization with (i) list of overwritten commits and (ii) content-equivalence/superset demonstration.
