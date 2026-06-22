---
name: z-do
disable-model-invocation: false
description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Routes to the right planning/debug workflow when scope or bug signals exceed direct execution.
argument-hint: <small task description>
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

## STOP — DEPRECATED ALIAS

**Print to the user:** "Note: /z-do is deprecated and now routes to /z-plan --quick (L1)."

STOP. This command is a deprecated alias. You MUST immediately invoke `/z-plan --quick $ARGUMENTS` and do NOT continue past this section for any new invocation. Hand off to `/z-plan --quick` right now — pass `$ARGUMENTS` verbatim and terminate this command's execution. Do not read, execute, or act on any section below this one.

```
/z-plan --quick $ARGUMENTS
```

---

**BACKWARD-COMPATIBILITY ONLY — DO NOT EXECUTE FOR NEW INVOCATIONS**

The legacy phases below exist solely so that tooling that reads already-created `approach.md` / `premise.md` artifacts (e.g. `/z-improve`, run-brief rendering) continues to function without changes. A new invocation must never reach this line.

---

You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.

Task (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What's the task?" via their native channel. Silent omission is forbidden. -->
**If empty**, use `AskUserQuestion`: "What's the task?" Block until answered.

## Setup

1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
2. `export Z_HARNESS_SLUG=adhoc`
3. Export archive dir (required by Run Brief finalize fragment):
   ```bash
   export CURRENT_ARCHIVE_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir)/adhoc/archive/$RUN"
   mkdir -p "$CURRENT_ARCHIVE_DIR"
   ```
4. (CURRENT_ARCHIVE_DIR already set in step 3)
5. **Version stamp + log:**
   ```bash
   export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]; v["session_id"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>" "$Z_HARNESS_SESSION_ID")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
   ```

   **Run Brief init (immediately after `do_run_start`).** Registry: `/z-do`, profile `lite`, artifact `approach.md` (fallback `premise.md`).
   ```bash
   RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
   bash "$RB_SH" init --run "$RUN" --command /z-do --slug "$Z_HARNESS_SLUG" --profile lite \
     --intent "<task from $ARGUMENTS — max 240 chars; not the command name alone>"
   export RUN_BRIEF_PROFILE=lite
   export RUN_BRIEF_ARTIFACT="$CURRENT_ARCHIVE_DIR/approach.md"
   export RUN_BRIEF_ARTIFACT_FALLBACKS="$CURRENT_ARCHIVE_DIR/premise.md"
   ```

   **Active-plan registration (immediately after do_run_start).** Register this run in the shared registry. Graduated failure policy — never silent-continue on failure:
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
     --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-do --phase do \
     --session "$Z_HARNESS_SESSION_ID"
   REG_RC=$?
   ```
   - `REG_RC == 0` → registered; proceed.
   - `REG_RC == 3` (no record written) → emit `registry_error` event; interactive → `AskUserQuestion` proceed/abort; unattended → proceed+log (or halt if `Z_HARNESS_STRICT_OVERLAP=1`). No deregister on abort (no record).
   - Any OTHER nonzero → treat as `REG_RC == 3`.
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
     "$(printf '{"op":"register","run_id":"%s","rc":%d}' "$RUN" "$REG_RC")"
   ```

   **FINALIZE_STATUS rule:** On any run-ending halt after `REG_RC == 0`, execute **Run Brief — halt finalize** (below) before `deregister --status aborted`. On normal completion (Phase 7), deregister with `complete`. If register failed, do NOT deregister.

6. **Config resolution:**
   ```bash
   export Z_HARNESS_RUN="$RUN"
   eval "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" export-env)"
   ```
   See `docs/human/config.md` for available knobs (`notify.level`, `docs.always_apply`).

## Plan Route Check

<!-- PLAN_ROUTE_CHECK_START -->
Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan`, `/z-map`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.

Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route to `/z-plan <task>` when this exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, or when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
- Route to `/z-map <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.

Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.

If at any point you discover:

- **>3 files** need editing
- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
- **Cross-module / cross-crate impact** OR **schema change**
- User says "this might be bigger than I thought"

→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, then notify and ask the user to switch / continue if the hard threshold allows continuation / abandon:
```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && \
  PushNotification("z-do: route decision reached — your input is needed to proceed.")
```
If the user chooses switch or abandon (ending the run), per the FINALIZE_STATUS rule execute **Run Brief — halt finalize** (below) with reason `route gate — user chose switch or abandon`.
If the user chooses **continue**, deregister is NOT called here — the run continues and Phase 7 handles it normally.

`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.

Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase 1 — Premise check (mandatory, quick)

One paragraph in main thread: is the stated task actually the right problem? Could it be config, expected behavior, or symptom of something else? Is there a materially better path?

If a concern surfaces → notify and raise via `AskUserQuestion` before proceeding:
```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && \
  PushNotification("z-do: premise concern — your input is needed before continuing.")
```
Otherwise, write a single-sentence "premise accepted: <restated goal>" and continue.

Save to `$CURRENT_ARCHIVE_DIR/premise.md`.

## Phase 2 — Ground (doc-fetcher first)

Per the global rule, if `docs/llm/INDEX.json` exists AND `docs.always_apply` is `always` (the default; read via `config.py get docs.always_apply`), dispatch `doc-fetcher` (Haiku) BEFORE any other reading:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement and skip if unavailable. Proceeds with reduced grounding. -->
Agent(subagent_type="doc-fetcher",
      description="Doc context for: <task>",
      prompt="query: <one-sentence task>\nrepo_root: <abs path>\ndepth: standard")
```

If `docs.always_apply` is `never`, skip doc-fetcher entirely and proceed directly to Read/Grep/Glob.

Use doc-fetcher's return to constrain what files you read next. If `STATUS: no_docs` / `no_match` / `partial`, fall back to direct Read/Grep/Glob — do NOT spawn Explore in `/z-do` (too expensive for this command).

Read at most 3-5 files from main thread to fill gaps.

If a `DRIFT WARNING` came back, log `doc_drift` and continue.

## Phase 3 — Inline approach note (NO decisions.md, NO upfront consult)

In a single short message to yourself, state:
- What you're about to change (2-3 sentences)
- Files to touch (list)
- Acceptance: how you'll know it worked

Save to `$CURRENT_ARCHIVE_DIR/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.

**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.

## Phase 4 — Implement inline

Edit / Write the files. Apply the implementer self-check:

1. No broad exception handlers added.
2. No scope expansion outside `approach.md` "Files to touch".
3. No unsolicited validation / error paths.
4. No new public surface beyond what `approach.md` describes.
5. No stale docstrings / comments left behind.

If mid-implementation you discover scope growth → notify and halt:
```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event error)" = yes ] && \
  PushNotification("z-do: scope growth detected mid-implementation — halted for your decision.")
