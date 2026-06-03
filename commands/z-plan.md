---
description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
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

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the question
     "What task should I plan?" to the user via their native channel and accept
     a text reply. Silent omission is forbidden. -->
**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for existing slug names across both new and legacy plan layouts. If a matching slug dir is found:
   - **Precontext-only slug dir** (only `MAP.md`, `BRAINSTORM.md`, and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug-collision
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
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must present the slug
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
4a. Export run id and resolve config:
    ```bash
    export Z_HARNESS_RUN="$RUN"
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

   **Active-plan registration (immediately after run_start).** Register this run in the shared registry. Graduated failure policy — never silent-continue on failure:
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
     --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan --phase plan \
     --session "$Z_HARNESS_SESSION_ID"
   REG_RC=$?
   ```
   - `REG_RC == 0` → registered; proceed.
   - `REG_RC == 3` (register FAILED — no record was written) → emit a loud `registry_error` event, then branch:
     - **Interactive** (not `Z_HARNESS_NO_ASK`) → `AskUserQuestion`: *proceed without coordination* / *abort*.
       - **proceed** → continue; skip heartbeats and deregister later (no record to update).
       - **abort** → do **NOT** call deregister (no record exists); push-notify and `exit 1`.
     - **Unattended (`Z_HARNESS_NO_ASK`)** → proceed without coordination and log prominently, UNLESS `Z_HARNESS_STRICT_OVERLAP=1` → halt (`exit 1`). No deregister either way (no record).
   - **Any OTHER nonzero** → treat as `REG_RC == 3`.
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
     "$(printf '{"op":"register","run_id":"%s","rc":%d}' "$RUN" "$REG_RC")"
   ```

   **FINALIZE_STATUS / deregister rule (single source of truth for the entire run):**
   > On any run-ending halt that occurs AFTER `REG_RC == 0` (a record exists), set `FINALIZE_STATUS=aborted` and call `deregister --status aborted` before exiting. On normal completion (Phase 9), leave `FINALIZE_STATUS` unset so Phase 9 deregisters with `complete`. If register failed (no record), do NOT deregister anywhere.

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
6. Notification policy is resolved from config via the `export-env` step above. See `docs/human/config.md` for knob details (`notify.level`).
7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
8. **Docs-freshness scan (inline, no gate yet).** Initialize signals before scanning: `docs_stale=false`, `research_stale=false`, `map_stale=false`; `stale_concepts_list=[]`; `stale_research_citations=[]`; `stale_map_citations=[]`. If `docs/llm/INDEX.json` exists, compute staleness across all its entries. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). Record signal: `docs_stale = (stale_pct >= threshold)`. Also record `stale_concepts_list` (list of stale concept slugs) for display. **Do not present any AskUserQuestion here** — the gate fires below in step 9c after all three signals are collected.
9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `MAP.md`, `BRAINSTORM.md`, and `RESEARCH.md`.

    **RESEARCH.md artifact_kind dispatch:** If `RESEARCH.md` exists, read its frontmatter `artifact_kind` and `status` fields first to determine the precontext mode:

    - **`artifact_kind: approach_synthesis` + `status: complete`** → **one-way gate active.** RESEARCH.md is canonical precontext. Skip MAP.md + BRAINSTORM.md injection entirely. Phase 1 uses matrix-based skip rules (see Phase 1 — RESEARCH.md one-way gate shortcut).
    - **`artifact_kind: map`** (legacy old-RESEARCH.md not yet renamed) → treat as a MAP.md artifact: apply freshness check (same regex/mtime logic as MAP.md below), then proceed with component-file injection (MAP.md + BRAINSTORM.md mode). Log `legacy_map_artifact_detected`.
    - **No `artifact_kind` field** → treat as legacy MAP.md artifact per above (component-file injection). Log `legacy_map_artifact_detected`.
    - **`status: incomplete`** → halt. Emit `precontext_research_incomplete`. Recommend re-running `/z-research` before proceeding. Per the FINALIZE_STATUS rule, set `FINALIZE_STATUS=aborted` and deregister before exiting:
      ```bash
      FINALIZE_STATUS=aborted
      python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
        --run-id "$RUN" --status aborted 2>/dev/null || true
      ```

    **Freshness scan — RESEARCH.md (inline, no gate yet)** (when one-way gate is active): parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). Record signal: `research_stale = true` if any citation is stale. Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) and set `research_stale = true`. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open). **Do not present any AskUserQuestion here** — the gate fires below in step 9c.

    **Freshness scan — MAP.md (inline, no gate yet)** (when one-way gate is inactive and MAP.md exists or RESEARCH.md is treated as MAP.md): parse all file citations using the same regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/` and extensionless allowlist (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to the MAP.md frontmatter `generated_at`; for line-ranges, use min-line mtime. Record signal: `map_stale = true` if any citation is stale. Deleted-source detection: emit `precontext_source_deleted` and set `map_stale = true`. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open). **Do not present any AskUserQuestion here** — the gate fires below in step 9c.

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the consolidated
     freshness gate covering docs / research / map staleness — all three signals
     merged into one AskUser call — when stale_pct >= threshold or any precontext
     citation is stale or deleted. Silent omission is forbidden. -->
    **9c. Consolidated freshness gate.** After all three scans complete, if `docs_stale OR research_stale OR map_stale` is true:

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

    If only one signal fired, the question naturally collapses to a single per-source bullet and two options (per-source remedy + proceed + abandon).

    On user choice:

    - **Re-run remedy**: Update `route-decision.md` with the user's chosen remedy. Emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: <the computed remedy from the route-decision.md step above>`, `route_class: "contextual"`, `reason_codes` (built above), `signals.docs_stale_or_drifted: <docs_stale>`, `signals.research_stale: <research_stale>`, `signals.map_stale: <map_stale>`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and `user_choice: <the user's selection>`. Halt. Do not auto-invoke the remedy command. Per the FINALIZE_STATUS rule, set `FINALIZE_STATUS=aborted` and deregister before exiting:
      ```bash
      FINALIZE_STATUS=aborted
      python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
        --run-id "$RUN" --status aborted 2>/dev/null || true
      ```
    - **Proceed with all stale**: Update `route-decision.md` to record "no remedy command selected — user accepted stale inputs." Emit `plan_route_decision` with `from_command: "/z-plan"`, **`to_command: null`** (omit the field or set it to `null` explicitly — `/z-stats` must be able to distinguish this from a real remedy), `route_class: "contextual"`, `reason_codes` (built above), `signals.docs_stale_or_drifted: <docs_stale>`, `signals.research_stale: <research_stale>`, `signals.map_stale: <map_stale>`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and `user_choice: "proceed_with_all_stale"`. Then:
      - If `docs_stale=true`: emit a `doc_drift_acknowledged` event. Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
      - If `research_stale=true OR map_stale=true` (regardless of `docs_stale`): emit a `precontext_freshness_acknowledged` event with `sources: ["research"]` / `["map"]` / `["research","map"]` as applicable.
      - Continue to Phase 1.
    - **Abandon**: Emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: null`, `route_class: "contextual"`, `reason_codes` (built above), `signals.docs_stale_or_drifted: <docs_stale>`, `signals.research_stale: <research_stale>`, `signals.map_stale: <map_stale>`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and `user_choice: "abandon"`. Halt. Per the FINALIZE_STATUS rule, set `FINALIZE_STATUS=aborted` and deregister before exiting:
      ```bash
      FINALIZE_STATUS=aborted
      python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
        --run-id "$RUN" --status aborted 2>/dev/null || true
      ```

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

Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `plan_validation_intent`, `plan_amend_intent`, `has_fix_artifact`, and `docs_stale_or_drifted`. Set `plan_validation_intent`/`plan_amend_intent` only when the user re-enters this command on a slug with `SPEC.md`+`PLAN.md`+`TASKS.md` all present (see `agents/planning-router.md` for the language-match heuristic).

Deterministic routes:
- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.

When the user chooses **switch** or **abandon** at the route gate (ending the run), per the FINALIZE_STATUS rule set `FINALIZE_STATUS=aborted` and deregister before exiting:
```bash
FINALIZE_STATUS=aborted
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status aborted 2>/dev/null || true
```

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.

---

## Phase 0 — Premise check

**Do not take the prompt's premises for granted.** If precontext artifacts were detected in Setup step 9, **inject their content here** as input to the premise check:
- **One-way gate active** (`artifact_kind: approach_synthesis`): inject RESEARCH.md content only (core hypothesis, approach decision matrix summary, mechanical rank-ordering). Do not inject MAP.md or BRAINSTORM.md.
- **One-way gate inactive** (component-file mode): inject MAP.md (or legacy RESEARCH.md treated as MAP.md) findings and BRAINSTORM.md chosen framing.

Do not re-derive context already covered by these artifacts.

Before any planning, ask:

- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
- Is there a materially better path the user hasn't considered?

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface any premise
     concern to the user via their native channel and await a response before
     proceeding. Silent omission is forbidden. -->
If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.

If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.

Checkpoint: `phase0-premise.md`.

## Phase 1 — Exploration

**RESEARCH.md one-way gate shortcut** (when `artifact_kind: approach_synthesis` + `status: complete` detected in Setup step 9): If RESEARCH.md is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately using the new RESEARCH.md schema (matrix + evidence gaps):

- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `## Approach decision matrix` section has ≥1 cell with `OK` or `RISKY` verdict citing a file in the task's likely-touched set.
- **Skip Explore** iff RESEARCH.md is non-stale AND its `## Evidence gaps` section is empty (no `UNVERIFIED` cells aggregated).

The four resulting cases (one-way gate active):
- **(a) Skip doc-fetcher only** — matrix has OK/RISKY cell citing a touched file but Evidence gaps non-empty → run Explore, skip doc-fetcher.
- **(b) Skip Explore only** — matrix has no OK/RISKY cell for touched files but Evidence gaps empty → run doc-fetcher, skip Explore.
- **(c) Skip both** — matrix has OK/RISKY cell for touched files AND Evidence gaps empty → skip both, proceed to Phase 2.
- **(d) Run both** — RESEARCH.md is stale, absent in gate-active mode, or meets neither skip condition → run both doc-fetcher and Explore.

**Legacy RESEARCH.md / component-file shortcut** (when one-way gate is inactive — MAP.md or legacy RESEARCH.md detected in Setup step 9): If MAP.md (or legacy RESEARCH.md treated as MAP.md) is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:

- **Skip doc-fetcher** iff MAP.md (or legacy RESEARCH.md) is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- **Skip Explore** iff MAP.md (or legacy RESEARCH.md) is non-stale AND its `Open questions:` section is empty.

The four resulting cases (gate inactive):
- **(a) Skip doc-fetcher only** — MAP.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
- **(b) Skip Explore only** — MAP.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
- **(c) Skip both** — MAP.md has findings for touched files AND no open questions → skip both, proceed to Phase 2.
- **(d) Run both** — MAP.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.

**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.

### 1a. Dispatch doc-fetcher (if INDEX.json exists)

If Setup step 7 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:

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
- `halt`: emit `plan_halt` event and exit cleanly — do NOT invoke `AskUserQuestion`. A subsequent `/z-plan` resume re-enters at Phase 2.5. Per the FINALIZE_STATUS rule, deregister before exiting (this halt occurs after a successful register):
  ```bash
  if [[ "$RESULT_DECISIONS" == "halt" ]]; then
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "${RUN:-z-plan}" plan_halt \
      "$(printf '{"reason":"no_ask_blocked","question_id":"workflow.plan_decisions_approval","rule_id":"no_ask_halt"}')"
    echo "halt: no_ask_blocked on workflow.plan_decisions_approval" >&2
    FINALIZE_STATUS=aborted
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status aborted 2>/dev/null || true
    exit 0
  fi
  ```
- `skip`: accept the decisions doc silently — no AskUserQuestion. Emit `askuser_skipped` event with `{question_id: "workflow.plan_decisions_approval", source: "$SOURCE_DECISIONS"}` and proceed to Phase 3.
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the decisions doc
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

**Consult-off guard.** Before spawning any consultant, check the runtime signal:

```bash
CONSULT_PROVIDER="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-provider.py" consultant_primary 2>/dev/null)"
```

If `CONSULT_PROVIDER == "none"` (i.e. `Z_HARNESS_CONSULT=off`):
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

## Phase 4 — Final clarifications

If anything is still unclear about scope, constraints, or success criteria — ask the user. No silent assumptions.

## Phase 5 — Present + approve

```bash
[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && <PushNotification: "Decisions ready for review.">
```

Present a **concise** decisions summary: one bullet per decision (what, why, what was rejected). Separate **Shortcuts** section: what's being skipped, robust alternative, cost of the shortcut.

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface each approval
     question (design decisions, shortcuts) via their native channel and await
     a response before proceeding. Silent omission is forbidden. -->
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
| MAP.md | $Z_HARNESS_PLAN_DIR/MAP.md | <iso timestamp or "n/a"> |
| BRAINSTORM.md | $Z_HARNESS_PLAN_DIR/BRAINSTORM.md | <iso timestamp or "n/a"> |
| RESEARCH.md | $Z_HARNESS_PLAN_DIR/RESEARCH.md | <iso timestamp or "n/a"> |
```

Include only rows for artifacts that were actually present. If none were present, write: `none — fresh /z-plan run.`

Create `$Z_HARNESS_PLAN_DIR/PLAN.md` — approved plan: goals, decisions (with rationale), non-goals, approved shortcuts, ordered phases.

Both obey **DRY / KISS / SOLID**. State explicitly how the plan respects each.

## Phase 7 — Bundled final review

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     requirement to the user and skip all Phase 7 consultant Agent() calls.
     Document the gap in the archive and proceed to Phase 8 without final
     review input. -->

**Consult-off guard.** Before spawning any consultant, check the runtime signal:

```bash
CONSULT_PROVIDER_P7="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-provider.py" consultant_primary 2>/dev/null)"
```

If `CONSULT_PROVIDER_P7 == "none"` (i.e. `Z_HARNESS_CONSULT=off`):
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

Spawn all 5 panel members in parallel, each handed the full SPEC.md + PLAN.md. Include `kernel_path: <KERNEL_PATH>` in each `Agent(prompt=...)` when `KERNEL_PATH` is non-empty (resolved in Setup). All 5 arms receive: "Critique this plan. What's wrong, missing, or fragile?" Prepend the arm's Phase 7 persona body to the prompt when available — empty string when vanilla. Cursor arms pass their model via `--model <model>`:

- `Agent(subagent_type="agy", description="Phase 7 final review — gemini arm", prompt="<P7_GEMINI_PREFIX>Critique this plan...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`
- `Agent(subagent_type="cursor", model="claude-4.6-sonnet", description="Phase 7 final review — claude-sonnet arm", prompt="<P7_SONNET_PREFIX>Critique this plan...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`
- `Agent(subagent_type="cursor", model="grok-4.3", description="Phase 7 final review — grok arm", prompt="<P7_GROK_PREFIX>Critique this plan...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`
- `Agent(subagent_type="cursor", model="composer-2.5", description="Phase 7 final review — composer arm", prompt="<P7_COMPOSER_PREFIX>Critique this plan...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`
- `Agent(subagent_type="codex-cli", description="Phase 7 final review — codex-5.5 arm", prompt="<P7_CODEX_PREFIX>Critique this plan...\n[kernel_path: <KERNEL_PATH>  ← omit when KERNEL_PATH is empty]")`

Each `<P7_*_PREFIX>` is the persona body followed by a blank line, or **empty** when that arm drew no persona (underflow slot, `CRITIQUE_PANEL` off, or `PERSONA_ROTATION` off) — in the empty case the prompt is byte-identical to the pre-feature dispatch.

If `PERSONA_ROTATION == "false"`, fall back to the standard 2-consultant behavior: spawn both consultants in parallel, each handed the full SPEC.md + PLAN.md. Include `kernel_path: <KERNEL_PATH>` in each `Agent(prompt=...)` when `KERNEL_PATH` is non-empty (resolved in Setup):
- consultant-primary: "Critique this plan. What's wrong, missing, or fragile?"
- consultant-secondary: same.

Apply findings that hold up under "one reason this might be wrong" scrutiny. Push back on the rest with documented reasoning.

## Phase 8 — TASKS.md

Create `$Z_HARNESS_PLAN_DIR/TASKS.md`. Break PLAN.md into small, independently-implementable tasks. Each: `T001`-style ID, title, files touched, dependencies, acceptance criteria, status `[ ]`. Size so each fits a fresh context window.

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the task-count
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
If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).

