---
name: z-plan
disable-model-invocation: false
description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce INTENT.md + initial TASKS.md (or SPEC.md / PLAN.md / TASKS.md in --full legacy mode).
argument-hint: <feature or task description>
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running the **z-harness `/z-plan`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What task should I plan?" to the user via their native channel and accept
     a text reply. Silent omission is forbidden. -->
**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-execute`.

## Revised phase spine and `/z-plan` edit sequence

The `/z-plan` spine is ordered so every expensive action is gated, every artifact handoff is explicit, and later redesign tasks have stable insertion points:

1. **Setup** — slug/collision checks, claim/register, docs/precontext freshness, deterministic artifact inventory.
2. **Plan Route Check (pre-gate)** — route-down/lateral recommendations from cheap signals only; do not auto-dispatch another command.
3. **Explicit planning mode gate** — visible Intent-vs-Full SDD choice, with config/flags as the recommended default and `SPEC.md` as the legacy full-mode override.
4. **Pre-subagent cost gate (hard)** — runs after the mode gate has fixed the cost shape and before any expensive Agent dispatch.
5. **Post-gate classifiers** — artifact-scout classifier, deferred planning-router, intent classifier/depth announcement.
6. **Phases 0–5** — premise, exploration, decisions, user approval, and consulted design convergence.
7. **Phase 6** — write the primary planning artifact: `INTENT.md` in intent mode, or `SPEC.md` + `PLAN.md` + initial legacy `TASKS.md` in full SDD mode.
8. **Phase 7** — bundled final review after the initial task plan exists: intent mode generates missing initial `TASKS.md` with `task-tree-generator`; full mode requires the legacy `TASKS.md` path before review.
9. **Phase 8** — validate/checkpoint/finalize `TASKS.md`: intent-mode sanity, legacy complexity stamps, scope seed, and workstreams.
10. **Phase 8.4** — post-artifact route checks after the artifacts exist; may recommend `/z-plan-split`, `/z-sharpen`, or `/z-brainstorm`, but never auto-dispatch.
11. **Phase 8.5** — handoff context producer. Writes rich `HANDOFF.md`, calls `scripts/write-handoff.sh`, validates/logs `handoff.json`, and stays before Phase 8.6.
12. **Phase 8.6** — final user handoff gate: fresh-session implementation, audit-first, stop with handoff, or amend.
13. **Phase 9** — finalize run brief, release claim, deregister.

`/z-plan` skill edits for this redesign MUST land in this sequence: **T001 spine/mode gate first**, then **T005 Phase 8 sanity**, then **T006 Phase 8.5 handoff producer**, then **T007 Phase 7 mode-aware reviewer inputs**, then docs sync. Dependent tasks must not edit earlier sections to smuggle in their own ordering changes.

Amend/resume routing is phase-specific: scope or goal changes resume at **Phase 0**, decision changes resume at **Phase 2**, primary artifact wording changes resume at **Phase 6**, and task decomposition changes resume at **Phase 8**.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for existing slug names across both new and legacy plan layouts. If a matching slug dir is found:
   - **Precontext-only slug dir** (only `MAP.md`, `BRAINSTORM.md`, `RESEARCH.md`, and/or `GRILL.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug-collision
        confirmation question via their native channel. Silent omission is forbidden. -->
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): **collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug. This collision check runs UNCONDITIONALLY and is never bypassed by the resolver below.**

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
   <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must present the slug
        recommendation via their native channel when result is "prefill" or "ask". -->
   - `prefill`: present the AskUserQuestion normally, pre-select the derived slug as the recommended option (label suffix: ` (Recommended — your preference)`).
   - `ask`: if the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion` normally. If `$SOURCE == "conflict"`, add to the question header: `(Note: config says <X>, memory says <Y> — your answer below will be offered as a conflict-resolution write target.)` After the user picks an answer that differs from both stored values, surface a one-shot follow-up: "Record your answer as the new preference? (config / memory:very_strong / memory:strong / no)".
   - `halt`: emit `plan_halt` event and exit cleanly — do NOT invoke `AskUserQuestion`:
     ```bash
     if [[ "$RESULT" == "halt" ]]; then
       bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "${RUN:-z-plan}" plan_halt \
         "$(printf '{"reason":"no_ask_blocked","question_id":"workflow.slug_confirm","rule_id":"no_ask_halt"}')"
       echo "halt: no_ask_blocked on workflow.slug_confirm" >&2
       exit 0
     fi
     ```

   **Invariant:** the collision check above is a hard safety prerequisite that runs unconditionally regardless of resolver outcome. The resolver only governs the soft non-obvious-slug confirmation gate.
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
     <!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface this contention question
          via their native channel and await a response. Silent omission is forbidden. -->
     - **Interactive** (not `Z_HARNESS_NO_ASK`): `AskUserQuestion` — **proceed anyway / abort / use a new slug**.
       - `proceed anyway` → continue (uncoordinated; log a `plan_claim_override` event).
       - `abort` → exit 1. (No release — we never held the lock.)
       - `use a new slug` → re-derive a slug and re-run the acquire **once** (loop-guard: at most 1 re-derive prompt; if the new slug also contends, abort). After a successful re-derive: re-export `Z_HARNESS_SLUG`, `Z_HARNESS_PLAN_DIR`, `RUN`, and `CURRENT_ARCHIVE_DIR` for all subsequent calls; re-persist `$Z_HARNESS_SESSION_ID` to the new archive path; re-run claim acquire with the new slug (same `CLAIM_RC` + `CLAIM_OUTPUT` pattern); branch on the new `CLAIM_RC` normally (no further re-derive).
     - **Unattended** (`Z_HARNESS_NO_ASK`): abort (`exit 1`) unless `Z_HARNESS_CLAIM_OVERRIDE=1` → proceed anyway (log override). (No release — we never held the lock.)

   - **`CLAIM_RC == 2`** (stale-takeover — **we now hold the lock**) → show prior holder + idle age from `$CLAIM_OUTPUT`.
     <!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface this stale-takeover
          question via their native channel and await a response. Default is abort.
          Silent omission is forbidden. -->
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
     <!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface this corrupt-lock
          question via their native channel and await a response. Default is abort.
          Silent omission is forbidden. -->
     - **Interactive**: `AskUserQuestion` — **abort (default)** / **proceed UNCOORDINATED** (clearly labeled: you and a peer may clobber each other's artifacts).
       - `abort` → exit 1. (No release — we never held the lock.)
       - `proceed UNCOORDINATED` → continue (log a `plan_claim_corrupt_proceed` event).
     - **Unattended**: abort (`exit 1`) unless `Z_HARNESS_CLAIM_OVERRIDE=1` → proceed uncoordinated. (No release either way.)

   **CLAIM_HELD flag.** The orchestrator MUST set `CLAIM_HELD` to exactly `1` or `0` immediately after the acquire branch resolves. All downstream heartbeat guards (T007) and release guards (T008) evaluate `${CLAIM_HELD:-0}`; if `CLAIM_HELD` is never set, every guard silently evaluates to false, the lock leaks, and heartbeats never fire. This assignment is not optional.

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
   Resolve the kernel path exactly once here. When `KERNEL_PATH` is non-empty, inject `kernel_path: <KERNEL_PATH>` as a line in the `Agent(prompt=...)` of every behavioral-agent dispatch in this run (consultant-primary, consultant-secondary). Omit the line entirely when `KERNEL_PATH` is empty — the agent's static fallback handles self-resolution in that case. Do NOT inject kernel content — inject the path string only.

   Then log provider resolution (once per run, guarded against re-emission):
   ```bash
   if [ ! -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
     mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN"
     touch "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged"
   fi
   ```
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
   ```bash
   if [[ -f "docs/llm/INDEX.json" ]]; then
     DOCS_LLM_INDEX_EXISTS=1
   else
     DOCS_LLM_INDEX_EXISTS=0
   fi
   export DOCS_LLM_INDEX_EXISTS
   ```
9. **Docs-freshness scan (inline, no gate yet).** Initialize signals before scanning: `docs_stale=false`, `research_stale=false`, `map_stale=false`; `stale_concepts_list=[]`; `stale_research_citations=[]`; `stale_map_citations=[]`. If `docs/llm/INDEX.json` exists, compute staleness across all its entries. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is the value from `config.py get docs.staleness_threshold` (default `20` — meaning 20 percent). Record signal: `docs_stale = (stale_pct >= threshold)`. Also record `stale_concepts_list` (list of stale concept slugs) for display. **Do not present any AskUserQuestion here** — the gate fires below in step 10c after all three signals are collected.
10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `MAP.md`, `BRAINSTORM.md`, `RESEARCH.md`, and `GRILL.md`.

    **RESEARCH.md artifact_kind dispatch:** If `RESEARCH.md` exists, read its frontmatter `artifact_kind` and `status` fields first to determine the precontext mode:

    - **`artifact_kind: approach_synthesis` + `status: complete`** → **one-way gate active.** RESEARCH.md is canonical precontext. Skip MAP.md + BRAINSTORM.md injection entirely. Phase 1 uses matrix-based skip rules (see Phase 1 — RESEARCH.md one-way gate shortcut).
    - **`artifact_kind: map`** (legacy old-RESEARCH.md not yet renamed) → treat as a MAP.md artifact: apply freshness check (same regex/mtime logic as MAP.md below), then proceed with component-file injection (MAP.md + BRAINSTORM.md mode). Log `legacy_map_artifact_detected`.
    - **No `artifact_kind` field** → treat as legacy MAP.md artifact per above (component-file injection). Log `legacy_map_artifact_detected`.
    - **`status: incomplete`** → halt. Emit `precontext_research_incomplete`. Recommend regenerating or removing the incomplete artifact before proceeding; do not recommend hidden experimental commands in prod. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `RESEARCH.md status incomplete`.

    **Freshness scan — RESEARCH.md (inline, no gate yet)** (when one-way gate is active): parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). Record signal: `research_stale = true` if any citation is stale. Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) and set `research_stale = true`. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open). **Do not present any AskUserQuestion here** — the gate fires below in step 10c.

    **Freshness scan — MAP.md (inline, no gate yet)** (when one-way gate is inactive and MAP.md exists or RESEARCH.md is treated as MAP.md): parse all file citations using the same regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/` and extensionless allowlist (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to the MAP.md frontmatter `generated_at`; for line-ranges, use min-line mtime. Record signal: `map_stale = true` if any citation is stale. Deleted-source detection: emit `precontext_source_deleted` and set `map_stale = true`. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open). **Do not present any AskUserQuestion here** — the gate fires below in step 10c.

    **GRILL.md detection** (independent of one-way gate): If `$Z_HARNESS_PLAN_DIR/GRILL.md` exists and its frontmatter `status` is `complete`, note it as a GRILL.md precontext artifact. Read its `## Sharpened problem`, `## Killed scope`, and `## Open branches` sections for injection in Phase 0 and Phase 2. GRILL.md is a problem-statement artifact, not a code-citation artifact — **no mandatory freshness gate applies.** Exception: if GRILL.md contains file citations (matched by the same regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`), apply the same freshness scan as MAP.md (mtime vs GRILL.md frontmatter `generated_at`) and fold any stale signal into `map_stale` for the 10c gate. If `status` is not `complete`, skip GRILL.md silently (treat as absent).

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the consolidated
     freshness gate covering docs / research / map staleness — all three signals
     merged into one AskUser call — when stale_pct >= threshold or any precontext
     citation is stale or deleted. Silent omission is forbidden. -->
    **10c. Consolidated freshness gate.** After all four scans complete (docs, RESEARCH.md, MAP.md, GRILL.md citations if present), if `docs_stale OR research_stale OR map_stale` is true:

    Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`. Build up `reason_codes` from all true signals (e.g. `["docs_stale"]`, `["research_stale"]`, `["map_stale"]`, or a combination). Set `to_command` to the most specific release-safe remedy (prefer `"/z-maintain-docs"` if docs_stale; otherwise use `null` and ask the user to refresh/remove stale precontext manually; list all remedies in the route-decision.md body).

    Push-notify (guarded by notify level), then present **ONE** `AskUserQuestion` with:

    - **Header:** "One or more planning inputs are stale. Review and choose how to proceed:"
    - **Per-source bullets** for each true signal (include only bullets for signals that fired):
      - `docs`: "Docs are stale — `stale_pct`% of concepts outdated (affects: `stale_concepts_list`). Remedy: `/z-maintain-docs`."
      - `research`: "RESEARCH.md has stale or deleted citations. Remedy: refresh or remove the stale precontext artifact; experimental synthesis regeneration is dev-only."
      - `map`: "MAP.md has stale or deleted citations. Remedy: refresh or remove the stale terrain artifact; experimental terrain mapping is dev-only."
    - **Options** (always include):
      - `re-run /z-maintain-docs` (if `docs_stale`)
      - `proceed with all stale — I accept the risk`
      - `abandon`

    If only one signal fired, the question naturally collapses to a single per-source bullet plus proceed/abandon; the `/z-maintain-docs` remedy appears only for docs staleness.

    On user choice:

    - **Re-run /z-maintain-docs** (docs staleness only): Update `route-decision.md` with the user's chosen remedy. Emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes` (built above), `signals.docs_stale_or_drifted: <docs_stale>`, `signals.research_stale: <research_stale>`, `signals.map_stale: <map_stale>`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and `user_choice: <the user's selection>`. Halt. Do not auto-invoke the remedy command. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `stale inputs — user chose docs remedy re-run`.
    - **Proceed with all stale**: Update `route-decision.md` to record "no remedy command selected — user accepted stale inputs." Emit `plan_route_decision` with `from_command: "/z-plan"`, **`to_command: null`** (omit the field or set it to `null` explicitly — `/z-stats` must be able to distinguish this from a real remedy), `route_class: "contextual"`, `reason_codes` (built above), `signals.docs_stale_or_drifted: <docs_stale>`, `signals.research_stale: <research_stale>`, `signals.map_stale: <map_stale>`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and `user_choice: "proceed_with_all_stale"`. Then:
      - If `docs_stale=true`: emit a `doc_drift_acknowledged` event. Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
      - If `research_stale=true OR map_stale=true` (regardless of `docs_stale`): emit a `precontext_freshness_acknowledged` event with `sources: ["research"]` / `["map"]` / `["research","map"]` as applicable.
      - Continue to Phase 1.
    - **Abandon**: Emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: null`, `route_class: "contextual"`, `reason_codes` (built above), `signals.docs_stale_or_drifted: <docs_stale>`, `signals.research_stale: <research_stale>`, `signals.map_stale: <map_stale>`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and `user_choice: "abandon"`. Halt. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `stale inputs — user abandoned`.

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

## Artifact Scout deterministic inventory (pre-gate, no Agent)

Run this hook after claim/register/awareness and docs/precontext freshness scanning, before Plan Route Check and before the hard cost gate. It is deterministic shell/Python only; it MUST NOT dispatch `artifact-scout` or any other Agent before the hard gate. The resulting inventory facts may feed deterministic route preflight and cost-shape estimates without creating a pre-gate Agent exception.

```bash
REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
ARTIFACT_SCOUT_INVENTORY="$Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout-inventory.json"
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/artifact-scout-inventory.py" \
  --command /z-plan --slug "$Z_HARNESS_SLUG" --run-id "$RUN" \
  --repo-root "$REPO_ROOT" --plan-dir "$Z_HARNESS_PLAN_DIR" \
  --task "$ARGUMENTS" --output "$ARTIFACT_SCOUT_INVENTORY"
ARTIFACT_SCOUT_EVENT_PAYLOAD="$(python3 - "$ARTIFACT_SCOUT_INVENTORY" <<'PYEOF'
import json, sys
path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
print(json.dumps({
  "command": data.get("command"),
  "slug": data.get("slug"),
  "run_id": data.get("run_id"),
  "artifact_path": path,
  "source_status": data.get("source_status", {}),
  "mandatory_candidate_count": len(data.get("mandatory_candidates") or []),
  "historical_candidate_count": len(data.get("historical_candidates") or []),
  "active_record_count": len(data.get("active_records") or []),
  "worktree_count": len(data.get("worktrees") or []),
  "truncated": bool(data.get("truncated")),
}, separators=(",", ":")))
PYEOF
)"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" artifact_scout_inventory_complete "$ARTIFACT_SCOUT_EVENT_PAYLOAD"
```

The `artifact_scout_inventory_complete` payload MUST include `command`, `slug`, `run_id`, `artifact_path`, `source_status`, `mandatory_candidate_count`, `historical_candidate_count`, `active_record_count`, `worktree_count`, and `truncated` from the inventory JSON.

The post-gate classifier consumes the inline JSON printed by this command and archives its raw response as `$Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout.md`.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear, and once more in **Phase 8.4** after `INTENT.md`/`SPEC.md`/`PLAN.md` and `TASKS.md` exist. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `asks_what_should_we_do`, `alternatives_unsettled`, `architecture_decision`, `reversibility_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `plan_validation_intent`, `question_heavy_artifacts`, `artifact_unsettled_approach`, `post_artifact_check`, and artifact existence.

Deterministic routes:
- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-fix`; if the task is an unknown bug symptom, use contextual `/z-debug`.
- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
- For unknown terrain or missing citations, surface the grounding risk and ask the user to narrow/gather facts; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. During the pre-gate route preflight, this is a **deferred expensive subagent**: do not invoke it before the `/z-plan` hard cost gate below. If deterministic routing cannot decide and the run still needs `/z-plan`, carry the compact signal payload forward, complete the hard cost gate, then invoke `planning-router` after a successful gate and before Phase 1 dispatch. Malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.

**Route-down shortcut surface (route-DOWN routes only).** A route is a *shortcut* only when it routes **DOWN** to a lighter command — i.e. `to_command` is `/z-do`, `/z-fix`, or `/z-debug`. Lateral or upward routes (`/z-plan-split`, `/z-brainstorm`, `/z-audit-plan`, `/z-amend`, `/z-maintain-docs`) are **not** shortcuts — they do not decline a more-robust alternative for speed — so they must NOT fire the surface. Scope this block to the route-down branch ONLY:

```bash
# Callsite 1 — route-down shortcut surface (route-DOWN routes only).
# RUN is already set/exported in Setup step 3 (RUN=<ts>-<slug>; export Z_HARNESS_RUN="$RUN").
# surface-shortcut.sh reads the RUN env var to attribute the event, so export it here.
export RUN="$RUN"
SURFACE_RC=0
case "$to_command" in
  /z-do|/z-fix|/z-debug)
    # Route-DOWN: declining full /z-plan for a lighter command — a genuine shortcut.
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/surface-shortcut.sh" \
      --chosen "$to_command" \
      --declined "full /z-plan" \
      --why "route signals indicate a lighter command is sufficient" || SURFACE_RC=$?
    ;;
  *)
    # Lateral/upward route — not a shortcut. Leave SURFACE_RC=0 (no-op).
    SURFACE_RC=0
    ;;
esac
```

<!-- RUNTIME-GATE: ask_user; category=shortcut; non-supporting drivers must surface this route-down shortcut question via their native channel before taking the lighter route. Silent omission is forbidden. -->
Handle the three `SURFACE_RC` cases explicitly (per the T009 contract):
- **`SURFACE_RC -eq 1`** — surface the shortcut ask: use `AskUserQuestion` to ask "Shortcut: routing down to `<to_command>` instead of running full /z-plan. The robust alternative is to continue /z-plan in full. Proceed with the lighter route?" with options `["Yes, take the lighter route", "No, continue full /z-plan"]`. On "No": stay in /z-plan (skip the route-down).
- **`SURFACE_RC -eq 0`** — no-op (the route was lateral/upward, or not a shortcut): proceed without the shortcut ask.
- **`SURFACE_RC -eq 2`** — INFRA ERROR (shortcut telemetry failed: RUN unset, wiring bug, or the event was lost). Surface a diagnostic to the user ("shortcut telemetry failed — surfacing the route-down confirmation anyway"), then **fall back to surfacing the same `AskUserQuestion` as the `-eq 1` case** (fail-safe: when in doubt, ASK — never silently take the lighter route).

Present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.

When the user chooses **switch** or **abandon** at the route gate (ending the run), per the FINALIZE_STATUS rule execute **Run Brief — halt finalize** (below) with reason `route gate — user chose switch or abandon`.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Explicit planning mode gate (before hard cost gate)

Read `workflow.planning_mode` and `workflow.intent_level` from config (already exported by Setup step 4a). These two knobs are recommendations for the visible Intent-vs-Full SDD gate, not a silent final decision unless an unattended driver must use the recommended default. Normalize `workflow.intent_level` before the cost gate: only `quick`, `standard`, `deep`, and `auto` are recognized; any unknown value is treated as `auto` for dispatch estimation and later classifier resolution.

```bash
PLANNING_MODE="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get workflow.planning_mode 2>/dev/null || echo "intent")"
INTENT_LEVEL_CONFIG="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get workflow.intent_level 2>/dev/null || echo "auto")"
case "$INTENT_LEVEL_CONFIG" in
  quick|standard|deep|auto) ;;
  *) INTENT_LEVEL_CONFIG="auto" ;;
esac
# Export immediately so downstream phases (3, 6, 8, 9) running in fresh shells can read it.
export PLANNING_MODE INTENT_LEVEL_CONFIG
```

**Flag overrides (parsed from `$ARGUMENTS` before the branch below).** CLI flags take precedence over config:

```bash
# Parse flag overrides from $ARGUMENTS.
# Flags are stripped before the task description is used as the slug.
_ARGS_REMAINING="$ARGUMENTS"
for _flag in "$@"; do
  case "$_flag" in
    --full)
      PLANNING_MODE="full"
      PLANNING_MODE_SOURCE="flag"
      _ARGS_REMAINING="${_ARGS_REMAINING/--full/}"
      ;;
    --quick)
      PLANNING_MODE="intent"
      PLANNING_MODE_SOURCE="flag"
      INTENT_LEVEL="quick"
      INTENT_LEVEL_SOURCE="flag"
      INTENT_LEVEL_REASON="--quick flag: forced L1"
      _ARGS_REMAINING="${_ARGS_REMAINING/--quick/}"
      ;;
    --standard)
      PLANNING_MODE="intent"
      PLANNING_MODE_SOURCE="flag"
      INTENT_LEVEL="standard"
      INTENT_LEVEL_SOURCE="flag"
      INTENT_LEVEL_REASON="--standard flag: forced L2"
      _ARGS_REMAINING="${_ARGS_REMAINING/--standard/}"
      ;;
    --deep)
      PLANNING_MODE="intent"
      PLANNING_MODE_SOURCE="flag"
      INTENT_LEVEL="deep"
      INTENT_LEVEL_SOURCE="flag"
      INTENT_LEVEL_REASON="--deep flag: forced L3"
      _ARGS_REMAINING="${_ARGS_REMAINING/--deep/}"
      ;;
  esac
done
# Trim leading/trailing whitespace from the remaining task description.
_ARGS_REMAINING="${_ARGS_REMAINING#"${_ARGS_REMAINING%%[![:space:]]*}"}"
_ARGS_REMAINING="${_ARGS_REMAINING%"${_ARGS_REMAINING##*[![:space:]]}"}"
# Export so slug derivation and subsequent phases see the stripped task text.
export PLANNING_MODE
```

When `INTENT_LEVEL_SOURCE="flag"`, the intent-level announce + override gate (Step 2) still fires — pre-selecting the flag-forced level as the recommended option — but it MUST obey the pre-subagent cost ceiling recorded in `ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX`: it may not silently offer or accept a level more expensive than the gate estimated. Emit `intent_level_chosen` with `source: "flag"` instead of `"classifier"` or `"config-forced"`.

When any of `--quick`, `--standard`, or `--deep` was parsed, also set `INTENT_LEVEL_CONFIG="$INTENT_LEVEL"` (overwriting the config-read value) so the Step 1 forced-level branch fires and the classifier is bypassed:

```bash
# After flag parse: if a level flag was set, sync INTENT_LEVEL_CONFIG so Step 1 skips the classifier.
if [[ "$INTENT_LEVEL_SOURCE" == "flag" ]]; then
  INTENT_LEVEL_CONFIG="$INTENT_LEVEL"
  export INTENT_LEVEL_CONFIG
fi
```

**Backward-compat SPEC detection (Invariant 4).** Check whether the slug dir already contains a legacy `SPEC.md` — if so, treat the plan as legacy regardless of `PLANNING_MODE` config. This guard runs BEFORE the branch below, after flag parsing:

```bash
# Invariant 4: never overwrite an existing legacy plan with INTENT.md.
if [[ -f "$Z_HARNESS_PLAN_DIR/SPEC.md" ]]; then
  if [[ "$PLANNING_MODE" != "full" ]]; then
    echo "[z-plan] SPEC.md detected in '$Z_HARNESS_PLAN_DIR' — routing to legacy path (Invariant 4)." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" legacy_spec_detected \
      "$(printf '{"slug":"%s","spec_path":"%s","original_planning_mode":"%s"}' \
         "$Z_HARNESS_SLUG" "$Z_HARNESS_PLAN_DIR/SPEC.md" "$PLANNING_MODE")"
    PLANNING_MODE="full"
    export PLANNING_MODE
  fi
  # Additionally, if TASKS.md is present, this is a finished plan — route to amend/implement,
  # not a fresh planning run. Surface this to the user.
  if [[ -f "$Z_HARNESS_PLAN_DIR/TASKS.md" ]]; then
    # <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must
    #      surface this finished-legacy-plan advisory via their native channel.
    #      Silent omission is forbidden. -->
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" legacy_plan_exists \
      "$(printf '{"slug":"%s","has_spec":true,"has_tasks":true}' "$Z_HARNESS_SLUG")"
    AskUserQuestion "This slug already has a finished legacy plan (SPEC.md + TASKS.md). \
What would you like to do?" \
      ["Amend the existing plan (/z-amend)", \
       "Implement the existing plan (/z-execute)", \
       "Continue here — start a fresh legacy plan run (overwrites SPEC/PLAN/TASKS)", \
       "Abort"]
    # On /z-amend or /z-execute: log next_step_choice, execute Run Brief — halt finalize,
    # deregister, then exit 0. Do NOT auto-dispatch the chosen command.
    # On "Continue here": proceed with PLANNING_MODE=full; the user accepts overwrite risk.
    # On Abort: execute Run Brief — halt finalize, deregister, then exit 1.
  fi
fi
```

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the
     Intent-vs-Full SDD mode choice before the hard cost gate. Silent omission is forbidden. -->
**Visible planning-mode choice.** After config, flags, and the `SPEC.md` legacy guard have resolved the recommended mode, surface a visible choice **before** the hard cost gate:

- **Intent mode (recommended default for new plans):** write `INTENT.md` with `frozen_at: pending`, then generate initial `TASKS.md`.
- **Full SDD mode:** write legacy `SPEC.md`, `PLAN.md`, and `TASKS.md`.

Config (`workflow.planning_mode`) and flags (`--full`, `--quick`, `--standard`, `--deep`) only choose the recommended/preselected option. A pre-existing `$Z_HARNESS_PLAN_DIR/SPEC.md` is the only hard override: it forces `PLANNING_MODE=full`, records `planning_mode_source=legacy_spec`, and the mode gate must explain that intent mode is unavailable for this slug to avoid overwriting legacy artifacts.

In unattended/no-ask mode, the visible question cannot be surfaced; bind the explicit choice variable from the resolved recommendation instead. The answer source remains `config` (from `workflow.planning_mode`) unless a CLI flag set `PLANNING_MODE_SOURCE=flag`, and the event reason records that this was the unattended/no-ask config default path.

```bash
PLANNING_MODE_RECOMMENDED="$PLANNING_MODE"
PLANNING_MODE_SOURCE="${PLANNING_MODE_SOURCE:-config}"
if [[ -f "$Z_HARNESS_PLAN_DIR/SPEC.md" ]]; then
  PLANNING_MODE_CHOICE="full"
  PLANNING_MODE="full"
  PLANNING_MODE_SOURCE="legacy_spec"
  PLANNING_MODE_REASON="SPEC.md exists; legacy full SDD mode is forced"
elif [[ -n "${Z_HARNESS_NO_ASK:-}" ]]; then
  # Unattended/no-ask drivers cannot surface the visible gate; bind the
  # already-resolved config/flag recommendation as the explicit answer.
  PLANNING_MODE_CHOICE="$PLANNING_MODE_RECOMMENDED"
  case "$PLANNING_MODE_CHOICE" in
    intent|full) PLANNING_MODE="$PLANNING_MODE_CHOICE" ;;
    *) PLANNING_MODE_CHOICE="intent"; PLANNING_MODE="intent" ;;
  esac
  PLANNING_MODE_REASON="unattended/no-ask config default from workflow.planning_mode or CLI flag"
else
  PLANNING_MODE_CHOICE="$(AskUserQuestion "Choose planning mode for this /z-plan run before cost estimation:" \
    ["intent — Intent mode: adaptive INTENT.md + initial TASKS.md (recommended: ${PLANNING_MODE_RECOMMENDED})", \
     "full — Full SDD mode: SPEC.md + PLAN.md + TASKS.md"])"
  # Capture the visible answer into PLANNING_MODE_CHOICE first, normalize the
  # machine token before the em dash, then map it to PLANNING_MODE.
  PLANNING_MODE_CHOICE="${PLANNING_MODE_CHOICE%% — *}"
  case "$PLANNING_MODE_CHOICE" in
    intent) PLANNING_MODE="intent" ;;
    full) PLANNING_MODE="full" ;;
    *) echo "invalid planning mode choice: $PLANNING_MODE_CHOICE" >&2; exit 1 ;;
  esac
  PLANNING_MODE_SOURCE="user"
  PLANNING_MODE_REASON="explicit mode gate"
fi
export PLANNING_MODE PLANNING_MODE_CHOICE PLANNING_MODE_SOURCE PLANNING_MODE_REASON

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" planning_mode_chosen \
  "$(printf '{"slug":"%s","mode":"%s","choice":"%s","recommended_mode":"%s","source":"%s","reason":"%s","legacy_spec_forced":%s}' \
     "$Z_HARNESS_SLUG" "$PLANNING_MODE" "$PLANNING_MODE_CHOICE" \
     "$PLANNING_MODE_RECOMMENDED" "$PLANNING_MODE_SOURCE" "${PLANNING_MODE_REASON:-}" \
     "$(if [[ "$PLANNING_MODE_SOURCE" == "legacy_spec" ]]; then echo true; else echo false; fi)")"
```

The `planning_mode_chosen` event is mandatory and is emitted exactly once per run, before `cost_gate_decision`. Downstream telemetry must treat it as the source of truth for `planning_mode`.


## Pre-subagent cost gate (hard)

This gate runs after the cheap setup, claim/register, freshness checks, deterministic route preflight, and the **explicit planning mode gate** above. It runs **before every expensive subagent**: `planning-router` (when deferred), `intent-classifier`, Phase 1 `doc-fetcher`, Phase 1 Explore, Phase 3 / Phase 7 consultant panels, the Phase 7 pre-dispatch `task-tree-generator` guard, and any other Agent dispatch.

`workflow.pre_run_cost_gate` remains the single disposition authority: `/z-plan` must call `scripts/pre-run-cost-gate.sh`, and that helper delegates the disposition to `scripts/config.py`. Do not read `cost.token_budget` here and do not reimplement the budget comparison in the skill.

Compute explicit dispatch counts using only the documented `z-plan` keys from `scripts/token-cost-profiles.json`: `planning_mode_full`, `intent_level_depth`, `doc_fetcher`, `explore`, `phase3_consultants`, `phase7_consultants`, and `task_tree_generator`. Counts are conservative pre-gate upper bounds; unknown future fan-out stays at the fail-closed default rather than being guessed downward.

```bash
# Explicit z-plan dispatch counts replace profile defaults for these keys.
# Keep this key list in sync with scripts/token-cost-profiles.json profiles["z-plan"].dispatch_contract.accepted_keys.
ZPLAN_DISPATCH_PLANNING_MODE_FULL=0
if [[ "$PLANNING_MODE" == "full" ]]; then
  ZPLAN_DISPATCH_PLANNING_MODE_FULL=1
fi

# intent_level_depth: 0=quick, 1=standard, 2=deep.
# Forced config/flag levels are known before the gate because flag parsing syncs
# INTENT_LEVEL_CONFIG above. Charge their exact depth. Only auto/unknown charges
# deep conservatively because the classifier and level override have not run yet.
ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=0
if [[ "$PLANNING_MODE" == "intent" ]]; then
  case "${INTENT_LEVEL_CONFIG:-auto}" in
    quick)    ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=0 ;;
    standard) ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=1 ;;
    deep)     ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=2 ;;
    *)        ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=2 ;;
  esac
fi
ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX="$ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH"
export ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX

# Setup step 8 records whether docs/llm/INDEX.json exists; use that cheap signal only.
# If the driver did not persist a boolean, fail closed with 1 because docs may exist.
case "${DOCS_LLM_INDEX_EXISTS:-unknown}" in
  0|false|False|no|No) ZPLAN_DISPATCH_DOC_FETCHER=0 ;;
  *)                   ZPLAN_DISPATCH_DOC_FETCHER=1 ;;
esac

# Explore is capped by workflow.max_explore (default 3). Use the configured cap because
# Phase 1 skip conditions are not guaranteed until after the gate.
ZPLAN_DISPATCH_EXPLORE="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get workflow.max_explore 2>/dev/null || echo 3)"
case "$ZPLAN_DISPATCH_EXPLORE" in
  ''|*[!0-9]*) ZPLAN_DISPATCH_EXPLORE=3 ;;
esac

# Phase 3 may still run unless a later, post-gate level decision/user choice skips it.
# Charge the full panel conservatively except when a pre-known L1 Quick level makes
# Phase 3 structurally unreachable before the gate.
ZPLAN_DISPATCH_PHASE3_CONSULTANTS=5
if [[ "$PLANNING_MODE" == "intent" && "${INTENT_LEVEL_CONFIG:-auto}" == "quick" ]]; then
  ZPLAN_DISPATCH_PHASE3_CONSULTANTS=0
fi

# Phase 7 remains a possible final-review panel before the gate; keep the conservative panel count.
ZPLAN_DISPATCH_PHASE7_CONSULTANTS=5

ZPLAN_DISPATCH_TASK_TREE_GENERATOR=0
if [[ "$PLANNING_MODE" == "intent" ]]; then
  ZPLAN_DISPATCH_TASK_TREE_GENERATOR=1
fi

GATE_JSON="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/pre-run-cost-gate.sh" \
  z-plan hard "$RUN" \
  --dispatch \
    planning_mode_full="$ZPLAN_DISPATCH_PLANNING_MODE_FULL" \
    intent_level_depth="$ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH" \
    doc_fetcher="$ZPLAN_DISPATCH_DOC_FETCHER" \
    explore="$ZPLAN_DISPATCH_EXPLORE" \
    phase3_consultants="$ZPLAN_DISPATCH_PHASE3_CONSULTANTS" \
    phase7_consultants="$ZPLAN_DISPATCH_PHASE7_CONSULTANTS" \
    task_tree_generator="$ZPLAN_DISPATCH_TASK_TREE_GENERATOR" \
  2>/dev/null)" || GATE_JSON=""

# Parse and normalize the helper's single JSON object. The raw helper output is never logged.
# If the helper invocation failed, the JSON is malformed, or required estimate fields are
# missing, convert that condition into a sanitized ask/halt branch rather than emitting the
# raw payload.
GATE_HELPER_STATUS=ok
GATE_PARSE_STATUS=ok
GATE_FIELDS_STATUS=ok
GATE_SANITIZED_ERROR=""
GATE_NORMALIZED_JSON="$(python3 - "$GATE_JSON" <<'PY'
import json, sys
raw = sys.argv[1]
try:
    d = json.loads(raw)
except Exception:
    print(json.dumps({"ok": False, "error": "malformed_helper_json"}))
    raise SystemExit(0)

def as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default

est = d.get("estimate")
missing = []
if not isinstance(est, dict):
    est = {}
    missing.extend(["estimated_tokens", "confidence", "basis", "range_high"])
for key in ("estimated_tokens", "confidence", "basis"):
    if key not in est or est.get(key) in (None, ""):
        missing.append(key)
if "range_high" not in est and "range_high" not in d:
    missing.append("range_high")
invalid = []
for key in ("estimated_tokens", "range_high"):
    value = est.get(key, d.get(key))
    if value not in (None, "") and as_int(value, None) is None:
        invalid.append(key)

out = {
    "ok": True,
    "disposition": d.get("disposition") or "ask",
    "human_block": d.get("human_block") or "Token estimate unavailable.",
    "estimated_tokens": as_int(est.get("estimated_tokens"), 0),
    "confidence": est.get("confidence") or "low",
    "basis": est.get("basis") or "unknown",
    "rule_id": d.get("rule_id") or d.get("rule", {}).get("id"),
    "range_high": est.get("range_high", d.get("range_high")),
    "missing_fields": sorted(set(missing + invalid)),
}
print(json.dumps(out, separators=(",", ":")))
PY
)"
if [[ -z "$GATE_JSON" ]]; then
  GATE_HELPER_STATUS=failed
  GATE_SANITIZED_ERROR="helper_invocation_failure"
fi
if [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("ok"))' "$GATE_NORMALIZED_JSON" 2>/dev/null)" != "True" ]]; then
  GATE_PARSE_STATUS=malformed
  GATE_SANITIZED_ERROR="${GATE_SANITIZED_ERROR:-malformed_helper_json}"
fi

GATE_DISPOSITION="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("disposition","ask"))' "$GATE_NORMALIZED_JSON" 2>/dev/null || echo ask)"
GATE_HUMAN_BLOCK="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("human_block","Token estimate unavailable."))' "$GATE_NORMALIZED_JSON" 2>/dev/null || echo "Token estimate unavailable.")"
GATE_EST_TOKENS="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("estimated_tokens",0))' "$GATE_NORMALIZED_JSON" 2>/dev/null || echo 0)"
GATE_CONFIDENCE="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("confidence","low"))' "$GATE_NORMALIZED_JSON" 2>/dev/null || echo low)"
GATE_BASIS="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("basis","unknown"))' "$GATE_NORMALIZED_JSON" 2>/dev/null || echo unknown)"
GATE_RULE_ID="$(python3 -c 'import json,sys; v=json.loads(sys.argv[1]).get("rule_id"); print("" if v is None else v)' "$GATE_NORMALIZED_JSON" 2>/dev/null || true)"
GATE_RANGE_HIGH="$(python3 -c 'import json,sys; v=json.loads(sys.argv[1]).get("range_high"); print("" if v is None else v)' "$GATE_NORMALIZED_JSON" 2>/dev/null || true)"
GATE_MISSING_FIELDS="$(python3 -c 'import json,sys; print(",".join(json.loads(sys.argv[1]).get("missing_fields",[])))' "$GATE_NORMALIZED_JSON" 2>/dev/null || true)"
if [[ -n "$GATE_MISSING_FIELDS" ]]; then
  GATE_FIELDS_STATUS=missing
  GATE_SANITIZED_ERROR="${GATE_SANITIZED_ERROR:-missing_estimate_fields}"
fi

# Helper problems degrade to the ask path when a user can decide. In no-ask/non-interactive
# drivers they are terminal halts: do not proceed after an untrusted or incomplete estimate.
if [[ "$GATE_HELPER_STATUS" != ok || "$GATE_PARSE_STATUS" != ok || "$GATE_FIELDS_STATUS" != ok ]]; then
  if [[ -n "${Z_HARNESS_NO_ASK:-}" ]]; then
    GATE_DISPOSITION="halt"
  else
    GATE_DISPOSITION="ask"
    GATE_HUMAN_BLOCK="Token estimate unavailable or incomplete (${GATE_SANITIZED_ERROR}). Proceed with /z-plan, or abandon before any expensive planning subagents run?"
  fi
fi

printf '%s\n' "$GATE_HUMAN_BLOCK"
```

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the pre-subagent cost gate via their native channel when the normalized disposition is `ask`. Silent omission is forbidden. -->

### Cost gate telemetry contract

`cost_gate_decision` is reserved for **exactly one terminal `/z-plan` cost-gate decision per run**. It is emitted before any expensive Agent dispatch and never emitted again on later success paths. Every terminal branch uses the same payload builder and includes these fields when known:

- `command: "z-plan"`
- `choice`: one of `auto_proceed`, `proceed`, `abandon`, `halt`, or `interrupted`
- `estimated_tokens`, `confidence`, `basis`
- `disposition`: normalized helper disposition that led to the branch (`auto_proceed`, `ask`, `halt`, `unhandled_gate`, or the sanitized fallback disposition)
- `rule_id`
- `range_high`
- `choice_source`: `helper`, `user`, `policy`, `sanitized_helper_error`, or `driver_interrupt`
- `attempt_count`: terminal count of cost reduction / re-estimate attempts
- optional `reason`: sanitized reason such as `gate_policy_halt`, `unhandled_gate`, `helper_invocation_failure`, `malformed_helper_json`, `missing_estimate_fields`, `user_abandoned`, or `user_wait_interrupted`

Nonterminal reduction / re-estimate attempts MUST NOT emit `cost_gate_decision`. They emit `cost_gate_reestimate_attempt` instead, with: `command`, `run_id`, `gate_id`, `attempt_index`, changed driver(s) (for example `changed_drivers`), `prior_range_high`, `new_range_high`, `disposition`, and terminal-correlation fields (`terminal_event_kind: "cost_gate_decision"` plus the same `gate_id`).

Use this logging shape in each terminal branch; bind `ZPLAN_COST_CHOICE`, `ZPLAN_COST_CHOICE_SOURCE`, and optional `ZPLAN_COST_REASON` once, then call it **once**:

```bash
ZPLAN_COST_DECISION_EMITTED=0
ZPLAN_COST_ATTEMPT_COUNT="${ZPLAN_COST_ATTEMPT_COUNT:-0}"
ZPLAN_COST_REESTIMATE_MAX="${ZPLAN_COST_REESTIMATE_MAX:-2}"
ZPLAN_COST_GATE_ID="${RUN}:z-plan:pre-subagent-cost-gate"
emit_zplan_cost_gate_decision_once() {
  if [[ "${ZPLAN_COST_DECISION_EMITTED:-0}" -eq 1 ]]; then
    return 0
  fi
  ZPLAN_COST_DECISION_JSON="$(python3 - \
    "$ZPLAN_COST_CHOICE" "$GATE_EST_TOKENS" "$GATE_CONFIDENCE" "$GATE_BASIS" \
    "$GATE_DISPOSITION" "$GATE_RULE_ID" "$GATE_RANGE_HIGH" "$ZPLAN_COST_CHOICE_SOURCE" \
    "$ZPLAN_COST_ATTEMPT_COUNT" "${ZPLAN_COST_REASON:-}" "$ZPLAN_COST_GATE_ID" <<'PY'
import json, sys
def as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default

choice, est, confidence, basis, disposition, rule_id, range_high, source, attempts, reason, gate_id = sys.argv[1:12]
payload = {
    "command": "z-plan",
    "choice": choice,
    "estimated_tokens": as_int(est, 0),
    "confidence": confidence,
    "basis": basis,
    "disposition": disposition,
    "choice_source": source,
    "gate_id": gate_id,
}
if rule_id:
    payload["rule_id"] = rule_id
if range_high:
    payload["range_high"] = as_int(range_high, 0)
if attempts:
    payload["attempt_count"] = as_int(attempts, 0)
if reason:
    payload["reason"] = reason
print(json.dumps(payload, separators=(",", ":")))
PY
)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "$RUN" cost_gate_decision "$ZPLAN_COST_DECISION_JSON"
  ZPLAN_COST_DECISION_EMITTED=1
}
```

### Cost gate reduction / re-estimate UX (bounded)

The interactive `ask` branch offers a bounded chance to lower already-known `/z-plan` cost drivers and re-run the same helper before any expensive Agent dispatch. This is not a budget bypass: every re-estimate still calls `scripts/pre-run-cost-gate.sh`, every terminal path still emits exactly one `cost_gate_decision`, and every nonterminal reduction emits `cost_gate_reestimate_attempt`.

Loop rules:

- `ZPLAN_COST_REESTIMATE_MAX=2`. After two valid reduction attempts, the prompt MUST remove all reduction options; the user can only proceed with the current estimate or abandon.
- Default action: **Proceed with current estimate (default)**. Drivers may bind Enter/Return to this option only when they can distinguish it from cancellation/timeout.
- Invalid, malformed, unavailable, or driver-unknown choices take the conservative path: set `_COST_GATE_CHOICE=interrupted`, emit `user_wait_end` with `disposition=interrupted`, then use the existing interrupted terminal branch (`choice=interrupted`, `choice_source=driver_interrupt`, halt-finalize). Never treat an unrecognized reduction token as proceed.
- If a reduction re-estimate refreshes `GATE_DISPOSITION=auto_proceed`, that helper approval is terminal: emit the single `cost_gate_decision` with `choice=auto_proceed` / `choice_source=helper` and continue without printing another prompt or recording a user proceed.
- Reduction options are shown only in `PLANNING_MODE=intent`. Legacy `planning_mode=full` has no cost-reduction option in this loop because reducing `planning_mode_full` would change the planning paradigm; users must abandon and rerun with an explicit flag/config if they want a different mode.
- Reducible drivers in this loop are limited to:
  - `intent_level_depth`: explicit user downgrade to L2 Standard or L1 Quick.
  - `phase3_consultants`: only through the L1 Quick downgrade, which sets `INTENT_CONSULT_POLICY=skip` and updates the dispatch count to 0.
- Non-reducible here: `doc_fetcher` (required when docs exist), `task_tree_generator` (required for intent runs), `phase7_consultants` (no existing downstream run-state variable controls a per-run skip), and `explore` (Phase 1's cap is config-governed; do not silently mutate config from this gate).

Exact prompt/options while attempts remain:

```text
<GATE_HUMAN_BLOCK>

Current high-end estimate: <GATE_RANGE_HIGH or unknown> tokens
Confidence: <GATE_CONFIDENCE>; basis: <GATE_BASIS>
Reduction attempts remaining: <ZPLAN_COST_REESTIMATE_MAX - ZPLAN_COST_ATTEMPT_COUNT>

Choose a cost-gate action:
1. Proceed with current estimate (default)
2. Reduce: force L2 Standard — full intent, optional Phase-3 consult
3. Reduce: force L1 Quick — thin intent, skip Phase-3 consult
4. Abandon before expensive planning subagents
```

Exact prompt/options after the cap:

```text
<GATE_HUMAN_BLOCK>

Reduction attempt limit reached (2). Choose a terminal action:
1. Proceed with current estimate (default)
2. Abandon before expensive planning subagents
```

Reduction state mutations are authoritative run state, not display-only. The downgrade MUST update the variables consumed by later mode/consult phases and the dispatch variables passed into the next helper call:

```bash
zplan_apply_cost_reduction() {
  _ZPLAN_COST_REDUCTION="$1"
  ZPLAN_COST_CHANGED_DRIVERS_JSON="[]"

  case "$_ZPLAN_COST_REDUCTION" in
    force_l2_standard)
      # Explicit L3/auto -> L2 downgrade. This is the only way the cost gate may
      # reduce deep semantics to standard semantics.
      PLANNING_MODE="intent"
      INTENT_LEVEL="standard"
      INTENT_LEVEL_CONFIG="standard"   # Step 1 skips intent-classifier later.
      INTENT_LEVEL_SOURCE="user-cost-reduction"
      INTENT_LEVEL_REASON="cost gate reduction: user forced L2 Standard"
      INTENT_CONSULT_POLICY="optional" # Step 3/Phase 3 later read the same policy.
      ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=1
      ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX=1
      # L2 consult is optional later, but the pre-gate estimate stays conservative
      # and keeps charging the Phase-3 panel until the user explicitly skips it there.
      ZPLAN_DISPATCH_PHASE3_CONSULTANTS=5
      ZPLAN_COST_CHANGED_DRIVERS_JSON='["intent_level_depth","intent_level","intent_consult_policy"]'
      ;;

    force_l1_quick)
      # Explicit downgrade to L1 Quick. This is the only cost-gate path that
      # changes Phase-3 consult dispatch to zero before Phase 3.
      PLANNING_MODE="intent"
      INTENT_LEVEL="quick"
      INTENT_LEVEL_CONFIG="quick"      # Step 1 skips intent-classifier later.
      INTENT_LEVEL_SOURCE="user-cost-reduction"
      INTENT_LEVEL_REASON="cost gate reduction: user forced L1 Quick"
      INTENT_CONSULT_POLICY="skip"     # Phase 3 structural guard consumes this.
      ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH=0
      ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX=0
      ZPLAN_DISPATCH_PHASE3_CONSULTANTS=0
      ZPLAN_COST_CHANGED_DRIVERS_JSON='["intent_level_depth","intent_level","intent_consult_policy","phase3_consultants"]'
      ;;

    *)
      return 2
      ;;
  esac

  export PLANNING_MODE INTENT_LEVEL INTENT_LEVEL_CONFIG INTENT_LEVEL_SOURCE INTENT_LEVEL_REASON INTENT_CONSULT_POLICY
  export ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH ZPLAN_DISPATCH_PHASE3_CONSULTANTS ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX
}
```

Re-estimate pseudocode (reuse the exact helper invocation and normalization rules from the initial estimate; raw helper output is still never logged):

```bash
zplan_reestimate_cost_gate_after_reduction() {
  _ZPLAN_PRIOR_RANGE_HIGH="$GATE_RANGE_HIGH"

  GATE_JSON="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/pre-run-cost-gate.sh" \
    z-plan hard "$RUN" \
    --dispatch \
      planning_mode_full="$ZPLAN_DISPATCH_PLANNING_MODE_FULL" \
      intent_level_depth="$ZPLAN_DISPATCH_INTENT_LEVEL_DEPTH" \
      doc_fetcher="$ZPLAN_DISPATCH_DOC_FETCHER" \
      explore="$ZPLAN_DISPATCH_EXPLORE" \
      phase3_consultants="$ZPLAN_DISPATCH_PHASE3_CONSULTANTS" \
      phase7_consultants="$ZPLAN_DISPATCH_PHASE7_CONSULTANTS" \
      task_tree_generator="$ZPLAN_DISPATCH_TASK_TREE_GENERATOR" \
    2>/dev/null)" || GATE_JSON=""

  # Re-run the same parse/normalize block used above, then refresh:
  # GATE_DISPOSITION, GATE_HUMAN_BLOCK, GATE_EST_TOKENS, GATE_CONFIDENCE,
  # GATE_BASIS, GATE_RULE_ID, GATE_RANGE_HIGH, and GATE_SANITIZED_ERROR.

  ZPLAN_COST_ATTEMPT_COUNT=$((ZPLAN_COST_ATTEMPT_COUNT + 1))
  ZPLAN_COST_REESTIMATE_JSON="$(python3 - \
    "$RUN" "$ZPLAN_COST_GATE_ID" "$ZPLAN_COST_ATTEMPT_COUNT" \
    "$ZPLAN_COST_CHANGED_DRIVERS_JSON" "$_ZPLAN_PRIOR_RANGE_HIGH" \
    "$GATE_RANGE_HIGH" "$GATE_DISPOSITION" <<'PY'
import json, sys
run_id, gate_id, attempt, changed, prior, new, disposition = sys.argv[1:8]
def as_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default
payload = {
    "command": "z-plan",
    "run_id": run_id,
    "gate_id": gate_id,
    "attempt_index": int(attempt),
    "changed_drivers": json.loads(changed),
    "prior_range_high": as_int(prior, 0),
    "new_range_high": as_int(new, 0),
    "disposition": disposition,
    "terminal_event_kind": "cost_gate_decision",
}
print(json.dumps(payload, separators=(",", ":")))
PY
)"
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "$RUN" cost_gate_reestimate_attempt "$ZPLAN_COST_REESTIMATE_JSON"
}
```

L3/deep semantics are never reduced implicitly. The only cost-gate paths that lower them are the explicit `force_l2_standard` or `force_l1_quick` options above, both of which set `INTENT_LEVEL_CONFIG`, update `ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX`, and export `INTENT_LEVEL` / `INTENT_CONSULT_POLICY` for downstream phases. Later intent-level override handling MUST treat `ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX` as the maximum already-gated depth; choosing a deeper level requires a fresh hard cost-gate re-estimate before any expensive Agent dispatch.

### Cost gate terminal cleanup helper

The gate runs after `run-brief.sh init` and after the active-plan register attempt. Every terminal post-register failure (`abandon`, `halt`, `unhandled_gate`, helper failure/malformed/missing-field no-ask halt, or interrupted wait) MUST reuse **Run Brief — halt finalize** semantics. The invariant is finalize/render/require before cleanup, then release-before-deregister:

```bash
zplan_cost_gate_halt_finalize() {
  RB_HALT_REASON="$1"
  export RUN_BRIEF_PROFILE=full
  export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
  export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-PLAN.md:SPEC.md}"
  RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
  bash "$RB_SH" set-section --run "$RUN" --section outcome --value "Halted: ${RB_HALT_REASON}"
  bash "$RB_SH" set-section --run "$RUN" --section next --json /dev/stdin <<'JSON'
{"label": "Review plan status and retry or escalate", "command": null}
JSON
  # Run the standard Run Brief finalize sequence before any claim release or registry deregister.
  # This is the inline equivalent of `<!-- include: _fragments/run-brief-finalize.md -->`
  # for the pre-subagent cost gate helper.
  RB_PY="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-run-brief.py"
  bash "$RB_SH" finalize --run "$RUN"
  COST_SUMMARY_TEXT=""
  COST_RENDERER="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/render-cost-summary.py"
  if [ -f "$COST_RENDERER" ] && [ -f "$CURRENT_ARCHIVE_DIR/events.jsonl" ]; then
    COST_SUMMARY_TEXT="$(python3 "$COST_RENDERER" "$CURRENT_ARCHIVE_DIR/events.jsonl" 2>/dev/null || true)"
  fi
  if [[ -n "$COST_SUMMARY_TEXT" ]]; then
    python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat --cost-summary-text "$COST_SUMMARY_TEXT"
  else
    python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format chat
  fi
  if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ]; then
    PUSH_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
    PushNotification("$PUSH_BODY")
  fi
  if [ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end --channel discord)" = yes ]; then
    DISCORD_TITLE="${RUN_BRIEF_INTENT:-z-harness run}"
    DISCORD_BODY="$(python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --format push)"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/notify-discord.sh" "$DISCORD_TITLE" "$DISCORD_BODY" || true
  fi
  python3 "$RB_PY" --run-dir "$CURRENT_ARCHIVE_DIR" --require
  RB_REQUIRE_RC=$?
  if [[ "$RB_REQUIRE_RC" -ne 0 ]]; then
    echo "run-brief: --require failed (missing or invalid run-brief.json)" >&2
  fi
  FINALIZE_STATUS=aborted
  if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" release \
      --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
      --command /z-plan || true
  fi
  if [[ "${REG_RC:-1}" -eq 0 ]]; then
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted 2>/dev/null || true
  fi
}
```

Cleanup matrix:

| Branch | Terminal event | Cleanup / next step |
|---|---|---|
| `auto_proceed` | `choice=auto_proceed`, `choice_source=helper`, `disposition=auto_proceed` | Continue; no AskUser; no cleanup. |
| `ask` → Proceed | `choice=proceed`, `choice_source=user`, `disposition=ask` | Continue after `user_wait_end`; no cleanup. |
| `ask` → Reduce / re-estimate | Nonterminal only: emit `cost_gate_reestimate_attempt`; do **not** emit `cost_gate_decision` | Mutate the authoritative intent/dispatch variables, re-run the helper, print the recomputed human block, and loop until proceed/abandon, cap, interruption, or policy halt. |
| `ask` → Re-estimate returns `auto_proceed` | `choice=auto_proceed`, `choice_source=helper`, `disposition=auto_proceed`, `attempt_count>0` | Continue immediately; no extra AskUser and no user-proceed terminal event. |
| `ask` → Re-estimate returns `halt` | `choice=halt`, `choice_source=policy`, `reason=gate_policy_halt`, `attempt_count>0` | Run `zplan_cost_gate_halt_finalize "cost gate policy halt"`; exit 1. |
| `ask` → Abandon | `choice=abandon`, `choice_source=user`, `reason=user_abandoned` | Run `zplan_cost_gate_halt_finalize "cost gate abandoned by user"`; exit 1. |
| `halt` | `choice=halt`, `choice_source=policy`, `reason=gate_policy_halt` | Run `zplan_cost_gate_halt_finalize "cost gate policy halt"`; exit 1. |
| `unhandled_gate` | `choice=halt`, `choice_source=policy`, `disposition=unhandled_gate`, `reason=unhandled_gate` | Run `zplan_cost_gate_halt_finalize "cost gate unhandled disposition"`; exit 1. |
| Helper invocation failure | Interactive: ask branch with `reason=helper_invocation_failure`; no-ask: terminal `choice=halt` | If terminal, run halt-finalize; if user proceeds, continue only after the terminal `proceed` event. |
| Malformed helper JSON | Interactive: ask branch with `reason=malformed_helper_json`; no-ask: terminal `choice=halt` | Never log raw helper output; if terminal, run halt-finalize. |
| Missing estimate fields | Interactive: ask branch with `reason=missing_estimate_fields`; no-ask: terminal `choice=halt` | Never invent confidence/basis beyond safe defaults; if terminal, run halt-finalize. |
| Interrupted user wait after claim/register | `choice=interrupted`, `choice_source=driver_interrupt`, `reason=user_wait_interrupted` | Emit `user_wait_end` with interrupted disposition, then halt-finalize; release guarded by `CLAIM_HELD`, deregister only when `REG_RC==0`. |

Sanitized helper-error expansion (these are the only allowed outcomes once `GATE_SANITIZED_ERROR` is set):

| Condition | Interactive outcome | No-ask / noninteractive outcome |
|---|---|---|
| `helper_invocation_failure` | Ask with safe defaults. Proceed emits one terminal `cost_gate_decision` (`choice=proceed`, `reason=helper_invocation_failure`) and continues; Abandon/Interrupted emit one terminal decision and halt-finalize. | Emit one terminal `cost_gate_decision` (`choice=halt`, `choice_source=sanitized_helper_error`, `reason=helper_invocation_failure`), then halt-finalize. |
| `malformed_helper_json` | Ask with safe defaults. Proceed emits one terminal `cost_gate_decision` (`choice=proceed`, `reason=malformed_helper_json`) and continues; Abandon/Interrupted emit one terminal decision and halt-finalize. Raw helper text is never logged. | Emit one terminal `cost_gate_decision` (`choice=halt`, `choice_source=sanitized_helper_error`, `reason=malformed_helper_json`), then halt-finalize. Raw helper text is never logged. |
| `missing_estimate_fields` | Ask with safe defaults. Proceed emits one terminal `cost_gate_decision` (`choice=proceed`, `reason=missing_estimate_fields`) and continues; Abandon/Interrupted emit one terminal decision and halt-finalize. | Emit one terminal `cost_gate_decision` (`choice=halt`, `choice_source=sanitized_helper_error`, `reason=missing_estimate_fields`), then halt-finalize. |

Branch on normalized `GATE_DISPOSITION` before any Agent dispatch:

```bash
case "$GATE_DISPOSITION" in
  auto_proceed)
    ZPLAN_COST_CHOICE=auto_proceed
    ZPLAN_COST_CHOICE_SOURCE=helper
    emit_zplan_cost_gate_decision_once
    ;;

  ask)
    while :; do
      # Load-bearing heartbeat BEFORE each user wait.
      if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
          --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
          --command /z-plan || true
      fi
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
        '{"phase":"pre-subagent-cost-gate","reason":"cost_gate"}'

      if [[ "${PLANNING_MODE:-intent}" == "intent" && "${ZPLAN_COST_ATTEMPT_COUNT:-0}" -lt "${ZPLAN_COST_REESTIMATE_MAX:-2}" ]]; then
        AskUserQuestion(
          header: "$GATE_HUMAN_BLOCK

Current high-end estimate: ${GATE_RANGE_HIGH:-unknown} tokens
Confidence: ${GATE_CONFIDENCE}; basis: ${GATE_BASIS}
Reduction attempts remaining: $(( ${ZPLAN_COST_REESTIMATE_MAX:-2} - ${ZPLAN_COST_ATTEMPT_COUNT:-0} ))

Choose a cost-gate action:",
          options: [
            "Proceed with current estimate (default)",
            "Reduce: force L2 Standard — full intent, optional Phase-3 consult",
            "Reduce: force L1 Quick — thin intent, skip Phase-3 consult",
            "Abandon before expensive planning subagents"
          ]
        )
      else
        if [[ "${PLANNING_MODE:-intent}" != "intent" ]]; then
          _ZPLAN_COST_TERMINAL_REASON="No cost-reduction options are available for planning_mode=${PLANNING_MODE}."
        else
          _ZPLAN_COST_TERMINAL_REASON="Reduction attempt limit reached (${ZPLAN_COST_REESTIMATE_MAX:-2})."
        fi
        AskUserQuestion(
          header: "$GATE_HUMAN_BLOCK

${_ZPLAN_COST_TERMINAL_REASON} Choose a terminal action:",
          options: [
            "Proceed with current estimate (default)",
            "Abandon before expensive planning subagents"
          ]
        )
      fi

      # _COST_GATE_CHOICE must be captured as one of:
      # proceed, reduce_force_l2_standard, reduce_force_l1_quick, abandon, interrupted.
      # A re-estimate may also set the internal terminal token auto_proceed_after_reestimate.
      # Empty/default UI selection may become proceed; malformed/unknown tokens MUST become interrupted.
      case "$_COST_GATE_CHOICE" in
        reduce_force_l2_standard|reduce_force_l1_quick)
          if [[ "${ZPLAN_COST_ATTEMPT_COUNT:-0}" -ge "${ZPLAN_COST_REESTIMATE_MAX:-2}" ]]; then
            _COST_GATE_CHOICE=interrupted
            bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
              '{"phase":"pre-subagent-cost-gate","reason":"cost_gate","disposition":"interrupted"}'
            break
          fi
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
            "$(printf '{"phase":"pre-subagent-cost-gate","reason":"cost_gate","disposition":"%s"}' "$_COST_GATE_CHOICE")"
          case "$_COST_GATE_CHOICE" in
            reduce_force_l2_standard) zplan_apply_cost_reduction force_l2_standard ;;
            reduce_force_l1_quick)    zplan_apply_cost_reduction force_l1_quick ;;
          esac || { _COST_GATE_CHOICE=interrupted; break; }
          zplan_reestimate_cost_gate_after_reduction
          if [[ "$GATE_DISPOSITION" == "auto_proceed" ]]; then
            _COST_GATE_CHOICE=auto_proceed_after_reestimate
            break
          elif [[ "$GATE_DISPOSITION" == "halt" ]]; then
            _COST_GATE_CHOICE=policy_halt_after_reestimate
            break
          fi
          printf '%s\n' "$GATE_HUMAN_BLOCK"
          continue
          ;;
        proceed|abandon|interrupted)
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
            "$(printf '{"phase":"pre-subagent-cost-gate","reason":"cost_gate","disposition":"%s"}' "$_COST_GATE_CHOICE")"
          break
          ;;
        *)
          _COST_GATE_CHOICE=interrupted
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
            '{"phase":"pre-subagent-cost-gate","reason":"cost_gate","disposition":"interrupted"}'
          break
          ;;
      esac
    done

    case "$_COST_GATE_CHOICE" in
      auto_proceed_after_reestimate)
        ZPLAN_COST_CHOICE=auto_proceed
        ZPLAN_COST_CHOICE_SOURCE=helper
        ZPLAN_COST_REASON=""
        emit_zplan_cost_gate_decision_once
        ;;
      proceed)
        ZPLAN_COST_CHOICE=proceed
        ZPLAN_COST_CHOICE_SOURCE=user
        ZPLAN_COST_REASON="${GATE_SANITIZED_ERROR:-}"
        emit_zplan_cost_gate_decision_once
        ;;
      abandon)
        ZPLAN_COST_CHOICE=abandon
        ZPLAN_COST_CHOICE_SOURCE=user
        ZPLAN_COST_REASON="${GATE_SANITIZED_ERROR:-user_abandoned}"
        emit_zplan_cost_gate_decision_once
        zplan_cost_gate_halt_finalize "cost gate abandoned by user"
        exit 1
        ;;
      policy_halt_after_reestimate)
        ZPLAN_COST_CHOICE=halt
        ZPLAN_COST_CHOICE_SOURCE=policy
        ZPLAN_COST_REASON=gate_policy_halt
        emit_zplan_cost_gate_decision_once
        zplan_cost_gate_halt_finalize "cost gate policy halt"
        exit 1
        ;;
      *)
        ZPLAN_COST_CHOICE=interrupted
        ZPLAN_COST_CHOICE_SOURCE=driver_interrupt
        ZPLAN_COST_REASON=user_wait_interrupted
        emit_zplan_cost_gate_decision_once
        zplan_cost_gate_halt_finalize "cost gate user wait interrupted"
        exit 1
        ;;
    esac
    ;;

  halt)
    ZPLAN_COST_CHOICE=halt
    ZPLAN_COST_CHOICE_SOURCE="${GATE_SANITIZED_ERROR:+sanitized_helper_error}"
    ZPLAN_COST_CHOICE_SOURCE="${ZPLAN_COST_CHOICE_SOURCE:-policy}"
    ZPLAN_COST_REASON="${GATE_SANITIZED_ERROR:-gate_policy_halt}"
    emit_zplan_cost_gate_decision_once
    zplan_cost_gate_halt_finalize "cost gate policy halt"
    exit 1
    ;;

  unhandled_gate|*)
    ZPLAN_COST_CHOICE=halt
    ZPLAN_COST_CHOICE_SOURCE=policy
    ZPLAN_COST_REASON=unhandled_gate
    GATE_DISPOSITION=unhandled_gate
    emit_zplan_cost_gate_decision_once
    zplan_cost_gate_halt_finalize "cost gate unhandled disposition"
    exit 1
    ;;
esac
```

Never emit a generic "successful gate" `cost_gate_decision` after this branch; the successful paths above are already logged once.

## Artifact Scout classifier (post-gate, before first expensive dispatch)

Run this only after the hard cost gate has produced a terminal proceed/auto-proceed event and only when `artifact-scout-inventory.json` has nontrivial candidates, active/worktree overlaps, partial/truncated sources, or exact-slug/precontext signals. If the inventory is a clean no-match, skip the Agent and continue. This is the first allowed `artifact-scout` Agent position for `/z-plan`; it runs before deferred `planning-router`, `intent-classifier`, Phase 1 `doc-fetcher`, Explore, consultants, or task-tree generation.

```
<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this artifact-scout
     requirement and skip the Agent() call. Skipping means continue without scout routing. -->
Agent(
  subagent_type="artifact-scout",
  description="Artifact scout for z-plan <slug>",
  prompt="current_command: /z-plan
task_or_topic: <original task>
route_chain_json: <current route chain JSON>
repo_root: <abs repo root>
inventory_json_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout-inventory.json

Inline inventory JSON:
<contents printed by scripts/artifact-scout-inventory.py>"
)
```

Write the raw classifier response to `$Z_HARNESS_PLAN_DIR/archive/$RUN/artifact-scout.md`. Parse it with the `artifact-scout` contract. Emit `artifact_scout_classified` for every well-formed response, `artifact_scout_warning` for `STATUS: warned` or warning-only findings, and `artifact_scout_route` only when `ROUTE_RECOMMENDATION` is not `continue` and the JSON has `route_chain_effect: "write_route_decision"`.

Route boundary: warning-only output never writes `route-decision.md`, never emits `artifact_scout_route`, and never advances `route_chain`. Only `ask_user` or route recommendations with `route_chain_effect: "write_route_decision"` may write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision`, and append the artifact-scout hop to `route_chain`.


### Branch: `planning_mode=full` (legacy SDD path)

If `PLANNING_MODE == "full"`, set `INTENT_LEVEL=""` and proceed directly to Phase 0. All subsequent phases run exactly as documented below — no classifier dispatch, no INTENT.md write. The legacy SPEC/PLAN/TASKS path is unchanged.

```bash
# Legacy path guard (formalized by T007).
if [[ "$PLANNING_MODE" == "full" ]]; then
  INTENT_LEVEL=""
  INTENT_LEVEL_SOURCE=""
  # Emit a legacy_mode_active event so telemetry can distinguish full vs intent runs.
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" legacy_mode_active \
    "$(printf '{"slug":"%s","reason":"planning_mode=full"}' "$Z_HARNESS_SLUG")"
  # Fall through to Phase 0; all phases produce SPEC/PLAN/TASKS exactly as documented.
fi
```

### Branch: `planning_mode=intent` (adaptive INTENT path — default)

If `PLANNING_MODE == "intent"` (the default), run the intent-classifier to choose a planning depth level, then announce the chosen level and offer an inline override.

**Step 1 — Resolve the level.**

If `INTENT_LEVEL_CONFIG` is one of `quick`, `standard`, or `deep` (i.e. the user forced a level via config, flag, or the pre-subagent cost-reduction gate), skip the classifier and use the forced value directly. `auto` or any unknown value is not a forced level:

```bash
if [[ "$PLANNING_MODE" == "intent" ]]; then
  if [[ "$INTENT_LEVEL_CONFIG" =~ ^(quick|standard|deep)$ ]]; then
    # Forced level: skip classifier entirely. NEVER fall through to parse below.
    # Preserve explicit flag and cost-gate reduction sources; otherwise this is
    # a normal config-forced level.
    INTENT_LEVEL="$INTENT_LEVEL_CONFIG"
    if [[ "$INTENT_LEVEL_SOURCE" != "user-cost-reduction" && "$INTENT_LEVEL_SOURCE" != "flag" ]]; then
      INTENT_LEVEL_SOURCE="config-forced"
      INTENT_LEVEL_REASON="config-forced: workflow.intent_level=$INTENT_LEVEL_CONFIG"
    fi
  else
    # Auto mode: dispatch the intent-classifier (Haiku). Pass forced_level="" so the
    # classifier knows it is in auto mode.
    INTENT_CLASSIFIER_RC=0
    INTENT_CLASSIFIER_OUT=""
```

<!-- RUNTIME-GATE: subagent; non-supporting drivers must skip the intent-classifier
     Agent() call and default INTENT_LEVEL to "standard" with source "fallback". -->
If `INTENT_LEVEL_CONFIG` is not a forced level and `PLANNING_MODE == "intent"`, dispatch the classifier and capture its return into `INTENT_CLASSIFIER_OUT`. A non-zero exit or empty return triggers the fallback path:

```
INTENT_CLASSIFIER_OUT="$(Agent(
  subagent_type="intent-classifier",
  description="Classify planning depth for <slug>",
  prompt="task_prompt: <verbatim contents of $ARGUMENTS — the raw user task text>\nrepo_root: <abs path to repo root>\nforced_level: "
))"
INTENT_CLASSIFIER_RC=$?
```

(Orchestrators that don't support inline Agent() capture must assign the Agent return to `INTENT_CLASSIFIER_OUT` via their native binding mechanism and set `INTENT_CLASSIFIER_RC` accordingly.)

```bash
    # Parse classifier output (INTENT_CLASSIFIER_OUT holds the agent's return).
    # This parse block is inside the `else` (auto-mode) branch — it NEVER runs
    # when INTENT_LEVEL_CONFIG is quick/standard/deep (i.e. forced case above).
    if [[ "$INTENT_CLASSIFIER_RC" -ne 0 || -z "$INTENT_CLASSIFIER_OUT" ]]; then
      INTENT_LEVEL="standard"
      INTENT_LEVEL_SOURCE="fallback"
      INTENT_LEVEL_REASON="classifier returned non-zero or empty; defaulting standard"
    else
      INTENT_LEVEL="$(echo "$INTENT_CLASSIFIER_OUT" | grep '^LEVEL:' | awk '{print $2}' | tr -d '[:space:]')"
      INTENT_LEVEL_REASON="$(echo "$INTENT_CLASSIFIER_OUT" | grep '^REASON:' | sed 's/^REASON: *//')"
      INTENT_LEVEL_SOURCE="classifier"

      # Fallback: if parse fails or level is unrecognized, default to standard.
      if [[ ! "$INTENT_LEVEL" =~ ^(quick|standard|deep)$ ]]; then
        INTENT_LEVEL="standard"
        INTENT_LEVEL_SOURCE="fallback"
        INTENT_LEVEL_REASON="classifier parse failed or returned unrecognized level; defaulting standard"
      fi
    fi
  fi  # end of auto/non-forced else branch (closes the forced-level INTENT_LEVEL_CONFIG check)
fi
```

**Step 2 — Announce the level + offer override.**

Map the level to its human-readable name:
- `quick` → **L1 (Quick)** — thin intent, 2 sections, no consult
- `standard` → **L2 (Standard)** — full intent, 4 sections, optional consult
- `deep` → **L3 (Deep)** — full intent, 4 sections + full Phase-3 cross-LLM consult

Emit an `intent_level_chosen` event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_level_chosen \
  "$(printf '{"level":"%s","source":"%s","reason":%s}' \
     "$INTENT_LEVEL" "$INTENT_LEVEL_SOURCE" \
     "$(printf '%s' "$INTENT_LEVEL_REASON" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
```

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the
     level announcement and offer the override choice via their native channel.
     Silent omission is forbidden — the user must always see the chosen level. -->
Present an `AskUserQuestion` announcing the chosen level and offering an inline override. Pre-select the chosen level as the recommended option. Before building the options, read `ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX` (0=quick, 1=standard, 2=deep; default to 2 only if the variable is absent for a pre-contract resume). The override gate MUST NOT present or accept an option whose rank is greater than this approved maximum. If a driver cannot hide unsupported options and the user selects a too-deep level, it MUST either re-run the hard pre-subagent cost gate with the higher dispatch counts before any expensive Agent dispatch, or treat the selection as invalid/interrupted and halt-finalize; the default `/z-plan` contract is to constrain the options, not to re-gate.

```bash
case "${ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX:-2}" in
  0|1|2) ;;
  *) ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX=2 ;;
esac
zplan_intent_level_rank() {
  case "$1" in
    quick) echo 0 ;;
    standard) echo 1 ;;
    deep) echo 2 ;;
    *) echo 1 ;;  # safe default matches fallback standard
  esac
}
```

Build the options from that ceiling; never display a level above the approved rank:

```bash
ZPLAN_INTENT_LEVEL_OPTIONS=(
  "<INTENT_LEVEL_LABEL> — proceed (recommended)"
  "L1 Quick — thin intent, skip consult"
)
if [[ "$ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX" -ge 1 ]]; then
  ZPLAN_INTENT_LEVEL_OPTIONS+=("L2 Standard — full intent, optional consult")
fi
if [[ "$ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX" -ge 2 ]]; then
  ZPLAN_INTENT_LEVEL_OPTIONS+=("L3 Deep — full intent, full cross-LLM consult")
fi

AskUserQuestion(
  header: "Planning depth: <INTENT_LEVEL_LABEL> (<INTENT_LEVEL>) — <INTENT_LEVEL_REASON>.
           Proceed with this level, or override?",
  options: ZPLAN_INTENT_LEVEL_OPTIONS
)
```

On user selection:
- **Proceed (recommended)**: keep `INTENT_LEVEL` as-is.
- **L1 Quick / L2 Standard / L3 Deep**: first compute `SELECTED_INTENT_LEVEL_RANK="$(zplan_intent_level_rank "$SELECTED_INTENT_LEVEL")"` and verify `SELECTED_INTENT_LEVEL_RANK <= ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX`. If not, do not mutate `INTENT_LEVEL`; either run the fresh hard cost re-gate described above or treat the selection as invalid/interrupted and halt-finalize. Only after the rank check passes, set `INTENT_LEVEL` to `quick` / `standard` / `deep` and set `INTENT_LEVEL_SOURCE="user-override"`. Emit `intent_level_override` event:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_level_override \
    "$(printf '{"level":"%s","prior_level":"%s","source":"user-override"}' \
       "$INTENT_LEVEL" "$PRIOR_INTENT_LEVEL")"
  ```

**Step 3 — Set consult policy from level.**

```bash
# Level→consult policy:
#   L1 (quick)    → skip Phase-3 consult entirely
#   L2 (standard) → Phase-3 consult optional (user may skip)
#   L3 (deep)     → full Phase-3 cross-LLM consult required
case "$INTENT_LEVEL" in
  quick)    INTENT_CONSULT_POLICY="skip"     ;;
  standard) INTENT_CONSULT_POLICY="optional" ;;
  deep)     INTENT_CONSULT_POLICY="full"     ;;
  *)        INTENT_CONSULT_POLICY="optional" ;;  # safe default
