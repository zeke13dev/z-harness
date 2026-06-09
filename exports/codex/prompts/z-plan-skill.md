# /z-plan

You are running the **z-harness `/z-plan`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for existing slug names across both new and legacy plan layouts. If the derived slug matches an existing slug:
   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents — this is what namespaces every output path.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`
4a. Export run id, archive dir, and resolve config:
    ```bash
    export Z_HARNESS_RUN="$RUN"
    export CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"
    eval "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" export-env)"
    ```
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]; v["session_id"] = sys.argv[3]; v["command"] = "z-plan"
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>" "$Z_HARNESS_SESSION_ID")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
   ```
   Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).

   **Session-id persist (export-once + persist, invariant 7).** Immediately after run_start, persist the session id so a crash-resume can restore it before the claim acquire:
   ```bash
   # Export-once guard: Z_HARNESS_SESSION_ID was set above; persist it now.
   printf '%s\n' "$Z_HARNESS_SESSION_ID" > "$Z_HARNESS_PLAN_DIR/archive/$RUN/session-id"
   ```

   **Session-id restore on resume (invariant 7).** On a resume (the shell env is a fresh process), restore the persisted session id BEFORE the claim acquire so the self-reentry guard fires correctly:
   ```bash
   if [[ -z "$Z_HARNESS_SESSION_ID" && -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/session-id" ]]; then
     export Z_HARNESS_SESSION_ID="$(cat "$Z_HARNESS_PLAN_DIR/archive/$RUN/session-id")"
   fi
   ```

   **Claim acquire (claim-first ordering, invariant 2).** This runs BEFORE Run-Brief init, BEFORE register, BEFORE the docs/precontext scans, and BEFORE any artifact write. Pass `--command /z-plan` so the HOLDER string is `<session>::<run>::/z-plan` (required for heartbeat/release identity checks per T003 note):
   ```bash
   CLAIM_RC=0
   CLAIM_OUTPUT="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" acquire \
     --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
     --command /z-plan)" || CLAIM_RC=$?
   ```

   Branch on `$CLAIM_RC` — every path is surfaced, no silent fall-through:

   - **`CLAIM_RC == 0`** (acquired, self-reentry, or `Z_HARNESS_CLAIM_DISABLE=1`) → proceed normally.

   - **`CLAIM_RC == 1`** (live peer holds the slug) → show the holder details from `$CLAIM_OUTPUT` (session / run / command / heartbeat age).
     - **Interactive** (not `Z_HARNESS_NO_ASK`): `AskUserQuestion` — **proceed anyway / abort / use a new slug**.
       - `proceed anyway` → continue (uncoordinated; log a `plan_claim_override` event).
       - `abort` → exit 1. (No release — we never held the lock.)
       - `use a new slug` → re-derive a slug and re-run the acquire **once** (loop-guard: at most 1 re-derive prompt; if the new slug also contends, abort). After a successful re-derive: re-export `Z_HARNESS_SLUG`, `Z_HARNESS_PLAN_DIR`, `RUN`, and `CURRENT_ARCHIVE_DIR` for all subsequent calls; re-persist `$Z_HARNESS_SESSION_ID` to the new archive path; re-run claim acquire with the new slug (same `CLAIM_RC` + `CLAIM_OUTPUT` pattern); branch on the new `CLAIM_RC` normally (no further re-derive).
     - **Unattended** (`Z_HARNESS_NO_ASK`): abort (`exit 1`) unless `Z_HARNESS_CLAIM_OVERRIDE=1` → proceed anyway (log override). (No release — we never held the lock.)

   - **`CLAIM_RC == 2`** (stale-takeover — **we now hold the lock**) → show prior holder + idle age from `$CLAIM_OUTPUT`.
     - **Interactive**: `AskUserQuestion` — **proceed / abort** (default: **ABORT** — a partial SPEC/PLAN may exist from the prior holder).
       - `proceed` → continue.
       - `abort` → **call `plan-claim.sh release` first** (we hold the lock), then `exit 1`.
     - **Unattended**: abort (release first, then `exit 1`) unless `Z_HARNESS_CLAIM_OVERRIDE=1` → proceed anyway.
     ```bash
     # On abort at CLAIM_RC==2 (we hold the lock — must release):
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
       --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
       --command /z-plan || true
     ```

   - **`CLAIM_RC == 3`** (corrupt / invalid args — **we do NOT hold the lock**) → emit a loud error; show manual-cleanup hint (`rm <claims_dir>/<slug>.lock*` then retry).
     - **Interactive**: `AskUserQuestion` — **abort (default)** / **proceed UNCOORDINATED** (clearly labeled: you and a peer may clobber each other's artifacts).
       - `abort` → exit 1. (No release — we never held the lock.)
       - `proceed UNCOORDINATED` → continue (log a `plan_claim_corrupt_proceed` event).
     - **Unattended**: abort (`exit 1`) unless `Z_HARNESS_CLAIM_OVERRIDE=1` → proceed uncoordinated. (No release either way.)

   **CLAIM_HELD flag.** The orchestrator MUST set `CLAIM_HELD` to exactly `1` or `0` immediately after the acquire branch resolves. All downstream heartbeat guards and release guards evaluate `${CLAIM_HELD:-0}`; if `CLAIM_HELD` is never set, every guard silently evaluates to false, the lock leaks, and heartbeats never fire. This assignment is not optional.

   | Outcome | CLAIM_HELD |
   |---------|-----------|
   | `CLAIM_RC==0`, output is `acquired` or `self-reentry` | `1` — we hold the lock |
   | `CLAIM_RC==0`, output is `disabled` (`Z_HARNESS_CLAIM_DISABLE=1`) | `0` — no lock |
   | `CLAIM_RC==2`, user chose **proceed** (stale-takeover accepted) | `1` — we hold the lock |
   | `CLAIM_RC==2`, user chose **abort** (we released above) | `0` — lock released |
   | `CLAIM_RC==1` or `CLAIM_RC==3` (never acquired) | `0` — never held |

   ```bash
   # DEFINITIVE CLAIM_HELD assignment — orchestrator must execute this after the branch above.
   # Every downstream heartbeat and release guard depends on this value being set correctly.
   if [[ "$CLAIM_RC" -eq 0 && "$CLAIM_OUTPUT" != "disabled" ]] || \
      [[ "$CLAIM_RC" -eq 2 && "$_CLAIM_USER_CHOICE" == "proceed" ]]; then
     CLAIM_HELD=1
   else
     CLAIM_HELD=0
   fi
   ```

   (`$_CLAIM_USER_CHOICE` is the local variable set to `"proceed"` or `"abort"` in the CLAIM_RC==2 branch above — replace with however the orchestrator captured the user's answer.)

   **Run Brief init (after claim acquire, before register).** Create `run-brief.json` for this run (registry profile `full`):
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh" init \
     --run "$RUN" --command /z-plan --slug "$Z_HARNESS_SLUG" --profile full \
     --intent "<task description from $ARGUMENTS — max 240 chars; not the command name alone>"
   ```

   **Active-plan registration (after claim acquire).** Register this run in the shared registry. Graduated failure policy — never silent-continue on failure:
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
     --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --phase plan \
     --session "$Z_HARNESS_SESSION_ID"
   REG_RC=$?
   ```
   - `REG_RC == 0` → registered; proceed.
   - `REG_RC == 3` (register FAILED — no record was written) → emit a loud `registry_error` event, then branch:
     - **Interactive** (not `Z_HARNESS_NO_ASK`) → `AskUserQuestion`: *proceed without coordination* / *abort*.
       - **proceed** → continue; skip heartbeats and deregister later (no record to update). The claim is still held.
       - **abort** → **release the claim first** (we hold it — register failed AFTER a successful acquire), do **NOT** call deregister (no record exists), push-notify, then `exit 1`:
         ```bash
         if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
           bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
             --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
             --command /z-plan || true
         fi
         exit 1
         ```
     - **Unattended (`Z_HARNESS_NO_ASK`)** → proceed without coordination and log prominently, UNLESS `Z_HARNESS_STRICT_OVERLAP=1` → **release the claim** (same snippet as above) and halt (`exit 1`). No deregister either way (no record).
   - **Any OTHER nonzero** → treat as `REG_RC == 3`.
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
     "$(printf '{"op":"register","run_id":"%s","rc":%d}' "$RUN" "$REG_RC")"
   ```

   **FINALIZE_STATUS / deregister rule (single source of truth for the entire run):**
   > On any run-ending halt that occurs AFTER `REG_RC == 0` (a record exists), execute **Run Brief — halt finalize** (below) before `deregister --status aborted`. On normal completion (Phase 9), leave `FINALIZE_STATUS` unset so Phase 9 deregisters with `complete`. If register failed (no record), do NOT deregister anywhere.

   **Kernel path resolution (once per run, immediately after run_start):**
   ```bash
   KERNEL_PATH="$(bash scripts/resolve-kernel.sh 2>/dev/null || true)"
   ```
   <!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->

6. **Plan-start awareness read (after claim + register; non-fatal read-only).** After a successful claim and register, read the lockless registry to surface concurrent peers as an FYI — never a hard gate (Invariant 1):
   ```bash
   AWARENESS_JSON="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" list --json 2>/dev/null)"
   AWARENESS_RC=$?
   if [[ "$AWARENESS_RC" -ne 0 ]]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" registry_error \
       "$(printf '{"op":"awareness_read_failed","rc":%d}' "$AWARENESS_RC")"
   else
     # Render any record whose session_id != $Z_HARNESS_SESSION_ID as a one-line advisory.
     # Example: "Other active sessions: 20240101T120000Z-other-slug — /z-plan on other-slug (heartbeat 5s)"
     # This is purely informational — never blocks or gates a subsequent phase.
     echo "$AWARENESS_JSON" | python3 -c "
import json, sys, os
records = json.load(sys.stdin)
my_sid = os.environ.get('Z_HARNESS_SESSION_ID', '')
peers = [r for r in records if r.get('session_id') != my_sid]
if peers:
    print('Other active sessions:')
    for p in peers:
        hb = p.get('last_heartbeat', '')
        print(f\"  {p.get('run_id','?')} — {p.get('command','?')} on {p.get('slug','?')} (heartbeat {hb})\")
" 2>/dev/null || true
   fi
   ```
7. Notification policy is resolved from config via the `export-env` step above. See `docs/human/config.md` for knob details (`notify.level`).
8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
9. **Docs-freshness scan (inline, no gate yet).** Initialize signals before scanning: `docs_stale=false`, `research_stale=false`, `map_stale=false`; `stale_concepts_list=[]`; `stale_research_citations=[]`; `stale_map_citations=[]`. If `docs/llm/INDEX.json` exists, compute staleness across all its entries. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). Record signal: `docs_stale = (stale_pct >= threshold)`. Also record `stale_concepts_list` (list of stale concept slugs) for display. **Do not present any AskUserQuestion here** — the gate fires below in step 10c after all three signals are collected.
10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `MAP.md`, `BRAINSTORM.md`, `RESEARCH.md`, and `GRILL.md`.

    **RESEARCH.md artifact_kind dispatch:** If `RESEARCH.md` exists, read its frontmatter `artifact_kind` and `status` fields first to determine the precontext mode:

    - **`artifact_kind: approach_synthesis` + `status: complete`** → **one-way gate active.** RESEARCH.md is canonical precontext. Skip MAP.md + BRAINSTORM.md injection entirely. Phase 1 uses matrix-based skip rules.
    - **`artifact_kind: map`** (legacy old-RESEARCH.md not yet renamed) → treat as a MAP.md artifact: apply freshness check (same regex/mtime logic as MAP.md below), then proceed with component-file injection (MAP.md + BRAINSTORM.md mode). Log `legacy_map_artifact_detected`.
    - **No `artifact_kind` field** → treat as legacy MAP.md artifact per above. Log `legacy_map_artifact_detected`.
    - **`status: incomplete`** → halt. Emit `precontext_research_incomplete`. Recommend re-running `/z-research` before proceeding. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `RESEARCH.md status incomplete`.

    **Freshness scan — RESEARCH.md (inline, no gate yet)** (when one-way gate is active): parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). Record signal: `research_stale = true` if any citation is stale. Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) and set `research_stale = true`. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open). **Do not present any AskUserQuestion here** — the gate fires below in step 10c.

    **Freshness scan — MAP.md (inline, no gate yet)** (when one-way gate is inactive and MAP.md exists or RESEARCH.md is treated as MAP.md): parse all file citations using the same regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/` and extensionless allowlist (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to the MAP.md frontmatter `generated_at`; for line-ranges, use min-line mtime. Record signal: `map_stale = true` if any citation is stale. Deleted-source detection: emit `precontext_source_deleted` and set `map_stale = true`. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open). **Do not present any AskUserQuestion here** — the gate fires below in step 10c.

    **GRILL.md detection** (independent of one-way gate): If `$Z_HARNESS_PLAN_DIR/GRILL.md` exists and its frontmatter `status` is `complete`, note it as a GRILL.md precontext artifact. Read its `## Sharpened problem`, `## Killed scope`, and `## Open branches` sections for injection in Phase 0 and Phase 2. GRILL.md is a problem-statement artifact, not a code-citation artifact — **no mandatory freshness gate applies.** Exception: if GRILL.md contains file citations (matched by the same regex), apply the same freshness scan as MAP.md (mtime vs GRILL.md frontmatter `generated_at`) and fold any stale signal into `map_stale` for the 10c gate. If `status` is not `complete`, skip GRILL.md silently (treat as absent).

    **10c. Consolidated freshness gate.** After all four scans complete (docs, RESEARCH.md, MAP.md, GRILL.md citations if present), if `docs_stale OR research_stale OR map_stale` is true:

    Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`. Build up `reason_codes` from all true signals (e.g. `["docs_stale"]`, `["research_stale"]`, `["map_stale"]`, or a combination). Set `to_command` to the most specific single remedy (prefer `"/z-maintain-docs"` if docs_stale, `"/z-research"` if only research_stale, `"/z-map"` if only map_stale; if multiple signals fire, use `"/z-maintain-docs"` and list all remedies in the route-decision.md body).

    Push-notify (guarded by notify level), then present **ONE** `AskUserQuestion` with:

    - **Header:** "One or more planning inputs are stale. Review and choose how to proceed:"
    - **Per-source bullets** for each true signal (include only bullets for signals that fired):
      - `docs`: "Docs are stale — `stale_pct`% of concepts outdated (affects: `stale_concepts_list`). Remedy: `/z-maintain-docs`."
      - `research`: "RESEARCH.md has stale or deleted citations. Remedy: `/z-research`."
      - `map`: "MAP.md has stale or deleted citations. Remedy: `/z-map`."
    - **Options** (include only per-source remedy options that correspond to true signals, always include the last two):
      - `re-run /z-maintain-docs` (if `docs_stale`)
      - `re-run /z-research` (if `research_stale`)
      - `re-run /z-map` (if `map_stale`)
      - `proceed with all stale — I accept the risk`
      - `abandon`

    On user choice:

    - **Re-run remedy**: Emit `plan_route_decision` with the chosen remedy as `to_command`. Halt. Do not auto-invoke the remedy command. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `stale inputs — user chose remedy re-run`.
    - **Proceed with all stale**: Emit `plan_route_decision` with `to_command: null`. If `docs_stale=true`: emit `doc_drift_acknowledged`. If `research_stale=true OR map_stale=true`: emit `precontext_freshness_acknowledged`. Continue to Phase 1.
    - **Abandon**: Emit `plan_route_decision` with `to_command: null` and `user_choice: "abandon"`. Halt. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `stale inputs — user abandoned`.

    If **no** signal fired, skip the gate entirely — no AskUserQuestion, no route-decision.md write.

    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist (in component-file mode, i.e. one-way gate inactive), scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research/Map found constraint Y that prevents it). Surface contradictions to the user.
    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/SPEC.md`
- `$Z_HARNESS_PLAN_DIR/PLAN.md`
- `$Z_HARNESS_PLAN_DIR/TASKS.md`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.

Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `plan_validation_intent`, `plan_amend_intent`, `has_fix_artifact`, and `docs_stale_or_drifted`. Set `plan_validation_intent`/`plan_amend_intent` only when the user re-enters this command on a slug with `SPEC.md`+`PLAN.md`+`TASKS.md` all present (see `agents/planning-router.md` for the language-match heuristic).

Deterministic routes:
- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.

When the user chooses **switch** or **abandon** at the route gate (ending the run), per the FINALIZE_STATUS rule execute **Run Brief — halt finalize** (below) with reason `route gate — user chose switch or abandon`.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 9), stamp the start time to disk and fire a claim heartbeat:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" begin "$RUN" <phase-num>
# Claim heartbeat at phase boundary (guard: only when CLAIM_HELD==1)
if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
  _HB_RC=0
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-plan || _HB_RC=$?
  if [[ "$_HB_RC" -eq 9 ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
      "$(printf '{"slug":"%s","run_id":"%s","phase":"begin-%d"}' "$Z_HARNESS_SLUG" "$RUN" <phase-num>)"
    # URGENT: slug was taken over by another session while this run was active.
    AskUserQuestion "URGENT: The claim on slug '$Z_HARNESS_SLUG' was lost (taken over by another session or freed). \
This run may collide with a peer. Default: abort." \
      ["Abort (safe default)", "Continue uncoordinated (you accept collision risk)"]
    # On abort → CLAIM_HELD=0; if register succeeded → FINALIZE_STATUS=aborted + deregister; exit 1.
    # On continue-uncoordinated → CLAIM_HELD=0 (lock already gone); log plan_claim_override; proceed.
  fi
  # heartbeat_error (exit 0) is a transient read failure — NOT a lost claim; log-event already emitted
  # by plan-claim.sh; no gate fires.
fi
```

At the **end**, emit `phase_end` — `log-phase.sh finish` reads the stamped start time back, computes `wall_ms`, and logs it:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" finish "$RUN" <phase-num> \
  "$(printf '{"phase":%d,"name":"%s","user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$USER_WAIT_MS_THIS_PHASE")"
```

> **Why disk, not a shell variable:** each `Bash` tool call runs in a fresh shell, so a `T0=$(date +%s%3N)` recorded at phase start is gone by the phase-end call in a later turn — `WALL_MS` then resolves against an empty `T0` and logs `wall_ms: 0`. `log-phase.sh begin/finish` persists the start stamp under `${TMPDIR:-/tmp}/z-harness-phase/`, keyed by run+phase, so timing survives across tool-call boundaries. `finish` fail-opens (emits nothing) if `begin` was skipped, rather than logging a bogus zero.

If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact. **Immediately before the `user_wait_start` log, fire a claim heartbeat** — this is the load-bearing call that extends the TTL to survive the upcoming human wait:

```bash
# Load-bearing heartbeat BEFORE every user wait (extends TTL to survive the wait).
if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
  _HB_RC=0
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-plan || _HB_RC=$?
  if [[ "$_HB_RC" -eq 9 ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_claim_lost_during_gate \
      "$(printf '{"slug":"%s","run_id":"%s","phase":"pre-gate-%d"}' "$Z_HARNESS_SLUG" "$RUN" <phase-num>)"
    AskUserQuestion "URGENT: The claim on slug '$Z_HARNESS_SLUG' was lost before this gate. \
Another session may now be planning the same slug. Default: abort." \
      ["Abort (safe default)", "Continue uncoordinated (you accept collision risk)"]
    # On abort → FINALIZE_STATUS=aborted + deregister; CLAIM_HELD=0; exit 1.
    # On continue-uncoordinated → CLAIM_HELD=0; log plan_claim_override; proceed to gate.
  fi
  # heartbeat_error (exit 0): plan-claim.sh already emitted heartbeat_error event; proceed normally.
fi
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

The AFTER-gate heartbeat (`user_wait_end` bracket) is **optional** — skip it when the next phase's begin-heartbeat is imminent (it would otherwise duplicate the TTL refresh).

This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.

---

## Phase 0 — Premise check

**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.

Before any planning, ask:

- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
- Is there a materially better path the user hasn't considered?

If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.

If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.

Checkpoint: `phase0-premise.md`.

## Phase 1 — Exploration

**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:

- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.

The four resulting cases:
- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
- **(c) Skip both** — RESEARCH.md has findings for touched files AND no open questions → skip both, proceed to Phase 2.
- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.

**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.

### 1a. Dispatch doc-fetcher (if INDEX.json exists)

If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:

```
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
  subagent_type="doc-fetcher",
  description="Doc context for <slug>",
  prompt="query: <one-sentence summary of the task>\nrepo_root: <abs path>\ndepth: standard"
)
```

It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed to Explore with no grounding. If it returns `STATUS: partial`, Explore must fill the gap it named.

If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
```

### 1b. Explore for gaps (Haiku by default)

Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.

**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:

```
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
  subagent_type="Explore",
  model: "haiku",
  description="Find <thing> related to <slug>",
  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
)
```

**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.

**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore (even Haiku) is a repo-mapping pass that consumes meaningful cache-read context. In the data-overhaul run, 5 Opus Explores ate 13.9 M tokens — ~93% of the entire planning budget. Haiku materially cuts that, but the cap stays: if 3 is not enough, prefer direct Read/Grep/Glob from the orchestrator over a 4th Explore. Override via `Z_HARNESS_MAX_EXPLORE=N` only with explicit user request.

Output a one-paragraph context summary. Checkpoint: `phase1-context.md`.

## Phase 2 — Decisions document

Enumerate **every** decision needed to implement this task — obvious and non-obvious. Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/decisions.md`. For each decision:

- **Decision:** what's being decided
- **Options:** ≥1 candidate, with one-line tradeoffs
- **Tentative call:** your current pick
- **Consult? (yes/no):** apply the rules below
- **Trigger:** which rule made it consult-worthy (if yes)

### Consultation rules

A decision is **non-obvious (consult)** if *any* applies:

- Introduces a new external dependency
- Defines or changes a public API / module boundary / wire format
- Picks an algorithm or data structure where Big-O or memory differ between candidates
- Touches concurrency, shared state, or ordering guarantees
- Touches persistence: schema, migration, indexes, retention
- Names something on a public surface (hard to rename later)
- Affects >1 module or crosses a layer boundary
- **Reversibility:** if wrong, >1 hour to undo
- **Articulation:** you can name ≥2 candidate options with materially different tradeoffs

A decision is **obvious (skip consult)** if:
- Following an existing convention in the same file/module
- Local variable naming, internal helper structure
- Mechanical refactor with no behavior change
- Bug fix with root cause already identified

## Phase 2.5 — User gate

Show `decisions.md` to the user. They are the gate:
- Can flip any decision's consult flag
- Can override your tentative call
- Can kill scope

**Hard cap: 5 consult-flagged decisions per bundle.** If more, ask the user to pick the top 5 or split the plan into multiple `/z-plan` runs.

Block here until the user has approved the decisions doc.
```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && <PushNotification: decisions ready for approval>
```

## Phase 3 — Bundled cross-LLM consultation

Read config knobs:

```bash
PERSONA_ROTATION="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get experiment.persona_rotation 2>/dev/null || echo "true")"
CRITIQUE_PANEL="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get personas.critique_panel 2>/dev/null || echo "true")"
```

If `PERSONA_ROTATION == "true"`, use the **fixed 5-member panel** (agy, cursor@claude-4.6-sonnet, cursor@grok-4.3, cursor@composer-2.5, codex-cli). When `CRITIQUE_PANEL == "true"` as well, draw 5 distinct `consultant` personas and positionally prepend one body to each arm's prompt (graceful underflow — fewer personas than arms is fine, remaining arms run vanilla). This draw is Phase 3-specific; Phase 7 gets its own independent draw.

```bash
PLUGIN="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"
P3_GEMINI_PREFIX=""; P3_SONNET_PREFIX=""; P3_GROK_PREFIX=""; P3_COMPOSER_PREFIX=""; P3_CODEX_PREFIX=""
P3_GEMINI_NAME="<none>"; P3_SONNET_NAME="<none>"; P3_GROK_NAME="<none>"; P3_COMPOSER_NAME="<none>"; P3_CODEX_NAME="<none>"
P3_GEMINI_DRAW=""; P3_SONNET_DRAW=""; P3_GROK_DRAW=""; P3_COMPOSER_DRAW=""; P3_CODEX_DRAW=""

if [ "$PERSONA_ROTATION" = "true" ] && [ "$CRITIQUE_PANEL" = "true" ]; then
  P3_PERSONAS_JSON=$(python3 "$PLUGIN/scripts/resolve-persona.py" random-distinct-for-role consultant --count=5 \
    2>>"$Z_HARNESS_PLAN_DIR/archive/$RUN/persona-draw.log")
  for slot in 0:GEMINI 1:SONNET 2:GROK 3:COMPOSER 4:CODEX; do
    idx="${slot%%:*}"; who="${slot##*:}"
    name=$(echo "$P3_PERSONAS_JSON" | jq -r ".[$idx].persona // \"\"")
    path=$(echo "$P3_PERSONAS_JSON" | jq -r ".[$idx].persona_body_path // \"\"")
    draw=$(echo "$P3_PERSONAS_JSON" | jq -r ".[$idx].draw_id // \"\"")
    [ -z "$name" ] && continue
    prefix=$(python3 "$PLUGIN/runtime/dispatch/persona_prompt.py" "$path" "" 2>/dev/null | head -c 4096)
    eval "P3_${who}_NAME=\$name"; eval "P3_${who}_PREFIX=\$prefix"; eval "P3_${who}_DRAW=\$draw"
  done
fi
```

Emit `persona_bound` per arm before dispatch. Arms with a drawn persona use `selection_source=random_role_pool_distinct` and include `persona_id` + `draw_id`; vanilla arms use `selection_source=fixed_panel`:

```bash
declare -A P3_ARM_NAMES=([gemini]="$P3_GEMINI_NAME" [claude-sonnet]="$P3_SONNET_NAME" [grok]="$P3_GROK_NAME" [composer]="$P3_COMPOSER_NAME" [codex-5.5]="$P3_CODEX_NAME")
declare -A P3_ARM_DRAWS=([gemini]="$P3_GEMINI_DRAW" [claude-sonnet]="$P3_SONNET_DRAW" [grok]="$P3_GROK_DRAW" [composer]="$P3_COMPOSER_DRAW" [codex-5.5]="$P3_CODEX_DRAW")
for ARM in gemini claude-sonnet grok composer codex-5.5; do
  pname="${P3_ARM_NAMES[$ARM]}"; pdraw="${P3_ARM_DRAWS[$ARM]}"
  if [ "$pname" != "<none>" ] && [ -n "$pname" ]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" persona_bound \
      "$(printf '{"run_id":"%s","command":"z-plan","role":"consultant","arm":"%s","selection_source":"random_role_pool_distinct","persona_id":"%s","draw_id":"%s","phase":3}' "$RUN" "$ARM" "$pname" "$pdraw")"
  else
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" persona_bound \
      "$(printf '{"run_id":"%s","command":"z-plan","role":"consultant","arm":"%s","selection_source":"fixed_panel","phase":3}' "$RUN" "$ARM")"
  fi
done
```

Spawn all 5 panel members in parallel in a single message. Each receives the **entire approved decisions doc** with the consult-flagged decisions highlighted. Prepend the arm's persona body to its prompt when available (empty string = vanilla, byte-identical to pre-feature dispatch). Cursor arms pass their model via `--model <model>`:

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->

If `PERSONA_ROTATION == "false"`, fall back to the standard 2-consultant behavior:

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->

Each gets the **entire approved decisions doc** with the consult-flagged decisions highlighted. Two calls total, regardless of feature size.

When all consultants return (from either path):
1. For each recommendation, articulate **one concrete reason it might be wrong** before accepting it. This is mechanical, not optional.
2. Synthesize. Make the final call yourself, citing which inputs you weighed.
3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.

Save transcripts (the consultants do this themselves). Checkpoint: `phase3-decisions-final.md`.

## Phase 4 — Final clarifications

If anything is still unclear about scope, constraints, or success criteria — ask the user. No silent assumptions.

## Phase 5 — Present + approve

```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && <PushNotification: "Decisions ready for review.">
```

Present a **concise** decisions summary: one bullet per decision (what, why, what was rejected). Separate **Shortcuts** section: what's being skipped, robust alternative, cost of the shortcut.

Use `AskUserQuestion` for explicit approval on:
- Each major design decision
- Each proposed shortcut (default to robust if not approved)

Block until answered.

## Phase 6 — Write SPEC.md and PLAN.md

Create `$Z_HARNESS_PLAN_DIR/SPEC.md` — per-file detailed spec: paths, exported surface, signatures, behavior, invariants, edge cases, error handling.

The SPEC.md must include a `## Planning Inputs` section near the top (after title/overview, before any per-file sections) listing which precontext artifacts contributed to this plan:

```markdown
## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | $Z_HARNESS_PLAN_DIR/BRAINSTORM.md | <iso timestamp or "n/a"> |
| RESEARCH.md | $Z_HARNESS_PLAN_DIR/RESEARCH.md | <iso timestamp or "n/a"> |
```

If neither artifact was present, write: `none — fresh /z-plan run.`

Create `$Z_HARNESS_PLAN_DIR/PLAN.md` — approved plan: goals, decisions (with rationale), non-goals, approved shortcuts, ordered phases.

Both obey **DRY / KISS / SOLID**. State explicitly how the plan respects each.

## Phase 7 — Bundled final review

Reuse `PERSONA_ROTATION` and `CRITIQUE_PANEL` values from Phase 3. If `PERSONA_ROTATION == "true"`, use the same **fixed 5-member panel** for Phase 7. Draw a fresh, independent set of 5 distinct `consultant` personas — do NOT reuse the Phase 3 draw.

```bash
PLUGIN="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"
P7_GEMINI_PREFIX=""; P7_SONNET_PREFIX=""; P7_GROK_PREFIX=""; P7_COMPOSER_PREFIX=""; P7_CODEX_PREFIX=""
P7_GEMINI_NAME="<none>"; P7_SONNET_NAME="<none>"; P7_GROK_NAME="<none>"; P7_COMPOSER_NAME="<none>"; P7_CODEX_NAME="<none>"
P7_GEMINI_DRAW=""; P7_SONNET_DRAW=""; P7_GROK_DRAW=""; P7_COMPOSER_DRAW=""; P7_CODEX_DRAW=""

if [ "$PERSONA_ROTATION" = "true" ] && [ "$CRITIQUE_PANEL" = "true" ]; then
  P7_PERSONAS_JSON=$(python3 "$PLUGIN/scripts/resolve-persona.py" random-distinct-for-role consultant --count=5 \
    2>>"$Z_HARNESS_PLAN_DIR/archive/$RUN/persona-draw.log")
  for slot in 0:GEMINI 1:SONNET 2:GROK 3:COMPOSER 4:CODEX; do
    idx="${slot%%:*}"; who="${slot##*:}"
    name=$(echo "$P7_PERSONAS_JSON" | jq -r ".[$idx].persona // \"\"")
    path=$(echo "$P7_PERSONAS_JSON" | jq -r ".[$idx].persona_body_path // \"\"")
    draw=$(echo "$P7_PERSONAS_JSON" | jq -r ".[$idx].draw_id // \"\"")
    [ -z "$name" ] && continue
    prefix=$(python3 "$PLUGIN/runtime/dispatch/persona_prompt.py" "$path" "" 2>/dev/null | head -c 4096)
    eval "P7_${who}_NAME=\$name"; eval "P7_${who}_PREFIX=\$prefix"; eval "P7_${who}_DRAW=\$draw"
  done
fi
```

Emit `persona_bound` per arm (same pattern as Phase 3, with `"phase":7`):

```bash
declare -A P7_ARM_NAMES=([gemini]="$P7_GEMINI_NAME" [claude-sonnet]="$P7_SONNET_NAME" [grok]="$P7_GROK_NAME" [composer]="$P7_COMPOSER_NAME" [codex-5.5]="$P7_CODEX_NAME")
declare -A P7_ARM_DRAWS=([gemini]="$P7_GEMINI_DRAW" [claude-sonnet]="$P7_SONNET_DRAW" [grok]="$P7_GROK_DRAW" [composer]="$P7_COMPOSER_DRAW" [codex-5.5]="$P7_CODEX_DRAW")
for ARM in gemini claude-sonnet grok composer codex-5.5; do
  pname="${P7_ARM_NAMES[$ARM]}"; pdraw="${P7_ARM_DRAWS[$ARM]}"
  if [ "$pname" != "<none>" ] && [ -n "$pname" ]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" persona_bound \
      "$(printf '{"run_id":"%s","command":"z-plan","role":"consultant","arm":"%s","selection_source":"random_role_pool_distinct","persona_id":"%s","draw_id":"%s","phase":7}' "$RUN" "$ARM" "$pname" "$pdraw")"
  else
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" persona_bound \
      "$(printf '{"run_id":"%s","command":"z-plan","role":"consultant","arm":"%s","selection_source":"fixed_panel","phase":7}' "$RUN" "$ARM")"
  fi
done
```

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->

If `PERSONA_ROTATION == "false"`, fall back to the standard 2-consultant behavior: spawn both consultants in parallel, each handed the full SPEC.md + PLAN.md. Include `kernel_path: <KERNEL_PATH>` when non-empty:
- consultant-primary: "Critique this plan. What's wrong, missing, or fragile?"
- consultant-secondary: same.

Apply findings that hold up under "one reason this might be wrong" scrutiny. Push back on the rest with documented reasoning.

## Phase 8 — TASKS.md

Create `$Z_HARNESS_PLAN_DIR/TASKS.md`. Break PLAN.md into small, independently-implementable tasks. Each: `T001`-style ID, title, files touched, dependencies, acceptance criteria, status `[ ]`. Size so each fits a fresh context window.

**Task-count discipline.** Target **10–20 tasks**. If you produced **>25** tasks, stop and ask the user via `AskUserQuestion`:
- "Combine 2-3 tasks I'll suggest" (you propose candidate merges)
- "Ship as-is — this plan really is that big"
- "Restructure — let me redesign Phase 8"

Sweet spot: each task fits one fresh context window AND produces ~50–500 lines of diff. Too many micro-tasks = orchestration overhead dominates; too few mega-tasks = bad failure isolation.

**Remote-verify tags.** For any task that touches Rust crates or Python scripts intended for the remote host, append a `**REMOTE_VERIFY:** <cargo command>` line to the task block. Example:
```
**REMOTE_VERIFY:** cargo check -p strategies-sports-ml-mispricing
```
The orchestrator dispatches a `remote-runner` (Haiku) to rsync+build in the sandbox; failure halts the task before review.

**Docs-touched flag.** For any task that touches a user-facing surface (CLI flags, public APIs, configs, schemas), append a `**DOCS:** <concept-slug>` line. This is a hint for `/z-maintain-docs`; not a rigid task on its own.

<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" task_classified \
  "$(printf '{"task":"%s","tier":"%s","reason":%s}' "<task-id>" "<tier>" "$(printf '%s' "<reason>" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
```
If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).

**Scope seed (immediately after TASKS.md + complexity stamps are finalized).** Dispatch the `scope-extractor` (Haiku) subagent to seed the plan's file scope into the registry so a concurrent `/z-implement-all` can see what this plan intends. Best-effort, non-fatal — `update-scope` self-logs `registry_error` on failure:

```
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
  subagent_type="scope-extractor",
  description="Scope for /z-plan overlap seed",
  prompt="repo_root: <abs path to repo root>\nbase: $Z_HARNESS_PLAN_DIR"
)
```

Write the returned JSON array to a temp file, then:
```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" update-scope \
  --run-id "$RUN" --scope-json "$SCOPE_JSON" || true   # CLI self-logs registry_error on failure
```

**Heartbeat (Phase 8 boundary).** Best-effort, non-fatal:
```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" heartbeat \
  --run-id "$RUN" --phase phase8 || true   # CLI self-logs registry_error on failure
```

## Phase 9 — Finalize archive

Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).

Log run end. Send a PushNotification (guarded by notify level) with FOUR recommendations:
```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ] && <PushNotification: plan complete message below>
```
```
Plan complete. <N> tasks queued.

Recommended:
  /compact             — free planning context before next phase
  /z-audit-plan        — (recommended) audit spec & tasks against codebase reality and best practices
  /z-audit-plan-style  — (recommended) MR-style code-quality audit of the plan: defensive bloat, premature abstraction, DRY/KISS/SOLID, STYLE.md drift
  /z-test              — (optional, recommended for risky / financial code) draft semantic test cases before implementation
  /z-implement-all     — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
```

Then surface the same choice interactively via `AskUserQuestion` so users who don't read OS notifications still see it. Phrase the question as "Plan complete. What's next?" with these four options (the `AskUserQuestion` four-option cap is why the two plan audits share one option — the push-notification above still lists them separately): `/z-audit-plan` (label: `Audit the plan (recommended)` — recommended cheap pre-implementation reality check against the codebase; the description also points the user at `/z-audit-plan-style` for the companion MR-style quality pass on the plan artifacts), `/z-test` (label: `Draft semantic test cases` — recommended only for risky/financial code), `/z-implement-all` (label: `Start implementation now` — only when user has high confidence in the plan), `Skip — I'll decide later`. Default selection is `/z-audit-plan`. The user's choice is advisory — log it as a `next_step_choice` event but do not auto-dispatch the chosen command; the user invokes it themselves so they retain control of context boundaries (e.g. running `/compact` between phases).

**Release the claim and deregister this run** (best-effort, non-fatal). Release BEFORE deregister so the lock frees first (minimizes the window where the registry shows the run gone but the lock is still held). Per the FINALIZE_STATUS rule (Setup step 5): normal completion deregisters with `complete`. Both calls return 0 by design and self-log on internal failure, so call both with `|| true`. If register failed earlier (no record was ever written), the deregister is a harmless no-op.
```bash
# Release BEFORE deregister (invariant 3 — order matters).
if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-plan || true
fi
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status "${FINALIZE_STATUS:-complete}" || true   # CLI self-logs registry_error on failure
```

The `/compact` recommendation is important: the planning phase (Explore agents, decisions doc, consultant returns, SPEC/PLAN drafting) is the heaviest context burner in the harness. Compacting at this boundary frees ~MB of main-thread context before implementation kicks off. Subagents during implementation are fresh-context already, so no per-batch compact is needed.

The `/z-test` step is optional but high-value when the plan touches money, ordering, signal generation, or any other domain where mechanical correctness (which `/z-implement-all`'s reviewer catches) is not enough to catch semantic bugs (notional sign flips, feature schema mismatches, unit confusion). It produces a `TESTS.md` artifact that `/z-implement-all`'s implementer subagent reads alongside TASKS.md, so test code lands in the same diff as the production code it exercises.

## Run Brief — halt finalize

Before `deregister --status aborted` on any halt after `run-brief.sh init` (unless register failed — no deregister). Substitute `<reason>` in the outcome line. When no planning artifact exists yet, the shared fragment auto-downgrades to **lite** (Intent + Outcome + Next).

**Known gap:** halts before Setup step 5 (`run-brief.sh init`) — e.g. a resolver `halt` during slug derivation — skip this block (no brief JSON yet).

```bash
export RUN_BRIEF_PROFILE=full
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-PLAN.md:SPEC.md}"
RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: <reason>"
bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Review plan status and retry or escalate", "command": null}
JSON
```

```bash
FINALIZE_STATUS=aborted
# Release BEFORE deregister (invariant 3). Guard: only when CLAIM_HELD==1 (i.e. we actually hold the lock).
if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
    --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
    --command /z-plan || true
fi
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status aborted 2>/dev/null || true
```

---

## Decision emission (standing instruction)

After **any** `AskUserQuestion` resolves, emit a normalized decision event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-decision.sh" \
  "$RUN" "<question_id>" "<chosen_label>" \
  --options '["<opt1>","<opt2>",...]' \
  [--tentative "<recommended_option>"]
```

- `<question_id>` — stable kebab-case identifier for this decision point (e.g. `workflow.implement_all_proceed`, `workflow.slug_confirm`).
- `<chosen_label>` — the option label the user selected, verbatim.
- `--options` — full list of offered option labels as a JSON array.
- `--tentative` — the orchestrator's recommended option label; omit when the orchestrator had no recommendation.

Emission is gated by `Z_HARNESS_AXIOM_EXTRACT` (default on); when set to `"0"`, the script exits silently — no guard is needed here. Do **not** modify existing structured gate events (`cost_gate_decision`, `critique_failure_decision`, `map_collision_decision`, `shared_concerns_ack_override`); those are normalized separately by the extractor. This emission **records signal only** — it never approves, overrides, or influences any decision (proposes-only invariant).

## Operating principles

- **Premise first.** Challenge the request before planning around it.
- **Push back is structural** — every accepted recommendation needs an articulated "reason it might be wrong" before you accept it.
- **Always ask** when unclear.
- **Shortcuts only with explicit approval.**
- **DRY / KISS / SOLID** are non-negotiable.
- **Log everything.** Every consultation, approval, pushback, error — via `scripts/log-event.sh`.