**Scope seed (immediately after TASKS.md + complexity stamps are finalized).** Dispatch the `scope-extractor` (Haiku) subagent to seed the plan's file scope into the registry so a concurrent `/z-implement-all` can see what this plan intends. Best-effort, non-fatal — `update-scope` self-logs `registry_error` on failure:

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

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the next-step
     recommendation choice (/z-audit-plan / /z-test / /z-implement-all / skip)
     via their native channel. Silent omission is forbidden. -->
Then surface the same choice interactively via `AskUserQuestion` so users who don't read OS notifications still see it. Phrase the question as "Plan complete. What's next?" with these four options (the `AskUserQuestion` four-option cap is why the two plan audits share one option — the push-notification above still lists them separately): `/z-audit-plan` (label: `Audit the plan (recommended)` — recommended cheap pre-implementation reality check against the codebase; the description also points the user at `/z-audit-plan-style` for the companion MR-style quality pass on the plan artifacts), `/z-test` (label: `Draft semantic test cases` — recommended only for risky/financial code), `/z-implement-all` (label: `Start implementation now` — only when user has high confidence in the plan), `Skip — I'll decide later`. Default selection is `/z-audit-plan`. The user's choice is advisory — log it as a `next_step_choice` event but do not auto-dispatch the chosen command; the user invokes it themselves so they retain control of context boundaries (e.g. running `/compact` between phases).