esac
export INTENT_LEVEL INTENT_LEVEL_SOURCE INTENT_CONSULT_POLICY ZPLAN_COST_APPROVED_INTENT_LEVEL_MAX
```

**After mode detection, all downstream phases read `PLANNING_MODE` and `INTENT_LEVEL`:**
- `PLANNING_MODE=intent` with a set `INTENT_LEVEL` → intent path; Phase 6 writes INTENT.md, and the Phase 7 pre-dispatch guard generates the initial level-0 `TASKS.md` before reviewer prompts render `tasks_path`.
- `PLANNING_MODE=full` or `INTENT_LEVEL=""` → legacy path; all phases run as documented.
- SPEC.md detected in slug dir → `PLANNING_MODE` forced to `full` by the backward-compat guard above (Invariant 4); legacy path runs as if `--full` was passed.

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

### 0-sharpen. Auto-sharpen (handoff input)

Run this step **before** the premise check below, immediately after Phase telemetry begins.

**Purpose:** When `/z-plan` is invoked with a handoff-generated task description (e.g. from `/z-handoff`, a downstream prompt, or a machine-authored brief) the request may be under-specified or carry implicit assumptions. This step sharpens it into a confirmed problem statement written to `GRILL.md` — the same artifact that Phase 0 premise check and Phase 2 decisions seeding already consume.

**Opt-out:** Skip this step entirely if any of the following is true:

1. The `--no-sharpen` flag was parsed from `$ARGUMENTS`.
2. `Z_HARNESS_SHARPEN=off` is set in the environment.
3. `workflow.auto_sharpen` resolves to `false` via `python3 scripts/config.py get workflow.auto_sharpen`.
4. `$Z_HARNESS_PLAN_DIR/GRILL.md` already exists with `status: complete` in its frontmatter — the problem has already been sharpened.

When any opt-out condition is true, emit a `sharpen_skipped` event and proceed directly to the Premise check:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_skipped \
  "$(printf '{"reason":"%s"}' "<opt_out_reason>")"
```

