# /z-do

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
Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-map`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.

Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
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
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
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
     <!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
     without subagent support; document the gap. -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
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

**Advisory eval-reviewer.** When `personas.review_eval` is ON (default), an advisory persona reviewer also runs in parallel with the base codex reviewer, per the shared snippet at [## Advisory eval-reviewer (shared snippet)](#ADVISORY-EVAL-REVIEWER) in `commands/z-implement-all.md`. The advisory arm draws a single `random-for-role reviewer` persona (`reviewer_participant=random_arm`), dispatches alongside the base reviewer, and logs its verdict for data-collection only. It is advisory and logged only — it NEVER changes the pass/fail outcome of this phase. Only the base codex reviewer's blockers/majors drive the retry/halt logic above.

## Phase 6 — (Optional) end-of-run cross-LLM consult

This phase is **off by default**. Only run if any of:

- User explicitly asked for a consult ("get a second opinion")
- A non-obvious decision DID surface mid-run but you continued (rare — usually you'd escalate)
- The implementation diverges meaningfully from the stated approach.md

If running, spawn one or both consultants on the **diff + approach**, framed as "review this small change — anything wrong?":

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     <!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
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
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
| `ask_user` | yes | Empty arguments gate; Phase 5 reviewer second-failure gate |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