```
Then `AskUserQuestion`:
- "Switch to the recommended routed command"
- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
- "Abandon"

Hard limit: if you find yourself touching >5 files inline, halt regardless.

## Phase 5 — Codex review (MANDATORY safety gate)

Non-negotiable. This is what makes `/z-do` z-harness rather than freewheeling.

```bash
git diff > "$CURRENT_ARCHIVE_DIR/diff.patch"
```

Spawn the reviewer:

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement and skip the reviewer Agent() call. The safety gate cannot run
     without subagent support; document the gap. -->
Agent(
  subagent_type="reviewer",
  description="Codex review of /z-do <run>",
  prompt="task id: <RUN>\ntask description: <approach.md body, ≤500 chars>\nacceptance criteria: <approach.md Acceptance line>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\n$BASE: $CURRENT_ARCHIVE_DIR  (read approach.md and premise.md yourself if you need more context)"
)
```

Parse the return (capped at 8 KB, blockers + majors only).

**On blockers/majors:**
- First failure: re-edit inline. Re-run diff; if byte-identical → halt `no_change_on_retry`. Else re-spawn reviewer once.
<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the reviewer
     second-failure gate via their native channel. Silent omission is forbidden. -->
- Second failure: `AskUserQuestion` — proceed anyway / patch manually / abandon.

**No blockers/majors** → accept.