**Auto-sharpen procedure (when none of the opt-out conditions above apply):**

Check whether the input looks handoff-generated. Signals: starts with a structured prefix (`[handoff]`, `Task:`, `From:`, `---`, or a YAML/JSON block), was piped via stdin with `$ARGUMENTS` empty, or contains no sentence-ending punctuation and is shorter than 40 characters. If the input does NOT look handoff-generated (i.e. it reads as natural-language prose from a human), skip the sharpen and emit `sharpen_skipped` with `reason: not_handoff_input`.

When the input looks handoff-generated, pose 1–2 brief clarifying questions **in prose** (NOT an `AskUserQuestion` call). Write the questions directly in the response, end the turn, and wait for the user's free-text reply. A one-word reply of `"skip"` or `"go"` proceeds with the raw task unchanged.

Adapt the questions to the specific task — choose 1–2 of the most useful:
- What constraint or success criterion matters most here? (e.g. speed, simplicity, backward-compatibility)
- Who is the primary consumer of the output?
- Are there existing patterns or constraints to work within or avoid?
- What does "done" look like — what would a passing plan let you implement first?

After the user replies (or sends `"skip"/"go"`), write `$Z_HARNESS_PLAN_DIR/GRILL.md` with the following two sections (same format as `/z-brainstorm`'s `§0-sharpen` write path):

```markdown
## Sharpened problem

<synthesize the original task + any clarifications the user gave into 2–4 sentences
 that name the goal, the key constraint(s), and the intended outcome.
 If the user replied "skip" or "go", restate the raw task verbatim here.>

## Open branches

<!-- populated by Phase 2 decisions enumeration -->
```

Emit a `sharpen_gate` event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_gate \
  "$(printf '{"decision":"sharpened","grill_md_existed":false}')"
```

The sharpened problem statement flows into the Premise check below and into Phase 2's GRILL.md decision seeding (Step 2 already reads `## Open branches` from GRILL.md when detected in Setup step 10).

---

**Do not take the prompt's premises for granted.** If precontext artifacts were detected in Setup step 10, **inject their content here** as input to the premise check:
- **One-way gate active** (`artifact_kind: approach_synthesis`): inject RESEARCH.md content only (core hypothesis, approach decision matrix summary, mechanical rank-ordering). Do not inject MAP.md or BRAINSTORM.md.
- **One-way gate inactive** (component-file mode): inject MAP.md (or legacy RESEARCH.md treated as MAP.md) findings and BRAINSTORM.md chosen framing.
- **GRILL.md present** (independent of one-way gate): inject `## Sharpened problem` and `## Killed scope` sections as additional premise framing. Do not re-inject information already covered by MAP.md or RESEARCH.md — if both are present, treat GRILL.md as supplementary problem-statement context only (scope constraints, sharpened goal statement) and skip duplicating factual findings already present in MAP/RESEARCH.

Do not re-derive context already covered by these artifacts.

Before any planning, ask:

- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
- Is there a materially better path the user hasn't considered?

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface any premise
     concern to the user via their native channel and await a response before
     proceeding. Silent omission is forbidden. -->
If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.

If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.

Checkpoint: `phase0-premise.md`.

## Phase 1 — Exploration

**RESEARCH.md one-way gate shortcut** (when `artifact_kind: approach_synthesis` + `status: complete` detected in Setup step 10): If RESEARCH.md is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately using the new RESEARCH.md schema (matrix + evidence gaps):

- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `## Approach decision matrix` section has ≥1 cell with `OK` or `RISKY` verdict citing a file in the task's likely-touched set.
- **Skip Explore** iff RESEARCH.md is non-stale AND its `## Evidence gaps` section is empty (no `UNVERIFIED` cells aggregated).

The four resulting cases (one-way gate active):
- **(a) Skip doc-fetcher only** — matrix has OK/RISKY cell citing a touched file but Evidence gaps non-empty → run Explore, skip doc-fetcher.
- **(b) Skip Explore only** — matrix has no OK/RISKY cell for touched files but Evidence gaps empty → run doc-fetcher, skip Explore.
- **(c) Skip both** — matrix has OK/RISKY cell for touched files AND Evidence gaps empty → skip both, proceed to Phase 2.
- **(d) Run both** — RESEARCH.md is stale, absent in gate-active mode, or meets neither skip condition → run both doc-fetcher and Explore.

**Legacy RESEARCH.md / component-file shortcut** (when one-way gate is inactive — MAP.md or legacy RESEARCH.md detected in Setup step 10): If MAP.md (or legacy RESEARCH.md treated as MAP.md) is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:

- **Skip doc-fetcher** iff MAP.md (or legacy RESEARCH.md) is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- **Skip Explore** iff MAP.md (or legacy RESEARCH.md) is non-stale AND its `Open questions:` section is empty.

The four resulting cases (gate inactive):
- **(a) Skip doc-fetcher only** — MAP.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
- **(b) Skip Explore only** — MAP.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
- **(c) Skip both** — MAP.md has findings for touched files AND no open questions → skip both, proceed to Phase 2.
- **(d) Run both** — MAP.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.

**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.

### 1a. Dispatch doc-fetcher (if INDEX.json exists)

If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the Agent() call. The doc-fetcher phase
     cannot proceed without subagent support; skip conditions in Phase 1 still
     apply (command may continue without doc-fetcher grounding). -->
```
Agent(
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

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the Explore Agent() call. The command
     cannot perform codebase exploration without subagent support; document the
     gap and proceed to Phase 2 with reduced context. -->
```
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Find <thing> related to <slug>",
  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
)
```

**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.

**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore (even Haiku) is a repo-mapping pass that consumes meaningful cache-read context. In the data-overhaul run, 5 Opus Explores ate 13.9 M tokens — ~93% of the entire planning budget. Haiku materially cuts that, but the cap stays: if 3 is not enough, prefer direct Read/Grep/Glob from the orchestrator over a 4th Explore. Override via `workflow.max_explore` in config (default 3) only with explicit user request.

Output a one-paragraph context summary. Checkpoint: `phase1-context.md`.

## Phase 2 — Decisions document

**GRILL.md decision seeding** (if GRILL.md was detected in Setup step 10): before enumerating decisions, inject the `## Open branches` section from GRILL.md as candidate pre-seeded decisions. Each open branch is a decision the user already identified as unresolved — promote it to a decision entry in `decisions.md` with its stated options (if any) and a note that it originated from GRILL.md. Do not duplicate decisions already surfaced by MAP.md or RESEARCH.md analysis; if the same branch appears in multiple artifacts, merge them into one decision entry.

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