**Deregister this run** from the active-plan registry (best-effort, non-fatal). Per the FINALIZE_STATUS rule (Setup step 5): normal completion deregisters with `complete`. The `deregister` subcommand returns 0 by design and self-logs a `registry_error` on internal failure, so call it with `|| true`. If register failed earlier (no record was ever written), this is a harmless no-op.
```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status "${FINALIZE_STATUS:-complete}" || true   # CLI self-logs registry_error on failure
```

The `/compact` recommendation is important: the planning phase (Explore agents, decisions doc, consultant returns, SPEC/PLAN drafting) is the heaviest context burner in the harness. Compacting at this boundary frees ~MB of main-thread context before implementation kicks off. Subagents during implementation are fresh-context already, so no per-batch compact is needed.

The `/z-test` step is optional but high-value when the plan touches money, ordering, signal generation, or any other domain where mechanical correctness (which `/z-implement-all`'s reviewer catches) is not enough to catch semantic bugs (notional sign flips, feature schema mismatches, unit confusion). It produces a `TESTS.md` artifact that `/z-implement-all`'s implementer subagent reads alongside TASKS.md, so test code lands in the same diff as the production code it exercises.

---

## Telemetry reference

Event kinds emitted by `/z-plan` and its helpers. For full per-task event schema see `z-implement-all.md`.

| Event kind | When / meaning | Required fields |
|---|---|---|
| `run_start` | Planning run begins | version fields, `task`, `command` |
| `plan_route_decision` | Route check fired and a route was chosen | `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, `user_choice` |
| `plan_halt` | Run halted (e.g. `no_ask_blocked` on slug gate) | `reason`, `question_id`, `rule_id` |
| `askuser_skipped` | AskUserQuestion suppressed by resolver | `question_id`, `source` |
| `legacy_map_artifact_detected` | RESEARCH.md had no `artifact_kind` field and was treated as MAP.md terrain | — |
| `precontext_research_incomplete` | RESEARCH.md `status: incomplete`; run halted | — |
| `precontext_source_deleted` | A file cited in precontext artifact no longer exists | `path`, `artifact` |
| `precontext_freshness_check_failed` | Citation-regex parse failed for a precontext artifact | `artifact`, `reason` |
| `precontext_freshness_acknowledged` | User accepted stale precontext after consolidated 9c gate | `sources` (list of `"research"` / `"map"` / `"docs"`), `user_choice` |
| `doc_drift_acknowledged` | User accepted stale docs in the consolidated 9c gate | `stale_pct`, `stale_concepts` |
| `doc_drift` | doc-fetcher returned a DRIFT WARNING for a concept | `concept`, `claim`, `reality`, `file` |
| `task_classified` | complexity-classifier stamped a task block | `task`, `tier`, `reason` |
| `persona_bound` | Emitted per panel arm at Phase 3 and Phase 7 (5-panel path only) | `run_id`, `command`, `role`, `arm`, `selection_source`, `phase`; additionally `persona_id` + `draw_id` when `personas.critique_panel` drew a persona for that arm (`selection_source=random_role_pool_distinct`); vanilla arms omit those fields and carry `selection_source=fixed_panel` |
| `telemetry_anomaly` | `log-phase.sh` detected impossible `wall_ms` | `phase`, `reason` (`wall_ms_overflow` / `wall_ms_negative`), `t_start`, `t_end`, `computed_wall_ms` |
| `next_step_choice` | User picked a next step at Phase 9 | `choice` |

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
| `subagent` | yes | Phase 1a doc-fetcher Agent(); Phase 1b Explore Agent(); Phase 3 consultant-primary/secondary Agent() calls (2-consultant fallback when `experiment.persona_rotation=false`) or fixed 5-panel Agent() calls (agy, cursor@claude-4.6-sonnet, cursor@grok-4.3, cursor@composer-2.5, codex-cli — when `experiment.persona_rotation=true`); Phase 7 same panel structure as Phase 3; Phase 8 complexity-classifier Agent() calls. When `personas.critique_panel=true` (and `experiment.persona_rotation=true`), each Phase 3 and Phase 7 arm is additionally prefixed with a drawn consultant persona — no extra Agent() calls, the prefix is injected into each arm's existing prompt. |
| `ask_user` | yes | Setup step 0 (empty arguments); Setup step 1 (slug collision + resolver prefill/ask branches); Setup step 9c (consolidated freshness gate — one AskUserQuestion covering docs / research / map staleness); Phase 0 (premise concern); Phase 2.5 (decisions doc approval — guarded by `workflow.plan_decisions_approval` resolver); Phase 5 (design decision + shortcut approval); Phase 8 (task-count overflow); Phase 9 (next-step recommendation choice) |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