**Advisory eval-reviewer.** When `personas.review_eval` is ON (default), an advisory persona reviewer also runs in parallel with the base codex reviewer, per the shared snippet at [## Advisory eval-reviewer (shared snippet)](#ADVISORY-EVAL-REVIEWER) in `skills/z-execute/SKILL.md`. The advisory arm draws a single `random-for-role reviewer` persona (`reviewer_participant=random_arm`), dispatches alongside the base reviewer, and logs its verdict for data-collection only. It is advisory and logged only — it NEVER changes the pass/fail outcome of this phase. Only the base codex reviewer's blockers/majors drive the retry/halt logic above.

## Phase 6 — (Optional) end-of-run cross-LLM consult

This phase is **off by default**. Only run if any of:

- User explicitly asked for a consult ("get a second opinion")
- A non-obvious decision DID surface mid-run but you continued (rare — usually you'd escalate)
- The implementation diverges meaningfully from the stated approach.md

If running, spawn one or both consultants on the **diff + approach**, framed as "review this small change — anything wrong?":

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement and skip the optional consult Agent() call. Phase 6 is optional. -->
Agent(subagent_type="consultant-secondary",
      description="End-of-run consult for /z-do <RUN>",
      prompt="MODE: post-do-review\n\nTask: <approach summary>\nDiff: <inline or path>\nCodex-reviewer findings: <accepted / what was waived>\n\nAsk: is this change sound? Anything the reviewer missed?")
```

Apply the "one reason it might be wrong" check to each finding. If it raises a real concern, halt and ask the user.

## Phase 7 — Finalize

1. **Run Brief finalize (registry Phase 7).** Set `outcome` / `status` / `next` before the shared fragment. Chat and push are renders only — lite profile omits `APPROACH` / `DECISIONS` in chat (see `render-run-brief.py`); do not author independent completion prose.

   ```bash
   export RUN_BRIEF_PROFILE=lite
   export RUN_BRIEF_ARTIFACT="$CURRENT_ARCHIVE_DIR/approach.md"
   export RUN_BRIEF_ARTIFACT_FALLBACKS="$CURRENT_ARCHIVE_DIR/premise.md"
   export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
   export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"

   RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
   bash "$RB_SH" set-section --run "$RUN" --section outcome \
     --value "Shipped. ${N_FILES} files changed; review passed (${CYCLES} review cycle(s))."
   bash "$RB_SH" set-section --run "$RUN" --section status --value "shipped"
   bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Done — no follow-up required", "command": null}
JSON
   ```

   <!-- include: _fragments/run-brief-finalize.md -->

2. Log run end:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_end \
     "$(printf '{"status":"shipped","files_changed":%d,"review_cycles":%d,"consult_at_end":%s}' \
        "$N_FILES" "$CYCLES" "$DID_CONSULT")"
   ```
3. **Suggest `/z-improve` when this run had friction.** Run the nudge helper rather than eyeballing it — it scans this run's events and prints a one-line suggestion only if friction signals fired (auto-bail/escalation, doc drift, review retries, degraded consult, …), staying silent on a clean run:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/improve-nudge.sh" "$RUN" "adhoc/$RUN"
   ```
   If it emits a line, relay it verbatim to the user.
4. **Deregister this run** from the active-plan registry (best-effort, non-fatal). Per the FINALIZE_STATUS rule (Setup step 5): normal completion deregisters with `complete`; if the fragment's `--require` step set `FINALIZE_STATUS=aborted`, deregister with `aborted` instead.
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
     --run-id "$RUN" --status "${FINALIZE_STATUS:-complete}" || true   # CLI self-logs registry_error on failure
   ```

## Run Brief — halt finalize

Before `deregister --status aborted` on any halt after `run-brief.sh init` (unless register failed — no deregister). Substitute `<reason>` in the outcome line. Lite profile: Intent + Outcome + Next only (no `APPROACH` / `DECISIONS` in chat render).

```bash
export RUN_BRIEF_PROFILE=lite
export RUN_BRIEF_ARTIFACT="$CURRENT_ARCHIVE_DIR/approach.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS="$CURRENT_ARCHIVE_DIR/premise.md"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Review run status and retry or escalate", "command": null}
JSON
```

<!-- include: _fragments/run-brief-finalize.md -->

```bash
FINALIZE_STATUS=aborted
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status aborted 2>/dev/null || true
```

## Hard rules

- **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
- **No upfront cross-LLM consult.** Only at the end, only if triggered.
- **Codex review is non-negotiable.** Skipping it makes /z-do not-z-harness.
- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
- **Never read `docs/llm/*.json` from main thread.**
- **Always log to `$CURRENT_ARCHIVE_DIR/`** — `/z-improve` reads this.
- **No emojis.**

### Git history-rewrite safety

Before recommending any `git reset --hard HEAD~N`, `git commit --amend`, or interactive-rebase squash on a branch tracking an upstream: for each commit being rewritten, run `git branch -r --contains <sha>`. If the upstream ref appears, STOP — recommend rebase or new-commit instead, never silent rewrite. Force-push to main requires explicit per-incident user authorization with (i) list of overwritten commits and (ii) content-equivalence/superset demonstration.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 2 doc-fetcher Agent(); Phase 5 base codex reviewer Agent(); Phase 5 advisory eval-reviewer Agent() (when `personas.review_eval` ON — advisory only, see shared snippet); Phase 6 optional consultant-secondary Agent() call |
| `ask_user` | yes | Empty arguments gate; Phase 5 reviewer second-failure gate |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