Before presenting the decisions doc for approval, run the `check-no-ask` resolver for `workflow.plan_decisions_approval`:

```bash
RESOLVED_DECISIONS="$(python3 scripts/config.py resolve-question workflow.plan_decisions_approval)"
RESOLVE_DECISIONS_EXIT=$?

if [[ $RESOLVE_DECISIONS_EXIT -ne 0 ]]; then
  # Exit codes: 2=bad invocation, 3=unknown question_id, 4=I/O error.
  # In all error cases, fall through to ask the user normally — never silently skip.
  echo "resolve-question failed (exit $RESOLVE_DECISIONS_EXIT); falling back to ask" >&2
  RESULT_DECISIONS="ask"; SOURCE_DECISIONS="error"
else
  RESULT_DECISIONS="$(echo "$RESOLVED_DECISIONS" | jq -r .result)"
  SOURCE_DECISIONS="$(echo "$RESOLVED_DECISIONS" | jq -r .source)"
fi
```

Branch on `$RESULT_DECISIONS`:
- `halt`: emit `plan_halt` event — do NOT invoke `AskUserQuestion`. A subsequent `/z-plan` resume re-enters at Phase 2.5. This halt occurs after a successful register (`REG_RC==0`), so it MUST go through the **Run Brief — halt finalize** shared block (which includes the `CLAIM_HELD`-guarded release + deregister) before exit. The orchestrator MUST NOT skip to `exit 1` without executing that block:
  ```bash
  if [[ "$RESULT_DECISIONS" == "halt" ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "${RUN:-z-plan}" plan_halt \
      "$(printf '{"reason":"no_ask_blocked","question_id":"workflow.plan_decisions_approval","rule_id":"no_ask_halt"}')"
    echo "halt: no_ask_blocked on workflow.plan_decisions_approval" >&2
    # ---- Route through Run Brief — halt finalize (below) ----
    # Sets RUN_BRIEF_PROFILE, calls run-brief.sh set-section, then:
    #   if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then plan-claim.sh release ...; fi
    #   active-plan-registry.py deregister --status aborted
    # DO NOT jump to exit 1 without executing those steps.
    # <execute Run Brief — halt finalize with reason "no_ask_blocked on workflow.plan_decisions_approval">
    exit 1
  fi
  ```
- `skip`: accept the decisions doc silently — no AskUserQuestion. Emit `askuser_skipped` event with `{question_id: "workflow.plan_decisions_approval", source: "$SOURCE_DECISIONS"}` and proceed to Phase 3.
<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the decisions doc
     approval question via their native channel when result is "prefill" or "ask".
     Silent omission is forbidden. -->
- `prefill` or `ask`: proceed normally — block here until the user has approved the decisions doc.

Block here until the user has approved the decisions doc.
```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && <PushNotification: decisions ready for approval>
```

## Phase 3 — Bundled cross-LLM consultation

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip all consultant Agent() calls. Phase 3
     cannot complete without subagent support; document the gap in
     phase3-decisions-final.md and proceed to Phase 4 without cross-LLM input. -->

**Intent-level consult policy guard (intent-mode only).** Before any other guard, check `INTENT_CONSULT_POLICY` (set in Mode detection). This guard only fires when `PLANNING_MODE=intent`; in legacy mode (`PLANNING_MODE=full` or `INTENT_LEVEL=""`), it is a no-op.

```bash
# _PHASE3_CONSULT_SKIP is the structural skip flag for Phase 3.
# Set to 1 when L1 forces a skip or L2 user declines; 0 otherwise (default: run consult).
_PHASE3_CONSULT_SKIP=0

if [[ "$PLANNING_MODE" == "intent" ]]; then
  case "${INTENT_CONSULT_POLICY:-optional}" in
    skip)
      # L1 (quick): skip Phase-3 cross-LLM consult entirely.
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
        "$RUN" consult_skipped \
        "$(printf '{"phase":3,"reason":"intent_level_L1_quick","intent_level":"%s"}' "$INTENT_LEVEL")"
      # Copy decisions.md to phase3-decisions-final.md with a note that consult was skipped at L1.
      cp "$Z_HARNESS_PLAN_DIR/archive/$RUN/decisions.md" \
         "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md" 2>/dev/null || true
      printf '\n---\n_Consult skipped: L1 Quick — no cross-LLM review at this level._\n' \
        >> "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md" 2>/dev/null || true
      # Structural skip: set flag so the entire consult body below is bypassed.
      _PHASE3_CONSULT_SKIP=1
      ;;
    optional)
      # L2 (standard): offer the user a one-shot chance to skip consult.
      # Unattended (Z_HARNESS_NO_ASK set): default to skip.
      if [[ -n "${Z_HARNESS_NO_ASK:-}" ]]; then
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
          "$RUN" consult_skipped \
          "$(printf '{"phase":3,"reason":"intent_level_L2_user_skipped","intent_level":"%s","source":"unattended_default"}' "$INTENT_LEVEL")"
        cp "$Z_HARNESS_PLAN_DIR/archive/$RUN/decisions.md" \
           "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md" 2>/dev/null || true
        _PHASE3_CONSULT_SKIP=1
      else
        # Interactive: load-bearing heartbeat before user wait, then ask.
        if [[ "${CLAIM_HELD:-0}" -eq 1 ]]; then
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-claim.sh" heartbeat \
            --slug "$Z_HARNESS_SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" \
            --command /z-plan || true
        fi
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
          '{"phase":3,"reason":"L2_optional_consult_gate"}'
        # <!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must skip this
        #      optional consult gate and treat it as "skip consult". Silent omission is forbidden —
        #      default to skip in unattended mode. -->
        AskUserQuestion "Planning depth is L2 (Standard). Run the cross-LLM consult?
It adds depth for multi-file decisions but costs extra tokens." \
          ["Yes, run consult (recommended for non-trivial changes)", "No, skip consult"]
        # _L2_CONSULT_CHOICE = the user's selection ("Yes..." or "No...")
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
          '{"phase":3,"reason":"L2_optional_consult_gate"}'
        if [[ "$_L2_CONSULT_CHOICE" == No* ]]; then
          bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
            "$RUN" consult_skipped \
            "$(printf '{"phase":3,"reason":"intent_level_L2_user_skipped","intent_level":"%s"}' "$INTENT_LEVEL")"
          cp "$Z_HARNESS_PLAN_DIR/archive/$RUN/decisions.md" \
             "$Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md" 2>/dev/null || true
          _PHASE3_CONSULT_SKIP=1
        fi
        # On "Yes": _PHASE3_CONSULT_SKIP stays 0 — fall through to consult body below.
      fi
      ;;
    full)
      # L3 (deep): full consult — fall through to the consult-off guard and panel below.
      # _PHASE3_CONSULT_SKIP remains 0.
      ;;
  esac
fi
```

The entire Phase 3 consult body (consult-off guard + panel dispatch) is wrapped in a single structural guard that skips it entirely when `_PHASE3_CONSULT_SKIP=1` (L1 forced skip or L2 user declined):

```bash
if [[ "${_PHASE3_CONSULT_SKIP:-0}" -eq 0 ]]; then
  # --- Phase 3 consult body begins here ---
```

**Consult-off guard.** Before spawning any consultant, check the runtime signal:

```bash
CONSULT_PROVIDER="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-provider.py" consultant_primary 2>/dev/null)"
```

If `CONSULT_PROVIDER == "none"` (i.e. `runtime.consult = "off"` in config):
- Skip all consultant Agent() calls entirely.
- Record tentative decisions as final in `phase3-decisions-final.md`.
- Emit a `consult_skipped` event:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "$RUN" consult_skipped \
    '{"phase":3,"reason":"Z_HARNESS_CONSULT=off"}'
  ```
- Proceed directly to Phase 4.

**Fixed 5-panel dispatch (when `experiment.persona_rotation` is on):**

Check the config knobs:

```bash
PERSONA_ROTATION="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get experiment.persona_rotation 2>/dev/null || echo "true")"
CRITIQUE_PANEL="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get personas.critique_panel 2>/dev/null || echo "true")"
```

If `PERSONA_ROTATION == "true"`, use the **fixed 5-member panel** instead of the standard 2-consultant dispatch. The panel arms are fixed (no randomness):

| Arm | Provider | Model |
|---|---|---|
| gemini | `agy` | (default) |
| claude-sonnet | `cursor` | `claude-4.6-sonnet` (via `--model claude-4.6-sonnet`) |
| grok | `cursor` | `grok-4.3` (via `--model grok-4.3`) |
| composer | `cursor` | `composer-2.5` (via `--model composer-2.5`) |
| codex-5.5 | `codex-cli` | (default) |

**Persona draw for Phase 3 (when `PERSONA_ROTATION == "true"` AND `CRITIQUE_PANEL == "true"`):**

Draw 5 distinct `consultant` personas and positionally bind one body to each arm. Graceful underflow: if the pool has fewer than 5 members, the shorter array is returned (exit 0) and remaining arm slots stay vanilla. This draw is independent of Phase 7's draw — each phase draws its own set.

```bash
PLUGIN="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"

# Vanilla defaults: empty prefix + "<none>" name for all five arms.
# Knob-OFF leaves these untouched — dispatch is byte-identical to the pre-feature behavior.
P3_GEMINI_PREFIX="";     P3_GEMINI_NAME="<none>";     P3_GEMINI_DRAW=""
P3_SONNET_PREFIX="";     P3_SONNET_NAME="<none>";     P3_SONNET_DRAW=""
P3_GROK_PREFIX="";       P3_GROK_NAME="<none>";       P3_GROK_DRAW=""
P3_COMPOSER_PREFIX="";   P3_COMPOSER_NAME="<none>";   P3_COMPOSER_DRAW=""
P3_CODEX_PREFIX="";      P3_CODEX_NAME="<none>";      P3_CODEX_DRAW=""

if [ "$PERSONA_ROTATION" = "true" ] && [ "$CRITIQUE_PANEL" = "true" ]; then
  # Draw up to 5 distinct consultant personas. Underflow → shorter array, exit 0.
  P3_PERSONAS_JSON=$(python3 "$PLUGIN/scripts/resolve-persona.py" random-distinct-for-role consultant --count=5 \
    2>>"$Z_HARNESS_PLAN_DIR/archive/$RUN/persona-draw.log")

  # Positional bind: [0]->gemini, [1]->claude-sonnet, [2]->grok, [3]->composer, [4]->codex-5.5
  for slot in 0:GEMINI 1:SONNET 2:GROK 3:COMPOSER 4:CODEX; do
    idx="${slot%%:*}"; who="${slot##*:}"
    name=$(echo "$P3_PERSONAS_JSON" | jq -r ".[$idx].persona // \"\"")
    path=$(echo "$P3_PERSONAS_JSON" | jq -r ".[$idx].persona_body_path // \"\"")
    draw=$(echo "$P3_PERSONAS_JSON" | jq -r ".[$idx].draw_id // \"\"")
    [ -z "$name" ] && continue   # underflow slot — leave vanilla
    # prepend_persona(path, "") strips frontmatter and returns "<body>\n\n".
    prefix=$(python3 "$PLUGIN/runtime/dispatch/persona_prompt.py" "$path" "" 2>/dev/null | head -c 4096)
    eval "P3_${who}_NAME=\$name"
    eval "P3_${who}_PREFIX=\$prefix"
    eval "P3_${who}_DRAW=\$draw"
  done
fi
```

Before dispatching each panel member, emit a `persona_bound` event logging the arm. When a persona was drawn for the arm, include `persona_id`, `draw_id`, and use `selection_source=random_role_pool_distinct`; vanilla arms retain `selection_source=fixed_panel`:

```bash
declare -A P3_ARM_NAMES=([gemini]="$P3_GEMINI_NAME" [claude-sonnet]="$P3_SONNET_NAME" [grok]="$P3_GROK_NAME" [composer]="$P3_COMPOSER_NAME" [codex-5.5]="$P3_CODEX_NAME")
declare -A P3_ARM_DRAWS=([gemini]="$P3_GEMINI_DRAW" [claude-sonnet]="$P3_SONNET_DRAW" [grok]="$P3_GROK_DRAW" [composer]="$P3_COMPOSER_DRAW" [codex-5.5]="$P3_CODEX_DRAW")
for ARM in gemini claude-sonnet grok composer codex-5.5; do
  pname="${P3_ARM_NAMES[$ARM]}"
  pdraw="${P3_ARM_DRAWS[$ARM]}"
  if [ "$pname" != "<none>" ] && [ -n "$pname" ]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" persona_bound \
      "$(printf '{"run_id":"%s","command":"z-plan","role":"consultant","arm":"%s","selection_source":"random_role_pool_distinct","persona_id":"%s","draw_id":"%s","phase":3}' \
         "$RUN" "$ARM" "$pname" "$pdraw")"
  else
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" persona_bound \
      "$(printf '{"run_id":"%s","command":"z-plan","role":"consultant","arm":"%s","selection_source":"fixed_panel","phase":3}' \
         "$RUN" "$ARM")"
  fi
done
```

Spawn all 5 panel members in parallel in a single message. Each receives the **entire approved decisions doc** with the consult-flagged decisions highlighted. Prepend the arm's persona body (from the draw above) to the prompt when available — empty string when vanilla. Cursor-based arms pass their model via `--model <model>`:

- `Agent(subagent_type="agy", description="Phase 3 consult — gemini arm", prompt="<P3_GEMINI_PREFIX>...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`
- `Agent(subagent_type="cursor", model="claude-4.6-sonnet", description="Phase 3 consult — claude-sonnet arm", prompt="<P3_SONNET_PREFIX>...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`
- `Agent(subagent_type="cursor", model="grok-4.3", description="Phase 3 consult — grok arm", prompt="<P3_GROK_PREFIX>...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`
- `Agent(subagent_type="cursor", model="composer-2.5", description="Phase 3 consult — composer arm", prompt="<P3_COMPOSER_PREFIX>...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`
- `Agent(subagent_type="codex-cli", description="Phase 3 consult — codex-5.5 arm", prompt="<P3_CODEX_PREFIX>...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`

Each `<P3_*_PREFIX>` is the persona body followed by a blank line (from the draw above), or **empty** when that arm drew no persona (underflow slot, `CRITIQUE_PANEL` off, or `PERSONA_ROTATION` off) — in the empty case the prompt is byte-identical to the pre-feature dispatch.

Five calls total. When all return, synthesize across all five responses.

If `PERSONA_ROTATION == "false"`, fall back to the standard 2-consultant behavior: spawn **both** consultants in parallel in a single message:

- `Agent(subagent_type="consultant-primary", ..., prompt="...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`
- `Agent(subagent_type="consultant-secondary", ..., prompt="...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`

Each gets the **entire approved decisions doc** with the consult-flagged decisions highlighted. Two calls total, regardless of feature size.

When all consultants return (from either the 5-panel or 2-consultant path):
1. For each recommendation, articulate **one concrete reason it might be wrong** before accepting it. This is mechanical, not optional.
2. Synthesize. Make the final call yourself, citing which inputs you weighed.
3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.

Save transcripts (the consultants do this themselves). Checkpoint: `phase3-decisions-final.md`.

**Degraded-consult disclosure.** If any consultant did not return a normal response — rate-limited, fell back, errored, or was skipped (e.g. `consult_done` carries a `*_status` other than `ok`, such as `rate_limited_fallback`) — prepend a line to the decisions summary you present in Phase 5: "Consult degraded — `<provider>` unavailable (`<reason>`); treated as effectively single-LLM, weigh the cross-check lower." Record the degraded status in the `consult_done` event payload so `/z-stats` and `/z-improve` can see it. Do not silently present a single-LLM consult as if both arms agreed.

```bash
fi  # end of _PHASE3_CONSULT_SKIP guard — L1/L2-declined paths rejoin here after Phase 4.
```

## Phase 4 — Final clarifications

If anything is still unclear about scope, constraints, or success criteria — ask the user. No silent assumptions.

## Phase 5 — Present + approve

```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && <PushNotification: "Decisions ready for review.">
```

Present a **concise** decisions summary: one bullet per decision (what, why, what was rejected). Separate **Shortcuts** section: what's being skipped, robust alternative, cost of the shortcut.

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface each approval
     question (design decisions, shortcuts) via their native channel and await
     a response before proceeding. Silent omission is forbidden. -->
Use `AskUserQuestion` for explicit approval on each major design decision.

**Surface each proposed shortcut individually.** The **Shortcuts** section presented above is a list, one record per shortcut, each with three fields: the path being taken (what's being skipped), the robust alternative, and the cost. The orchestrator iterates that list and calls `surface-shortcut.sh` **once per shortcut record**, binding `chosen` = the path the shortcut takes (the thing being skipped/the looser route) and `declined` = the named robust alternative that shortcut bypasses. Loop over the actual records — there is no fixed count:

```bash
# Callsite 2 — Phase-5 shortcut approval: one surface-shortcut.sh call per record.
# RUN is already set/exported in Setup step 3; surface-shortcut.sh reads the RUN
# env var to attribute the shortcut_proposed event, so export it here.
export RUN="$RUN"
# Drive this loop from the Shortcuts section the orchestrator just presented:
# for each record, SHORTCUT_CHOSEN = the looser path this shortcut takes,
# SHORTCUT_DECLINED = the robust alternative it bypasses, SHORTCUT_WHY = its cost note.
# (The orchestrator extracts these three fields per record from the Shortcuts list;
#  iterate over every record — do not assume a single shortcut.)
for_each_shortcut_record() {  # conceptual loop body — run once per Shortcuts record
  SURFACE_RC=0
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/surface-shortcut.sh" \
    --chosen "$SHORTCUT_CHOSEN" \
    --declined "$SHORTCUT_DECLINED" \
    --why "$SHORTCUT_WHY" || SURFACE_RC=$?
  # ... handle SURFACE_RC per the three cases below ...
}
```

<!-- RUNTIME-GATE: ask_user; category=shortcut; non-supporting drivers must surface this shortcut approval question via their native channel and await a response before proceeding. Silent omission is forbidden. -->
For each shortcut record, handle the three `SURFACE_RC` cases explicitly (per the T009 contract):
- **`SURFACE_RC -eq 1`** — surface the approval ask: use `AskUserQuestion` to ask "Shortcut proposed: `<SHORTCUT_CHOSEN>`. The robust alternative is: `<SHORTCUT_DECLINED>`. Approve this shortcut?" with options `["Approve shortcut", "Reject — use robust alternative instead"]`. On reject: remove the shortcut from PLAN.md and use the robust path.
- **`SURFACE_RC -eq 0`** — no-op (`--declined` was empty, so this record names no robust alternative and is not a shortcut): proceed without an ask for this record.
- **`SURFACE_RC -eq 2`** — INFRA ERROR (RUN unset, `--chosen` empty, or telemetry lost). Surface a diagnostic ("shortcut telemetry failed for this record — asking for approval anyway"), then **fall back to surfacing the same approval `AskUserQuestion` as the `-eq 1` case** (fail-safe: ASK rather than silently approve the shortcut).

Default to the robust alternative if the user does not approve. Block until all design decisions and all shortcut records are answered.

```bash
# Callsite 2 — Phase-5 shortcut approval: one surface-shortcut.sh call per record.
# RUN is already set/exported in Setup step 3; surface-shortcut.sh reads the RUN
# env var to attribute the shortcut_proposed event, so export it here.
export RUN="$RUN"
# Drive this loop from the Shortcuts section the orchestrator just presented:
# for each record, SHORTCUT_CHOSEN = the looser path this shortcut takes,
# SHORTCUT_DECLINED = the robust alternative it bypasses, SHORTCUT_WHY = its cost note.
# (The orchestrator extracts these three fields per record from the Shortcuts list;
#  iterate over every record — do not assume a single shortcut.)
for_each_shortcut_record() {  # conceptual loop body — run once per Shortcuts record
  SURFACE_RC=0
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/surface-shortcut.sh" \
    --chosen "$SHORTCUT_CHOSEN" \
    --declined "$SHORTCUT_DECLINED" \
    --why "$SHORTCUT_WHY" || SURFACE_RC=$?
  # ... handle SURFACE_RC per the three cases below ...
}
```

<!-- RUNTIME-GATE: ask_user; category=shortcut; non-supporting drivers must surface this shortcut approval question via their native channel and await a response before proceeding. Silent omission is forbidden. -->
For each shortcut record, handle the three `SURFACE_RC` cases explicitly (per the T009 contract):
- **`SURFACE_RC -eq 1`** — surface the approval ask: use `AskUserQuestion` to ask "Shortcut proposed: `<SHORTCUT_CHOSEN>`. The robust alternative is: `<SHORTCUT_DECLINED>`. Approve this shortcut?" with options `["Approve shortcut", "Reject — use robust alternative instead"]`. On reject: remove the shortcut from PLAN.md and use the robust path.
- **`SURFACE_RC -eq 0`** — no-op (`--declined` was empty, so this record names no robust alternative and is not a shortcut): proceed without an ask for this record.
- **`SURFACE_RC -eq 2`** — INFRA ERROR (RUN unset, `--chosen` empty, or telemetry lost). Surface a diagnostic ("shortcut telemetry failed for this record — asking for approval anyway"), then **fall back to surfacing the same approval `AskUserQuestion` as the `-eq 1` case** (fail-safe: ASK rather than silently approve the shortcut).

Default to the robust alternative if the user does not approve. Block until all design decisions and all shortcut records are answered.

## Phase 6 — Write SPEC.md / PLAN.md / TASKS.md (legacy) / INTENT.md (intent-mode)

```bash
if [[ "$PLANNING_MODE" == "intent" ]]; then
  # ---------------------------------------------------------------------------
  # INTENT.md writer (T006).
  # Sections required by level:
  #   quick    (L1): ## Intent  +  ## Acceptance checklist
  #   standard (L2): ## Intent  +  ## Not doing  +  ## Consider for this  +  ## Acceptance checklist
  #   deep     (L3): all four sections (same as L2)
  # ---------------------------------------------------------------------------
```

**INTENT.md writer (intent-mode only).**

Author an `INTENT.md` document at `$Z_HARNESS_PLAN_DIR/INTENT.md`. Populate it from the planning work done in Phases 0–5 (premise check, exploration, decisions, consult findings).

**Frontmatter** — all six fields are required:

```markdown
---
artifact: intent
slug: <$Z_HARNESS_SLUG>
level: <$INTENT_LEVEL — quick|standard|deep>
generated_at: <ISO UTC timestamp, e.g. 2026-06-16T12:00:00Z>
frozen_at: pending
planning_mode: intent
---
```

**Sections** — required sections depend on level:

| Level | `## Intent` | `## Not doing` | `## Consider for this` | `## Acceptance checklist` |
|-------|-------------|----------------|------------------------|---------------------------|
| quick (L1) | required | optional | optional | **always required** |
| standard (L2) | required | **required** | **required** | **always required** |
| deep (L3) | required | **required** | **required** | **always required** |

Section content guidance:
- **`## Intent`** — 2–4 sentence narrative: what this effort accomplishes and why. No implementation detail.
- **`## Not doing`** — explicit scope boundaries (one sentence each). Required at L2+; omit entirely at L1 unless needed for clarity.
- **`## Consider for this`** — situational constraints: budget, tier, domain gotchas, risks worth tracking. Required at L2+; omit entirely at L1 unless needed.
- **`## Acceptance checklist`** — observable, verifiable `[ ]` criteria; one per line. Each criterion must be checkable (not vague "runs" or "works" with no observable object). At least one criterion is required.

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface any criterion
     lint failures to the user via their native channel and halt before writing INTENT.md.
     Silent omission is forbidden. -->
**Validation gate (D8) — compose to temp file, validate, then atomically promote.**

After composing the INTENT.md content, write it to a **temp file** (not the final path) so that a failing validation never leaves a bad INTENT.md on disk:

```bash
INTENT_TEMP="$(mktemp /tmp/intent-draft-XXXXXX.md)"
# Write the composed content to the temp file.
# (Orchestrators write their composed string here; shell-mode: cat > "$INTENT_TEMP".)
```

Run both validators on the temp file — `validate-intent` checks frontmatter fields and required per-level sections; `lint-criteria` checks that acceptance criteria are observable:

```bash
INTENT_SCHEMA_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/intent-schema.py" \
  validate-intent "$INTENT_TEMP" "$INTENT_LEVEL" 2>&1)"
INTENT_SCHEMA_RC=$?

INTENT_LINT_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/intent-schema.py" \
  lint-criteria "$INTENT_TEMP" 2>&1)"
INTENT_LINT_RC=$?
```

Combine failures (non-zero from either validator means the gate fires):

```bash
INTENT_GATE_RC=$(( INTENT_SCHEMA_RC != 0 || INTENT_LINT_RC != 0 ))
INTENT_GATE_OUT="${INTENT_SCHEMA_OUT}${INTENT_LINT_OUT}"
```

If `INTENT_GATE_RC != 0` (one or both validators failed):

1. Show the user the combined output from `$INTENT_GATE_OUT`. Schema failures report missing frontmatter fields or missing required sections; lint failures are formatted as `LINE <n>: <criterion text>`.
2. Explain the rules:
   - **Schema**: all six frontmatter fields required; `## Not doing` and `## Consider for this` required at standard/deep.
   - **Criteria**: must be observable — e.g. "exits 0", "outputs N lines", "raises HTTP 400" are observable; bare "runs" or "works" with no object are not.
3. Ask the user to revise via `AskUserQuestion`:

```
AskUserQuestion(
  header: "INTENT.md validation failed — issues found:
           <INTENT_GATE_OUT formatted as bullet list>
           Describe fixes and I will recompose and re-validate, or abandon.",
  options: [
    "I've described fixes — recompose and re-validate",
    "Abandon — I'll fix INTENT.md manually"
  ]
)
```

  - **"I've described fixes — recompose and re-validate"**: apply the user's described edits to the draft, overwrite `$INTENT_TEMP`, then re-run both validators. Repeat until both pass or user abandons. On each retry cycle, emit an `intent_lint_retry` event:
    ```bash
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_lint_retry \
      "$(printf '{"attempt":%d,"failures":%d}' "$_LINT_ATTEMPT" "$_LINT_FAILURE_COUNT")"
    ```
    Discard the temp file on abandon:
  - **"Abandon"**: `rm -f "$INTENT_TEMP"`. Emit `intent_lint_abandoned` event and halt. Per the FINALIZE_STATUS rule, execute **Run Brief — halt finalize** (below) with reason `INTENT.md validation abandoned by user`:
    ```bash
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_lint_abandoned \
      "$(printf '{"failures":%d}' "$_LINT_FAILURE_COUNT")"
    ```

If `INTENT_GATE_RC == 0` (both validators pass): emit `intent_lint_passed`, then **atomically promote** the temp file to the final path and clean up:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_lint_passed \
  "$(printf '{"level":"%s","slug":"%s"}' "$INTENT_LEVEL" "$Z_HARNESS_SLUG")"

mv "$INTENT_TEMP" "$Z_HARNESS_PLAN_DIR/INTENT.md"
```

After the atomic move, emit `intent_written`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_written \
  "$(printf '{"level":"%s","slug":"%s","path":"%s"}' \
     "$INTENT_LEVEL" "$Z_HARNESS_SLUG" "$Z_HARNESS_PLAN_DIR/INTENT.md")"
```

```bash
else
  # Legacy path (planning_mode=full, or SPEC.md detected — Invariant 4).
  # T007: backward-compat SPEC detection is handled in Mode detection before this branch.
  # This else-branch runs when PLANNING_MODE=full (set by --full flag, config, or SPEC.md guard).
```

**Legacy path (planning_mode=full):**

Create `$Z_HARNESS_PLAN_DIR/SPEC.md` — per-file detailed spec: paths, exported surface, signatures, behavior, invariants, edge cases, error handling.

The SPEC.md must include a `## Planning Inputs` section near the top (after title/overview, before any per-file sections) listing which precontext artifacts contributed to this plan:

```markdown
## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| MAP.md | $Z_HARNESS_PLAN_DIR/MAP.md | <iso timestamp or "n/a"> |
| BRAINSTORM.md | $Z_HARNESS_PLAN_DIR/BRAINSTORM.md | <iso timestamp or "n/a"> |
| RESEARCH.md | $Z_HARNESS_PLAN_DIR/RESEARCH.md | <iso timestamp or "n/a"> |
| GRILL.md | $Z_HARNESS_PLAN_DIR/GRILL.md | <iso timestamp or "n/a"> |
```

Include only rows for artifacts that were actually present. If none were present, write: `none — fresh /z-plan run.`

Create `$Z_HARNESS_PLAN_DIR/PLAN.md` — approved plan: goals, decisions (with rationale), non-goals, approved shortcuts, ordered phases.

Create the initial legacy `$Z_HARNESS_PLAN_DIR/TASKS.md` in the same full-mode branch, before Phase 7. Break PLAN.md into small, independently-implementable tasks. Each task uses a `T001`-style ID, title, files touched, dependencies, acceptance criteria, and status `[ ]`. Size so each fits a fresh context window, target **10–20 tasks**, and preserve the remote-verify/docs-touched flags described in Phase 8 for any applicable task.

SPEC.md and PLAN.md obey **DRY / KISS / SOLID**. State explicitly how the plan respects each. TASKS.md is the executable task contract that Phase 7 reviews and Phase 8 checkpoints.

```bash
fi  # end of Phase 6 if/else: intent-mode (INTENT.md writer) vs legacy (SPEC/PLAN/TASKS writer)
```

## Phase 7 — Bundled final review

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip all Phase 7 consultant Agent() calls.
     Document the gap in the archive and proceed to Phase 8 without final
     review input. -->

**Pre-dispatch TASKS existence/generation guard.** Phase 7 reviews the primary artifact plus the initial task plan, so the guard below runs before the consult-off branch, persona binding, prompt rendering, or any Phase 7 Agent dispatch. It guarantees the task plan exists and is not an amended-intent stale batch: Phase 8 still owns TASKS sanity, complexity/checkpoint work, scope seeding, workstreams, and handoff sequencing.

```bash
PHASE7_TASKS_PATH="$Z_HARNESS_PLAN_DIR/TASKS.md"
PHASE7_TASKS_STALE_REASON="$(python3 -c '
import re, sys
path = sys.argv[1]
try:
    text = open(path, encoding="utf-8").read()
except OSError:
    print("")
    raise SystemExit
m = re.search(r"^stale_reason:\s*(.+?)\s*$", text, re.M)
print(m.group(1).strip() if m else "")
' "$PHASE7_TASKS_PATH" 2>/dev/null || echo "")"
if [[ ! -f "$PHASE7_TASKS_PATH" || "$PHASE7_TASKS_STALE_REASON" == "amended-intent" ]]; then
  if [[ "$PLANNING_MODE" == "intent" ]]; then
    if [[ ! -f "$Z_HARNESS_PLAN_DIR/INTENT.md" ]]; then
      echo "ERROR: intent-mode Phase 7 cannot generate TASKS.md before INTENT.md exists." >&2
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
        '{"reason":"intent_missing_before_phase7_tasks"}' 2>/dev/null || true
      RB_HALT_REASON="intent artifact missing before Phase 7 TASKS guard"
      # include: _fragments/run-brief-halt-finalize-plan.md
      FINALIZE_STATUS=aborted
      python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
        --run-id "$RUN" --status aborted 2>/dev/null || true
      exit 1
    fi

    LEVEL_TASKS_FILE="$PHASE7_TASKS_PATH"
    LEDGER_FILE="$Z_HARNESS_PLAN_DIR/LEDGER.md"

    UNMET_CRITERIA_JSON="$(python3 -c "
import re, sys, json
content = open(sys.argv[1]).read()
m = re.search(r'## Acceptance checklist(.*?)(?=\n## |\Z)', content, re.S)
section = m.group(1) if m else ''
items = re.findall(r'- \[ \] (.+)', section)
print(json.dumps(items))
" "$Z_HARNESS_PLAN_DIR/INTENT.md" 2>/dev/null || echo '[]')"

    INTENT_BFS_LEVEL_CAP="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" \
      get workflow.intent_bfs_level_cap 2>/dev/null || echo "")"
    if [ -z "$INTENT_BFS_LEVEL_CAP" ] || [ "$INTENT_BFS_LEVEL_CAP" = "None" ]; then
      INTENT_BFS_LEVEL_CAP=6
    fi

    INTENT_TOKEN_BUDGET="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" \
      get cost.token_budget 2>/dev/null || echo "")"
    [ "$INTENT_TOKEN_BUDGET" = "None" ] && INTENT_TOKEN_BUDGET=""

    # <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface that intent-mode `/z-plan`
    #      requires `task-tree-generator` to create TASKS.md before Phase 7 review. Silent omission
    #      is forbidden; if the driver cannot dispatch subagents, halt with `plan_halt` rather than
    #      continuing to Phase 7 with a nonexistent tasks_path. -->
    GENERATOR_RETURN="$(Agent(
      subagent_type="task-tree-generator",
      description="Generate initial BFS level 0 task batch",
      prompt="intent_snapshot_path: ${Z_HARNESS_PLAN_DIR}/INTENT.md
ledger_path: ${LEDGER_FILE}
level: 0
unmet_criteria: ${UNMET_CRITERIA_JSON}
prior_level_outcomes: none
tasks_output_path: ${LEVEL_TASKS_FILE}
plan_dir: ${Z_HARNESS_PLAN_DIR}
level_cap: ${INTENT_BFS_LEVEL_CAP}
budget_tokens_remaining: ${INTENT_TOKEN_BUDGET:-}
task_id_start: 1"
    ))"

    GENERATOR_STATUS="$(printf '%s' "$GENERATOR_RETURN" | grep '^STATUS:' | head -1 | awk '{print $2}')"
    GENERATOR_TASKS_COUNT="$(printf '%s' "$GENERATOR_RETURN" | grep '^TASKS_WRITTEN:' | head -1 | awk '{print $2}')"
    GENERATOR_TERMINATION="$(printf '%s' "$GENERATOR_RETURN" | grep '^TERMINATION_CONDITION:' | head -1 | awk '{print $2}')"

    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" intent_initial_tasks_generated \
      "$(printf '{"slug":"%s","status":"%s","tasks_written":%s,"termination_condition":"%s","path":"%s","phase":"phase7_pre_dispatch"}' \
        "$Z_HARNESS_SLUG" "${GENERATOR_STATUS:-unknown}" "${GENERATOR_TASKS_COUNT:-0}" \
        "${GENERATOR_TERMINATION:-unknown}" "$LEVEL_TASKS_FILE")" 2>/dev/null || true

    if [ "${GENERATOR_STATUS:-}" = "unable_to_complete" ] || [ "${GENERATOR_STATUS:-}" = "termination_guard" ] || [ ! -f "$LEVEL_TASKS_FILE" ]; then
      echo "ERROR: task-tree-generator did not produce initial TASKS.md before Phase 7 review." >&2
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
        "$(printf '{"reason":"phase7_intent_initial_tasks_failed","generator_status":"%s","termination_condition":"%s"}' \
          "${GENERATOR_STATUS:-unknown}" "${GENERATOR_TERMINATION:-unknown}")" 2>/dev/null || true
      RB_HALT_REASON="intent initial task generation failed before Phase 7"
      # include: _fragments/run-brief-halt-finalize-plan.md
      FINALIZE_STATUS=aborted
      python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
        --run-id "$RUN" --status aborted 2>/dev/null || true
      exit 1
    fi
  else
    echo "ERROR: full-mode Phase 7 requires $PHASE7_TASKS_PATH to exist before final review." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
      "$(printf '{"reason":"full_mode_tasks_missing_before_phase7","path":"%s"}' "$PHASE7_TASKS_PATH")" 2>/dev/null || true
    RB_HALT_REASON="full-mode TASKS.md missing before Phase 7 review"
    # include: _fragments/run-brief-halt-finalize-plan.md
    FINALIZE_STATUS=aborted
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted 2>/dev/null || true
    exit 1
  fi
fi
```

**Consult-off guard.** Before spawning any consultant, check the runtime signal:

```bash
CONSULT_PROVIDER_P7="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-provider.py" consultant_primary 2>/dev/null)"
```

If `CONSULT_PROVIDER_P7 == "none"` (i.e. `runtime.consult = "off"` in config):
- Skip all Phase 7 consultant Agent() calls entirely.
- Document the gap in the archive.
- Emit a `consult_skipped` event:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
    "$RUN" consult_skipped \
    '{"phase":7,"reason":"Z_HARNESS_CONSULT=off"}'
  ```
- Proceed directly to Phase 8.

**Fixed 5-panel dispatch (when `experiment.persona_rotation` is on):**

Reuse the `PERSONA_ROTATION` and `CRITIQUE_PANEL` values resolved in Phase 3 (already set). If `PERSONA_ROTATION == "true"`, use the same **fixed 5-member panel** for Phase 7.

**Persona draw for Phase 7 (when `PERSONA_ROTATION == "true"` AND `CRITIQUE_PANEL == "true"`):**

Draw a fresh, independent set of 5 distinct `consultant` personas for Phase 7 — do NOT reuse the Phase 3 draw. Positional bind and graceful underflow follow the same rules as Phase 3.

```bash
PLUGIN="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"

# Vanilla defaults for Phase 7: empty prefix + "<none>" name for all five arms.
P7_GEMINI_PREFIX="";     P7_GEMINI_NAME="<none>";     P7_GEMINI_DRAW=""
P7_SONNET_PREFIX="";     P7_SONNET_NAME="<none>";     P7_SONNET_DRAW=""
P7_GROK_PREFIX="";       P7_GROK_NAME="<none>";       P7_GROK_DRAW=""
P7_COMPOSER_PREFIX="";   P7_COMPOSER_NAME="<none>";   P7_COMPOSER_DRAW=""
P7_CODEX_PREFIX="";      P7_CODEX_NAME="<none>";      P7_CODEX_DRAW=""

if [ "$PERSONA_ROTATION" = "true" ] && [ "$CRITIQUE_PANEL" = "true" ]; then
  # Phase 7 gets its own independent draw — do not share with Phase 3.
  P7_PERSONAS_JSON=$(python3 "$PLUGIN/scripts/resolve-persona.py" random-distinct-for-role consultant --count=5 \
    2>>"$Z_HARNESS_PLAN_DIR/archive/$RUN/persona-draw.log")

  # Positional bind: [0]->gemini, [1]->claude-sonnet, [2]->grok, [3]->composer, [4]->codex-5.5
  for slot in 0:GEMINI 1:SONNET 2:GROK 3:COMPOSER 4:CODEX; do
    idx="${slot%%:*}"; who="${slot##*:}"
    name=$(echo "$P7_PERSONAS_JSON" | jq -r ".[$idx].persona // \"\"")
    path=$(echo "$P7_PERSONAS_JSON" | jq -r ".[$idx].persona_body_path // \"\"")
    draw=$(echo "$P7_PERSONAS_JSON" | jq -r ".[$idx].draw_id // \"\"")
    [ -z "$name" ] && continue   # underflow slot — leave vanilla
    prefix=$(python3 "$PLUGIN/runtime/dispatch/persona_prompt.py" "$path" "" 2>/dev/null | head -c 4096)
    eval "P7_${who}_NAME=\$name"
    eval "P7_${who}_PREFIX=\$prefix"
    eval "P7_${who}_DRAW=\$draw"
  done
fi
```

Before dispatching, emit `persona_bound` events for each arm (same pattern as Phase 3, with `"phase":7`). When a persona was drawn, use `selection_source=random_role_pool_distinct` and include `persona_id` + `draw_id`; vanilla arms use `selection_source=fixed_panel`:

```bash
declare -A P7_ARM_NAMES=([gemini]="$P7_GEMINI_NAME" [claude-sonnet]="$P7_SONNET_NAME" [grok]="$P7_GROK_NAME" [composer]="$P7_COMPOSER_NAME" [codex-5.5]="$P7_CODEX_NAME")
declare -A P7_ARM_DRAWS=([gemini]="$P7_GEMINI_DRAW" [claude-sonnet]="$P7_SONNET_DRAW" [grok]="$P7_GROK_DRAW" [composer]="$P7_COMPOSER_DRAW" [codex-5.5]="$P7_CODEX_DRAW")
for ARM in gemini claude-sonnet grok composer codex-5.5; do
  pname="${P7_ARM_NAMES[$ARM]}"
  pdraw="${P7_ARM_DRAWS[$ARM]}"
  if [ "$pname" != "<none>" ] && [ -n "$pname" ]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" persona_bound \
      "$(printf '{"run_id":"%s","command":"z-plan","role":"consultant","arm":"%s","selection_source":"random_role_pool_distinct","persona_id":"%s","draw_id":"%s","phase":7}' \
         "$RUN" "$ARM" "$pname" "$pdraw")"
  else
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" persona_bound \
      "$(printf '{"run_id":"%s","command":"z-plan","role":"consultant","arm":"%s","selection_source":"fixed_panel","phase":7}' \
         "$RUN" "$ARM")"
  fi
done
```

**Phase 7 mode-aware input contract.** The final-review prompt always includes decisions and the task plan, but the primary planning artifact depends on `PLANNING_MODE`. This block is a runtime-expanded prompt payload, not a placeholder mapping. Every Phase 7 Agent prompt (5-panel and 2-consultant fallback) MUST include `planning_mode: $PLANNING_MODE` plus exactly one concrete artifact set:

- **Intent mode:** pass `INTENT.md` + `TASKS.md` + decisions. Do **not** ask for or synthesize `SPEC.md`/`PLAN.md` in intent mode.
  ```text
  planning_mode: $PLANNING_MODE
  intent_path: $Z_HARNESS_PLAN_DIR/INTENT.md
  tasks_path: $Z_HARNESS_PLAN_DIR/TASKS.md
  decisions_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md
  ```
- **Full mode:** pass `SPEC.md` + `PLAN.md` + `TASKS.md` + decisions.
  ```text
  planning_mode: $PLANNING_MODE
  spec_path: $Z_HARNESS_PLAN_DIR/SPEC.md
  plan_path: $Z_HARNESS_PLAN_DIR/PLAN.md
  tasks_path: $Z_HARNESS_PLAN_DIR/TASKS.md
  decisions_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md
  ```

Immediately before any Phase 7 Agent dispatch, build the rendered input block from the current mode and pass that same block to every arm:

```bash
if [[ "$PLANNING_MODE" == "intent" ]]; then
  PHASE7_MODE_AWARE_INPUT_BLOCK="$(cat <<EOF
planning_mode: $PLANNING_MODE
intent_path: $Z_HARNESS_PLAN_DIR/INTENT.md
tasks_path: $Z_HARNESS_PLAN_DIR/TASKS.md
decisions_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md
EOF
)"
else
  PHASE7_MODE_AWARE_INPUT_BLOCK="$(cat <<EOF
planning_mode: $PLANNING_MODE
spec_path: $Z_HARNESS_PLAN_DIR/SPEC.md
plan_path: $Z_HARNESS_PLAN_DIR/PLAN.md
tasks_path: $Z_HARNESS_PLAN_DIR/TASKS.md
decisions_path: $Z_HARNESS_PLAN_DIR/archive/$RUN/phase3-decisions-final.md
EOF
)"
fi

PHASE7_KERNEL_LINE=""
if [[ -n "${KERNEL_PATH:-}" ]]; then
  PHASE7_KERNEL_LINE=$'\n'"kernel_path: $KERNEL_PATH"
fi
```

All Phase 7 arms receive: "Critique this plan. What's wrong, missing, or fragile?" Prepend the arm's Phase 7 persona body to the prompt when available — empty string when vanilla — then include `$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE`. Cursor arms pass their model via `--model <model>`:

- `Agent(subagent_type="agy", description="Phase 7 final review — gemini arm", prompt="${P7_GEMINI_PREFIX}Critique this plan. What's wrong, missing, or fragile?\n$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE")`
- `Agent(subagent_type="cursor", model="claude-4.6-sonnet", description="Phase 7 final review — claude-sonnet arm", prompt="${P7_SONNET_PREFIX}Critique this plan. What's wrong, missing, or fragile?\n$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE")`
- `Agent(subagent_type="cursor", model="grok-4.3", description="Phase 7 final review — grok arm", prompt="${P7_GROK_PREFIX}Critique this plan. What's wrong, missing, or fragile?\n$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE")`
- `Agent(subagent_type="cursor", model="composer-2.5", description="Phase 7 final review — composer arm", prompt="${P7_COMPOSER_PREFIX}Critique this plan. What's wrong, missing, or fragile?\n$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE")`
- `Agent(subagent_type="codex-cli", description="Phase 7 final review — codex-5.5 arm", prompt="${P7_CODEX_PREFIX}Critique this plan. What's wrong, missing, or fragile?\n$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE")`

Each `<P7_*_PREFIX>`/`$P7_*_PREFIX` is the persona body followed by a blank line, or **empty** when that arm drew no persona (underflow slot, `CRITIQUE_PANEL` off, or `PERSONA_ROTATION` off) — in the empty case the prompt differs from vanilla only by the required `planning_mode: $PLANNING_MODE` and artifact-path lines.

If `PERSONA_ROTATION == "false"`, fall back to the standard 2-consultant behavior: spawn both consultants in parallel with the same rendered `$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE`:
- `Agent(subagent_type="consultant-primary", ..., prompt="MODE: plan-review\nCritique this plan. What's wrong, missing, or fragile?\n$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE")`
- `Agent(subagent_type="consultant-secondary", ..., prompt="MODE: plan-review\nCritique this plan. What's wrong, missing, or fragile?\n$PHASE7_MODE_AWARE_INPUT_BLOCK$PHASE7_KERNEL_LINE")`

Apply findings that hold up under "one reason this might be wrong" scrutiny. Push back on the rest with documented reasoning.

## Phase 8 — TASKS.md checkpoint, sanity, and workstream finalization

By Phase 8, `$Z_HARNESS_PLAN_DIR/TASKS.md` must already exist: the Phase 7 pre-dispatch guard generated the intent-mode initial level-0 task plan, while full mode authored the legacy TASKS.md in Phase 6 and the guard halted if it was still missing. Phase 8 does not create the first TASKS.md. It performs the intent-mode schema sanity check, then the existing checkpoint work: legacy complexity stamps, scope seeding, workstream generation, post-artifact routing, and handoff sequencing.

```bash
if [[ "$PLANNING_MODE" == "intent" && -f "$Z_HARNESS_PLAN_DIR/INTENT.md" ]]; then
  LEVEL_TASKS_FILE="$Z_HARNESS_PLAN_DIR/TASKS.md"
  if [[ ! -f "$LEVEL_TASKS_FILE" ]]; then
    echo "ERROR: Phase 8 reached intent-mode TASKS sanity before Phase 7 generated TASKS.md." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
      '{"reason":"phase8_tasks_missing_after_phase7_guard"}' 2>/dev/null || true
    RB_HALT_REASON="TASKS.md missing after Phase 7 pre-dispatch guard"
    # include: _fragments/run-brief-halt-finalize-plan.md
    FINALIZE_STATUS=aborted
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted 2>/dev/null || true
    exit 1
  fi

  TASKS_SANITY_OUT="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/intent-schema.py" \
    validate-tasks "$Z_HARNESS_PLAN_DIR/INTENT.md" "$LEVEL_TASKS_FILE" 2>&1)"
  TASKS_SANITY_RC=$?
  if [ "$TASKS_SANITY_RC" -ne 0 ]; then
    printf '%s\n' "$TASKS_SANITY_OUT" >&2
    TASKS_SANITY_JSON="$(printf '%s' "$TASKS_SANITY_OUT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
      "$(printf '{"reason":"intent_initial_tasks_sanity_failed","errors":%s}' "$TASKS_SANITY_JSON")" 2>/dev/null || true
    RB_HALT_REASON="intent initial task sanity failed"
    # include: _fragments/run-brief-halt-finalize-plan.md
    FINALIZE_STATUS=aborted
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted 2>/dev/null || true
    exit 1
  fi

  # Seed active-plan scope from the initial TASKS.md. Best-effort, same as legacy.
  # <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to
  #      the user and skip the Agent() call. Scope seeding is advisory; the plan proceeds without it. -->
  SCOPE_JSON="$(mktemp)"
  Agent(
    subagent_type="scope-extractor",
    description="Scope for /z-plan intent overlap seed",
    prompt="repo_root: <abs path to repo root>
base: $Z_HARNESS_PLAN_DIR"
  ) > "$SCOPE_JSON" || true
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" update-scope     --run-id "$RUN" --scope-json "$SCOPE_JSON" || true
  rm -f "$SCOPE_JSON"

  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" heartbeat     --run-id "$RUN" --phase phase8 || true

  HERMES_ENABLED="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get workflow.hermes_enabled 2>/dev/null || echo false)"
  if [ "$HERMES_ENABLED" = "true" ]; then
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/generate-workstreams.py"       --slug "$Z_HARNESS_SLUG" --source z-plan --plan-dir "$Z_HARNESS_PLAN_DIR" || true
  fi
  # T007: backward-compat SPEC detection is resolved upstream in Mode detection (Invariant 4).
  # When SPEC.md is present, PLANNING_MODE is forced to "full" before Phase 6 runs, so
  # INTENT.md is never written and this `if` branch is never entered for legacy slug dirs.
  # --- STRUCTURAL SKIP: the entire legacy SPEC/PLAN/TASKS checkpoint section below is inside the
  # `else` branch of this conditional. Do NOT add code between here and the matching `else` ---
else
  # The `else` closes when the legacy path (TASKS.md checkpoint/finalization) finishes — see the
  # closing `fi` at the end of the scope-seed + workstreams manifest block below.
```

**Legacy path (planning_mode=full, or INTENT.md not yet written):**

Full-mode `$Z_HARNESS_PLAN_DIR/TASKS.md` was authored in Phase 6 and must already have survived Phase 7 review. In Phase 8, finalize that legacy task plan: enforce task-count discipline, add complexity stamps, seed scope, and generate workstreams. If a driver reaches this point without TASKS.md, halt rather than letting post-artifact routing or handoff consume an incomplete plan.

```bash
if [[ ! -f "$Z_HARNESS_PLAN_DIR/TASKS.md" ]]; then
  echo "ERROR: Phase 8 reached full-mode TASKS checkpoint without TASKS.md." >&2
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
    '{"reason":"phase8_full_tasks_missing_after_phase7_guard"}' 2>/dev/null || true
  RB_HALT_REASON="full-mode TASKS.md missing after Phase 7 review"
  # include: _fragments/run-brief-halt-finalize-plan.md
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  exit 1
fi
```

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the task-count
     overflow question ("Combine", "Ship as-is", "Restructure") via their native
     channel when >25 tasks are produced. Silent omission is forbidden. -->
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

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip the complexity-classifier Agent() calls.
     Tasks will lack a Complexity stamp; the orchestrator must treat all
     unstamped tasks as "medium" tier. -->
**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" task_classified \
  "$(printf '{"task":"%s","tier":"%s","reason":%s}' "<task-id>" "<tier>" "$(printf '%s' "<reason>" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
```
If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-execute` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).

**Scope seed (immediately after TASKS.md + complexity stamps are finalized).** Dispatch the `scope-extractor` (Haiku) subagent to seed the plan's file scope into the registry so a concurrent `/z-execute` can see what this plan intends. Best-effort, non-fatal — `update-scope` self-logs `registry_error` on failure:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. Scope seeding is advisory; the plan proceeds without it. -->
```
Agent(
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

**Workstreams manifest (generated from TASKS.md).** After TASKS.md is finalized and all task blocks have their Complexity stamps, generate the plan's `workstreams.json` manifest. This file is the conflict DAG for parallelism — `/z-execute` reads it to decide what's safe to run concurrently. Best-effort, non-fatal — any failure is silent; `/z-execute` falls back to inline `**Files:**` dedup when the file is absent.

```bash
HERMES_ENABLED="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" get workflow.hermes_enabled 2>/dev/null || echo false)"
if [ "$HERMES_ENABLED" = "true" ]; then
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/generate-workstreams.py" \
    --slug "$Z_HARNESS_SLUG" --source z-plan --plan-dir "$Z_HARNESS_PLAN_DIR" || true
fi  # hermes_enabled gate (Invariant 6: Hermes machinery never executes unless hermes_enabled=true)
fi  # end of Phase 8 else-branch: legacy SPEC/PLAN/TASKS checkpoint/finalization — skipped when PLANNING_MODE=intent and INTENT.md present
```

## Phase 8.4 — Post-artifact route check

Run this route check after Phase 8 has checkpointed the current artifact set:

- Intent mode: `$Z_HARNESS_PLAN_DIR/INTENT.md` (with `frozen_at: pending`) and canonical `$Z_HARNESS_PLAN_DIR/TASKS.md`.
- Full SDD mode: `$Z_HARNESS_PLAN_DIR/SPEC.md`, `$Z_HARNESS_PLAN_DIR/PLAN.md`, and `$Z_HARNESS_PLAN_DIR/TASKS.md`.

This check reuses the **Plan Route Check** event and route-decision contract. It fires after artifact writing plus TASKS checkpointing, so it can inspect concrete artifact shape instead of estimates:

- Recommend `/z-plan-split` when the produced task count or independent cluster seams show the plan should be split before execution.
- Recommend `/z-sharpen` when artifacts remain question-heavy, acceptance criteria are vague, or task text shows unresolved problem framing.
- Recommend `/z-brainstorm` when approach alternatives remain unsettled or the artifacts still read like "what should we do?" rather than an approved implementation direction.

If a post-artifact route is recommended, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `route_class: "post_artifact"`, include the same `route_chain` loop-prevention fields as the pre-gate route check, and surface an `AskUserQuestion` with **switch / continue here / abandon**. Never auto-dispatch the target command. If no signal fires, record no route artifact and continue to Phase 8.5.

Concrete Phase 8.4 `plan_route_decision` payload example:

```json
{
  "from_command": "/z-plan",
  "to_command": "/z-sharpen",
  "route_class": "post_artifact",
  "reason_codes": ["question_heavy_artifacts", "post_artifact_check"],
  "signals": {
    "plan_validation_intent": false,
    "question_heavy_artifacts": true,
    "artifact_unsettled_approach": false,
    "post_artifact_check": true
  },
  "confidence": "high",
  "classifier_used": false,
  "artifact_path": "$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md",
  "route_chain": [
    {
      "from_command": "/z-plan",
      "to_command": "/z-sharpen",
      "reason_codes": ["question_heavy_artifacts", "post_artifact_check"]
    }
  ],
  "user_choice": "continue_here"
}
```

Recognize both finished-plan artifact sets as complete when deciding whether to route or stop: legacy `SPEC.md` + `PLAN.md` + `TASKS.md`, and intent `INTENT.md` + canonical `TASKS.md`.

## Phase 8.5 — Handoff context producer

The handoff producer runs only after Phase 7 has generated/required `TASKS.md`, the Phase 8 task sanity/checkpoint has passed, and Phase 8.4 post-artifact route checks have either passed or the user explicitly chose to continue here. It must stay before Phase 8.6 and before Phase 9 finalization.

### Archive copies for handoff and finalization

**Intent-mode artifact copy (when `PLANNING_MODE=intent`):** copy `INTENT.md` in addition to (or instead of) `SPEC.md`/`PLAN.md` when INTENT.md is present. If `INTENT.md` is absent, fall back to the legacy artifact set.

```bash
if [[ "$PLANNING_MODE" == "intent" && -f "$Z_HARNESS_PLAN_DIR/INTENT.md" ]]; then
  cp "$Z_HARNESS_PLAN_DIR/INTENT.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/INTENT.md" || true
  # Also copy LEDGER.md when it exists (created by BFS level execution).
  [[ -f "$Z_HARNESS_PLAN_DIR/LEDGER.md" ]] && \
    cp "$Z_HARNESS_PLAN_DIR/LEDGER.md" "$Z_HARNESS_PLAN_DIR/archive/$RUN/LEDGER.md" || true
fi
```

**Legacy artifact copy (planning_mode=full or INTENT.md absent):**

Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).

**Handoff artifact.** Write a curated context slice to `$Z_HARNESS_PLAN_DIR/HANDOFF.md` so the next command can orient itself without re-reading the full planning transcript. This artifact must be written after TASKS sanity and before printing the next-move instruction below. It is a human-readable index and summary, not a second copy of the plan.

```bash
# Determine the primary artifact set for the handoff slice.
_HANDOFF_PRIMARY_ARTIFACTS=("$Z_HARNESS_PLAN_DIR/HANDOFF.md")
if [[ "$PLANNING_MODE" == "intent" && -f "$Z_HARNESS_PLAN_DIR/INTENT.md" ]]; then
  _HANDOFF_PRIMARY_ARTIFACT="$Z_HARNESS_PLAN_DIR/INTENT.md"
  _HANDOFF_ARTIFACT_KIND="INTENT.md"
  _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/INTENT.md" "$Z_HARNESS_PLAN_DIR/TASKS.md")
  [[ -f "$Z_HARNESS_PLAN_DIR/LEDGER.md" ]] && _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/LEDGER.md")
else
  _HANDOFF_PRIMARY_ARTIFACT="$Z_HARNESS_PLAN_DIR/PLAN.md"
  _HANDOFF_ARTIFACT_KIND="PLAN.md"
  _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/SPEC.md" "$Z_HARNESS_PLAN_DIR/PLAN.md" "$Z_HARNESS_PLAN_DIR/TASKS.md")
fi
[[ -f "$Z_HARNESS_PLAN_DIR/workstreams.json" ]] && _HANDOFF_PRIMARY_ARTIFACTS+=("$Z_HARNESS_PLAN_DIR/workstreams.json")
_HANDOFF_PRIMARY_ARTIFACT_LIST="$(printf '%s\n' "${_HANDOFF_PRIMARY_ARTIFACTS[@]}")"
```

Write `$Z_HARNESS_PLAN_DIR/HANDOFF.md` with the following sections:

```markdown
---
artifact: handoff
slug: <$Z_HARNESS_SLUG>
planning_run: <$RUN>
planning_mode: <$PLANNING_MODE>
generated_at: <ISO UTC timestamp>
---

## Slug

<$Z_HARNESS_SLUG>

## Primary artifacts

<One bullet per path in $_HANDOFF_PRIMARY_ARTIFACT_LIST. Use pointers only; do not paste file contents. Include role labels such as "HANDOFF.md — curated context", "INTENT.md — accepted intent contract", "SPEC.md/PLAN.md — full SDD artifacts", "TASKS.md — executable task contract", "workstreams.json — generated workstream split", and "LEDGER.md — intent-mode BFS ledger" when present.>

## Intent / Goal

<2–3 sentence summary of what this plan sets out to accomplish, drawn from INTENT.md §Intent
or PLAN.md goals section — do not invent; quote or lightly paraphrase the approved text.>

## Task batch state

<Summarize the current TASKS.md level and staged groups (base, independent, dependent) in 3–6 bullets. Preserve canonical task ids and status marks from `## TNNN — title \`[ ]\`` headings.>

## Key decisions

<Bullet list of the top 3–5 approved decisions from decisions.md — one line each:
"Decision: [what was decided] — Rationale: [one-sentence reason]">

## Accepted shortcuts (if any)

<Bullet list of any shortcuts approved in Phase 5, or "none".>

## Grounding notes

<1–2 sentences summarizing what the codebase exploration (Phases 1–2) found —
key files, key constraints, or notable surprises. Omit if nothing noteworthy.>

## Invariants

<Bullets for non-negotiable constraints the executor must preserve: public API compatibility, data/schema invariants, ordering guarantees, safety gates, or "none".>

## Rejected approaches

<Bullets for approaches explicitly considered and rejected, with the reason. Use "none" if no rejection was recorded.>

## Decisions archive

<Pointer bullets to the durable decision artifacts under `$Z_HARNESS_PLAN_DIR/archive/$RUN/`, especially `phase3-decisions-final.md`, route-decision.md, consultant outputs, and review outputs when present. Do not paste full transcripts.>

## Verification commands

<Commands the executor/reviewer should run after implementation. Include the targeted tests named by the plan; use "none recorded" if the plan did not define commands.>

## Next move

Choose one of the Phase 8.6 gate options (`fresh_session_implementation`, `audit_first`, `stop_with_handoff`, or `amend`). Do not hard-code an audit-first recommendation before `FINAL_HANDOFF_CHOICE` is captured.
```

Machine handoff files (`handoff.json`, when produced by `scripts/write-handoff.sh`) must stay thin: `context_files` contains only `{path, role}` pointers. For a complete plan directory it should point at `HANDOFF.md`, the HANDOFF.md context categories (`invariants`, `rejected_approaches`, `decisions_archive`, `verification_commands`), `INTENT.md` when present, `SPEC.md`/`PLAN.md` when present, `TASKS.md`, `workstreams.json` when present, `LEDGER.md` when present, and `SESSION.md`; the schema owns the allowed roles.

After writing `HANDOFF.md`, call the machine handoff producer before Phase 8.6. Set the required z-plan overrides so the generated `handoff.json` describes a completed planning handoff, not an in-progress execute checkpoint; validate that the file exists and log both the human and machine artifacts:

```bash
export Z_HARNESS_HANDOFF_STATUS="complete"
export Z_HARNESS_HANDOFF_NEXT_STEP="Plan complete for ${Z_HARNESS_SLUG}. Choose the Phase 8.6 next step: fresh-session implementation, audit first, stop with handoff, or amend. Read HANDOFF.md, ${_HANDOFF_ARTIFACT_KIND}, and TASKS.md before acting."
export Z_HARNESS_AGENT="${Z_HARNESS_AGENT:-pi}"

HANDOFF_PRODUCER_OUT="$(Z_HARNESS_PLAN_DIR="$Z_HARNESS_PLAN_DIR" Z_HARNESS_SLUG="$Z_HARNESS_SLUG" bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/write-handoff.sh" 2>&1)"
HANDOFF_PRODUCER_RC=$?
if [[ "$HANDOFF_PRODUCER_RC" -ne 0 || ! -s "$Z_HARNESS_PLAN_DIR/handoff.json" ]]; then
  echo "ERROR: write-handoff.sh failed before Phase 8.6: $HANDOFF_PRODUCER_OUT" >&2
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_halt \
    "$(printf '{"reason":"handoff_json_producer_failed","rc":%d}' "$HANDOFF_PRODUCER_RC")" 2>/dev/null || true
  exit 1
fi

HANDOFF_JSON_VALIDATE="$(python3 - "$Z_HARNESS_PLAN_DIR/handoff.json" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
roles = [entry.get("role") for entry in data.get("context_files", []) if isinstance(entry, dict)]
required = {"handoff", "tasks"}
missing = sorted(required.difference(roles))
if missing:
    raise SystemExit(f"missing required handoff context roles: {missing}")
print(json.dumps({"path": path, "roles": roles, "context_file_count": len(roles)}, separators=(",", ":")))
PYEOF
)"

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" handoff_written \
  "$(printf '{"slug":"%s","path":"%s","artifact_kind":"%s","handoff_json":"%s","producer_output":"%s"}' \
     "$Z_HARNESS_SLUG" "$Z_HARNESS_PLAN_DIR/HANDOFF.md" "$_HANDOFF_ARTIFACT_KIND" \
     "$Z_HARNESS_PLAN_DIR/handoff.json" "$(printf '%s' "$HANDOFF_PRODUCER_OUT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])')")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" handoff_json_validated "$HANDOFF_JSON_VALIDATE"
```

## Phase 8.6 — Final handoff gate

Print the completion summary, then surface one final user gate. This gate occurs **after** Phase 8.5 writes `HANDOFF.md` and **before** Phase 9 finalizes the run:

```text
Plan complete for slug: <$Z_HARNESS_SLUG>

Primary artifact: <$_HANDOFF_PRIMARY_ARTIFACT>

<If PLANNING_MODE=intent: "INTENT.md is the contract for this run. It captures the
 accepted goal, scope boundaries, and acceptance checklist. Read it before auditing.">
<If PLANNING_MODE=full: "SPEC.md + PLAN.md + TASKS.md are the contract for this run.">

Handoff context written to: $Z_HARNESS_PLAN_DIR/HANDOFF.md
```

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface
     the final handoff gate after HANDOFF.md is written and before Phase 9 finalization.
     Silent omission is forbidden. -->
Ask the user to choose exactly one next step:

- **Fresh-session implementation** — run `/clear`, then `/z-execute <$Z_HARNESS_SLUG>`.
- **Audit first** — run `/clear`, then `/z-audit-plan <$Z_HARNESS_SLUG>`.
- **Stop with handoff** — leave `HANDOFF.md` as the next-session context and do not start another command.
- **Amend** — run `/z-amend <$Z_HARNESS_SLUG>` and resume from the mapped phase below.

Request-change resume map: scope/goal changes resume at Phase 0; decision changes resume at Phase 2; primary artifact wording changes resume at Phase 6; task decomposition changes resume at Phase 8.

Capture the final gate answer, normalize it into `FINAL_HANDOFF_CHOICE`, and export that machine value before any logging or `case "$FINAL_HANDOFF_CHOICE"` use. The only valid values are `fresh_session_implementation`, `audit_first`, `stop_with_handoff`, and `amend`.

```bash
FINAL_HANDOFF_CHOICE="$(AskUserQuestion "Choose the next step for <$Z_HARNESS_SLUG>:" \
  ["fresh_session_implementation — Fresh-session implementation: run /clear, then /z-execute <$Z_HARNESS_SLUG>", \
   "audit_first — Audit first: run /clear, then /z-audit-plan <$Z_HARNESS_SLUG>", \
   "stop_with_handoff — Stop with handoff: leave HANDOFF.md as next-session context", \
   "amend — Amend: run /z-amend <$Z_HARNESS_SLUG>"])"
FINAL_HANDOFF_CHOICE="${FINAL_HANDOFF_CHOICE%% — *}"
export FINAL_HANDOFF_CHOICE
case "$FINAL_HANDOFF_CHOICE" in
  fresh_session_implementation|audit_first|stop_with_handoff|amend) ;;
  *) echo "invalid final handoff choice: $FINAL_HANDOFF_CHOICE" >&2; exit 1 ;;
esac
```

Log the selected next step:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" next_step_choice \
  "$(printf '{"choice":"%s","source":"phase_8_6_final_handoff_gate"}' "$FINAL_HANDOFF_CHOICE")"
```

Set `$NEXT_JSON` for the run brief from the gate selection:

```bash
case "$FINAL_HANDOFF_CHOICE" in
  fresh_session_implementation)
    NEXT_JSON='{"label":"Implement in a fresh session","command":"/z-execute"}'
    ;;
  audit_first)
    NEXT_JSON='{"label":"Audit the plan first","command":"/z-audit-plan"}'
    ;;
  stop_with_handoff)
    NEXT_JSON='{"label":"Stop with handoff","command":null}'
    ;;
  amend)
    NEXT_JSON='{"label":"Amend the plan","command":"/z-amend"}'
    ;;
esac
```

## Phase 9 — Finalize archive

**Run Brief finalize (registry Phase 9).** Set registry artifact env, pre-seed outcome/status/next, then include the shared fragment. Chat and push text are rendered from `run-brief.json` only — do not author independent completion prose.

```bash
export RUN_BRIEF_PROFILE="full"
export RUN_BRIEF_ARTIFACT="$CURRENT_ARCHIVE_DIR/decisions.md"
export RUN_BRIEF_ARTIFACT_FALLBACKS="PLAN.md:SPEC.md"
export RUN_BRIEF_ARTIFACT="${RUN_BRIEF_ARTIFACT:-}"
export RUN_BRIEF_ARTIFACT_FALLBACKS="${RUN_BRIEF_ARTIFACT_FALLBACKS:-}"

RB_SH="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/run-brief.sh"
TASK_COUNT="$(grep -cE '^[[:space:]]*- \[[[:space:]]\] T[0-9]+' "$Z_HARNESS_PLAN_DIR/TASKS.md" 2>/dev/null || echo 0)"
bash "$RB_SH" set-section --run "$RUN" --section outcome \
  --value "Plan complete. ${TASK_COUNT} tasks queued in TASKS.md."
bash "$RB_SH" set-section --run "$RUN" --section status --value "complete"
NEXT_JSON_FILE="$(mktemp -t z-rb-next.XXXXXX.json)"
printf '%s\n' "$NEXT_JSON" > "$NEXT_JSON_FILE"
bash "$RB_SH" set-section --run "$RUN" --section next --json "$NEXT_JSON_FILE"
rm -f "$NEXT_JSON_FILE"
```

<!-- include: _fragments/run-brief-finalize.md -->

**Release the claim and deregister this run** (best-effort, non-fatal). Release BEFORE deregister so the lock frees first (minimizes the window where the registry shows the run gone but the lock is still held). Per the FINALIZE_STATUS rule (Setup step 5): normal completion deregisters with `complete`; if the fragment's `--require` step set `FINALIZE_STATUS=aborted`, deregister with `aborted` instead. Both calls return 0 by design and self-log on internal failure, so call both with `|| true`. If register failed earlier (no record was ever written), the deregister is a harmless no-op.
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

After planning, prefer a clear checkpoint over `/compact`: planning (Explore agents, decisions doc, consultant returns, SPEC/PLAN drafting) is the heaviest context burner in the harness. A watcher-readable checkpoint lets Oh My Pi/Hermes/MCP or the user clear before implementation starts; implementation subagents are fresh-context already, so no per-batch compact is needed.

## Run Brief — halt finalize

Before `deregister --status aborted` on any halt after `run-brief.sh init` (unless register failed — no deregister). Substitute `<reason>` in the outcome line. When no planning artifact exists yet, the shared fragment auto-downgrades to **lite** (Intent + Outcome + Next).

**Known gap:** halts before Setup step 5 (`run-brief.sh init`) — e.g. `workflow.slug_confirm` resolver `halt` during slug derivation — skip this block (no brief JSON yet).

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

<!-- include: _fragments/run-brief-finalize.md -->

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

## Telemetry reference

Event kinds emitted by `/z-plan` and its helpers. For full per-task event schema see `z-execute.md`.

| Event kind | When / meaning | Required fields |
|---|---|---|
| `run_start` | Planning run begins | version fields, `task`, `command` |
| `planning_mode_chosen` | Explicit Intent-vs-Full SDD mode gate resolved before the hard cost gate | `slug`, `mode`, `recommended_mode`, `source`, `reason`, `legacy_spec_forced` |
| `plan_route_decision` | Route check fired and a route was chosen | `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, `user_choice` |
| `plan_halt` | Run halted (e.g. `no_ask_blocked` on slug gate) | `reason`, `question_id`, `rule_id` |
| `askuser_skipped` | AskUserQuestion suppressed by resolver | `question_id`, `source` |
| `legacy_map_artifact_detected` | RESEARCH.md had no `artifact_kind` field and was treated as MAP.md terrain | — |
| `precontext_research_incomplete` | RESEARCH.md `status: incomplete`; run halted | — |
| `precontext_source_deleted` | A file cited in precontext artifact no longer exists | `path`, `artifact` |
| `precontext_freshness_check_failed` | Citation-regex parse failed for a precontext artifact | `artifact`, `reason` |
| `precontext_freshness_acknowledged` | User accepted stale precontext after consolidated 10c gate | `sources` (list of `"research"` / `"map"` / `"docs"`), `user_choice` |
| `doc_drift_acknowledged` | User accepted stale docs in the consolidated 10c gate | `stale_pct`, `stale_concepts` |
| `doc_drift` | doc-fetcher returned a DRIFT WARNING for a concept | `concept`, `claim`, `reality`, `file` |
| `task_classified` | complexity-classifier stamped a task block | `task`, `tier`, `reason` |
| `persona_bound` | Emitted per panel arm at Phase 3 and Phase 7 (5-panel path only) | `run_id`, `command`, `role`, `arm`, `selection_source`, `phase`; additionally `persona_id` + `draw_id` when `personas.critique_panel` drew a persona for that arm (`selection_source=random_role_pool_distinct`); vanilla arms omit those fields and carry `selection_source=fixed_panel` |
| `telemetry_anomaly` | `log-phase.sh` detected impossible `wall_ms` | `phase`, `reason` (`wall_ms_overflow` / `wall_ms_negative`), `t_start`, `t_end`, `computed_wall_ms` |
| `next_step_choice` | Phase 8.6 final handoff gate selection emitted (source: `phase_8_6_final_handoff_gate`) | `choice`, `source` |
| `sharpen_gate` | Phase 0 auto-sharpen gate decision | `decision` (`sharpened`\|`skipped`), `grill_md_existed` |
| `sharpen_skipped` | Phase 0 auto-sharpen step skipped (opt-out or not handoff input) | `reason` |
| `handoff_written` | Phase 8.5 handoff artifacts written to HANDOFF.md and handoff.json | `slug`, `path`, `artifact_kind`, `handoff_json`, `producer_output` |
| `handoff_json_validated` | Phase 8.5 verified the machine handoff before Phase 8.6 | `path`, `roles`, `context_file_count` |
| `plan_claim_lost_during_gate` | Heartbeat detected ownership change (exit 9) at a phase boundary or before a user gate; URGENT abort/continue-uncoordinated gate fires | `slug`, `run_id`, `phase` |
| `cost_gate_decision` | Exactly one terminal pre-subagent hard cost-gate decision per `/z-plan` run | `command`, `choice`, `estimated_tokens`, `confidence`, `basis`, `disposition`, `rule_id`, `range_high`, `choice_source`, `attempt_count` when known; optional sanitized `reason` |
| `cost_gate_reestimate_attempt` | Nonterminal cost reduction / re-estimate attempt; never counts as the terminal gate decision | `command`, `run_id`, `gate_id`, `attempt_index`, `changed_drivers`, `prior_range_high`, `new_range_high`, `disposition`, `terminal_event_kind`, terminal-correlation `gate_id` |
| `intent_level_chosen` | Mode detection resolved the planning depth level (via classifier, config-forced, flag, cost-gate reduction, or fallback) | `level`, `source` (`classifier` / `config-forced` / `flag` / `user-cost-reduction` / `user-override` / `fallback`), `reason` |
| `intent_level_override` | User overrode the classifier's chosen level via the inline announce gate | `level` (new), `prior_level`, `source` (`user-override`) |
| `consult_skipped` | Phase-3 or Phase-7 consult skipped; `reason` distinguishes `Z_HARNESS_CONSULT=off` / `intent_level_L1_quick` / `intent_level_L2_user_skipped` | `phase`, `reason`, optionally `intent_level` |
| `legacy_spec_detected` | Backward-compat guard: SPEC.md found in slug dir; `PLANNING_MODE` forced to `full` (Invariant 4) | `slug`, `spec_path`, `original_planning_mode` |
| `legacy_mode_active` | `PLANNING_MODE=full` branch entered (from --full flag, config, or SPEC detection) | `slug`, `reason` |
| `legacy_plan_exists` | Finished legacy plan (SPEC.md + TASKS.md) detected; user prompted to amend/implement/overwrite/abort | `slug`, `has_spec`, `has_tasks` |

---

## Operating principles

- **Premise first.** Challenge the request before planning around it.
- **Push back is structural** — every accepted recommendation needs an articulated "reason it might be wrong" before you accept it.
- **Always ask** when unclear.
- **Shortcuts only with explicit approval.**
- **DRY / KISS / SOLID** are non-negotiable.
- **Log everything.** Every consultation, approval, pushback, error — via `scripts/log-event.sh`.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 1a doc-fetcher Agent(); Phase 1b Explore Agent(); **Mode detection: intent-classifier Agent()** (when `planning_mode=intent` and `intent_level=auto`); Phase 3 consultant-primary/secondary Agent() calls or fixed 5-panel Agent() calls; Phase 7 pre-dispatch task-tree-generator guard when intent TASKS.md is absent; Phase 7 same consultant panel structure as Phase 3; Phase 8 complexity-classifier Agent() calls. When `personas.critique_panel=true` (and `experiment.persona_rotation=true`), each Phase 3 and Phase 7 arm is additionally prefixed with a drawn consultant persona — no extra Agent() calls, the prefix is injected into each arm's existing prompt. |
| `ask_user` | yes | Setup step 0 (empty arguments); Setup step 1 (slug collision + resolver prefill/ask branches); Setup step 5 claim acquire — CLAIM_RC 1 (live peer: proceed/abort/use-new-slug), CLAIM_RC 2 (stale-takeover: proceed/abort, default abort), CLAIM_RC 3 (corrupt: abort/proceed-uncoordinated, default abort); Setup step 10c (consolidated freshness gate — one AskUserQuestion covering docs / research / map / GRILL.md-citation staleness); **Pre-subagent hard cost gate** (guarded by `workflow.pre_run_cost_gate`, before `planning-router`, `intent-classifier`, doc-fetcher, Explore, consultants, and task-tree generation); **Mode detection: backward-compat SPEC detection — finished legacy plan gate** (amend / implement / continue / abort when SPEC.md+TASKS.md present); **Mode detection: intent level announce + override gate** (when `planning_mode=intent`; offers L1/L2/L3 override); **Mode detection: L2 optional consult gate** (when `INTENT_CONSULT_POLICY=optional` and not `Z_HARNESS_NO_ASK`); Phase 0 (premise concern); Phase 2.5 (decisions doc approval — guarded by `workflow.plan_decisions_approval` resolver); Phase 5 (design decision + shortcut approval); **Phase 6 (intent-mode only): acceptance-criterion lint failure gate — surfaces offending lines and offers rewrite or abandon** (when `planning_mode=intent` and lint finds non-observable criteria); Phase 8 (task-count overflow); heartbeat exit 9 at any phase boundary or pre-gate (`plan_claim_lost_during_gate` — abort/continue-uncoordinated, default abort). **Phase 9 no longer uses AskUserQuestion** — the next-step recommendation is emitted as prose only (handoff artifact + printed `/clear` + `/z-audit-plan <slug>` instruction). |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
