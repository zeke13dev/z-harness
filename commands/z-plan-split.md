---
description: Pre-emptive scope splitter — fan a big topic out into N narrow cluster-planner subagents in parallel, then reconcile file-path overlaps into SHARED-CONCERNS.md + MANIFEST.md.
argument-hint: <topic> [--slug=<root-slug>] [--clusters="a,b,c"]
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running the **z-harness `/z-plan-split`** pipeline.

Topic + flags (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the question "What topic should I split?" via their native channel. Silent omission is forbidden. -->
**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I split?". Wait for their reply. Treat the reply as the topic and continue.

`/z-plan-split` is a **pre-emptive scope splitter** for topics that would otherwise produce a sprawling ≥40-task `/z-plan` run. Instead of one mega-plan, it dispatches N parallel `cluster-planner` subagents (each producing a focused 5-15-task plan), then writes `SHARED-CONCERNS.md` (file-overlap observation, ack-gated) and `MANIFEST.md` (cluster listing + run order). It does NOT produce production code. One-level recursion only — nested MANIFESTs are explicitly out of scope.

## Setup

1. **Derive root slug.**
   - If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim.
   - Else if `$ARGUMENTS` contains `--clusters="a,b,c"`, the slug is auto-derived from the topic (kebab-case, 2-4 words). The `--clusters` flag overrides Phase 1's automatic proposal.
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug-confirmation question (when non-obvious) via their native channel. Silent omission is forbidden. -->
   - Otherwise auto-derive from the topic (kebab-case, 2-4 words). If non-obvious, confirm via `AskUserQuestion`.
2. **Validate the slug (mandatory — security gate).** The slug is interpolated into filesystem paths and must be a single safe segment. Reject (refuse with a clear error and exit cleanly) if the slug:
   - is empty or whitespace-only;
   - contains any character outside `[a-z0-9-]` (kebab-case only — no `/`, `\`, spaces, `:`, `..`, `~`, `$`, quotes, etc.);
   - contains `..` anywhere (even as a substring);
   - starts with `-` or `.`, or ends with `-`;
   - contains `//` or path separators of any kind.

   Concretely: the slug must match the anchored regex `^[a-z0-9]+(-[a-z0-9]+)*$`. Reject values like `../x`, `foo/bar`, `.hidden`, `a b`, empty string, `a..b`. Error message: `"Invalid slug: must be a single kebab-case segment matching ^[a-z0-9]+(-[a-z0-9]+)*$ (no slashes, dots, or path traversal). Got: <value>"`. Do not fall through to a sanitized version; force the user to re-invoke with a valid slug.
3. **Export** `Z_HARNESS_SLUG=<root-slug>` for all subsequent shell calls and subagents — this namespaces every output path under `z-harness/<root-slug>/`.
4. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
5. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
6. **Existing slug-dir handling.** Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for existing slug names across both new and legacy plan layouts. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the existing-slug decision (overwrite / abort) via their native channel. Silent omission is forbidden. -->
   - **overwrite** — move the **entire prior tree** (every file and subdirectory under `$Z_HARNESS_PLAN_DIR/` *except* the just-created `archive/<RUN>/` directory itself) into `$Z_HARNESS_PLAN_DIR/archive/<RUN>/prior-tree/`. This includes the old `MANIFEST.md`, `SHARED-CONCERNS.md`, all prior `<cluster-slug>/` subdirectories, and any other stale artifacts — so no stale cluster trees survive into the new run. Implementation sketch: `mkdir -p $Z_HARNESS_PLAN_DIR/archive/<RUN>/prior-tree && find $Z_HARNESS_PLAN_DIR/ -mindepth 1 -maxdepth 1 ! -name archive -exec mv {} $Z_HARNESS_PLAN_DIR/archive/<RUN>/prior-tree/ \;` (move any existing `archive/previous-*` subdirs separately if needed). Then start fresh.
   - **abort** — exit cleanly with no changes. Per the Early-exit telemetry contract, emit `plan_split_run_end` with `status: "aborted_existing_tree"` before returning (no `phase_end` — no phase is active yet at Setup time).
   No "append" option (D10 — append flow was under-specified; drop it).
7. **Version stamp + log run start.** Merge the version blob with the topic and emit `plan_split_run_start` with `topic_chars`:
   ```bash
   export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1])
   v["topic"] = sys.argv[2]
   v["topic_chars"] = len(sys.argv[2])
   v["session_id"] = sys.argv[3]
   v["command"] = "z-plan-split"
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<topic-text>" "$Z_HARNESS_SESSION_ID")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_split_run_start "$START_PAYLOAD"
   ```
   Output lands under `z-harness/<root-slug>/archive/$RUN/events.jsonl`.

   **Active-plan registration (immediately after plan_split_run_start).** Register this run in the shared registry. Graduated failure policy — never silent-continue on failure:
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
     --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-plan-split --phase split \
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

   **FINALIZE_STATUS rule:** On any run-ending halt after `REG_RC == 0`, set `FINALIZE_STATUS=aborted` + `deregister --status aborted`. On normal completion (Phase 5), deregister with `complete`. If register failed, do NOT deregister.

8. Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).
9. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, do NOT read it from main thread. Note its existence; Phase 1 may dispatch `doc-fetcher` (Haiku) for one-shot topic grounding. Skip the docs-freshness gate — this command does not itself touch INDEX.json; cluster-planners handle their own doc reads.
10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.

**All paths in subsequent phases live under `z-harness/<root-slug>/`:**
- `z-harness/<root-slug>/MANIFEST.md`
- `z-harness/<root-slug>/SHARED-CONCERNS.md`
- `z-harness/<root-slug>/<cluster-slug>/{SPEC.md,PLAN.md,TASKS.md}` (one per cluster — directory uses the kebab-case `cluster_slug`)
- `z-harness/<root-slug>/archive/<RUN>/...`

## Cluster identity (terminology — used consistently below)

Every cluster has **two distinct stable fields**:

- **`cluster_id`** — a short, stable, opaque handle of the form `C1`, `C2`, …, `CN`, assigned in confirmation order. Used in **telemetry payloads** (every event's `cluster_id` field), MANIFEST table's first column, and cross-references in SHARED-CONCERNS.md (`Touched by: <cluster_id> (<task_id>)`). Never used as a path segment.
- **`cluster_slug`** — the kebab-case name the user (or the auto-proposer) chose, e.g. `auth-refactor`. Must independently match `^[a-z0-9]+(-[a-z0-9]+)*$` (same validator as the root slug, step 2). Used as the **on-disk directory name** under `z-harness/<root-slug>/<cluster_slug>/`. Never used in telemetry payloads.

Where this doc previously wrote `<cluster-id>` in a filesystem path, read it as `<cluster_slug>`. Where this doc writes a `cluster_id` field in a JSON payload, it is the `C1`/`C2` form. MANIFEST.md rows include both: `ID` column = `cluster_id`, `Path` column = `<root-slug>/<cluster_slug>/`.

## Early-exit telemetry contract (mandatory for every exit path)

**Every** exit from this command — successful, refused, aborted, paused, or failed — MUST emit the matching `phase_end` for the currently-active phase (if any) **and** a single `plan_split_run_end` event before returning. The `status` field on `plan_split_run_end` distinguishes the exit reason. No exit path may silently skip these events; the post-run analyzer relies on `plan_split_run_end` always being present.

Allowed `status` values on `plan_split_run_end`:

- `ready` — Phase 5 finalized with all clusters ready.
- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
- `abandoned_by_user` — user picked "Abandon" in Phase 1d (or "Abandon this cluster" elided the last surviving cluster).
- `aborted_existing_tree` — user picked "abort" at the existing-slug prompt (Setup step 6). No `phase_end` to emit (no phase active yet).
- `aborted_too_few_clusters` — Phase 1 refused (<2 seams). Emit `phase_end` for Phase 1 first.
- `aborted_too_many_clusters` — Phase 1 refused (>6 seams). Emit `phase_end` for Phase 1 first.
- `aborted_invalid_slug` — Setup step 2 / 10 rejected the slug or a cluster name. No `phase_end` (no phase active yet).
- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.

Payload shape for early exits (when full counts aren't available yet, use `null` or `0`):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_split_run_end \
  "$(printf '{"command":"z-plan-split","status":"%s","total_clusters":%s,"clusters_ready":%s,"clusters_failed":%s,"overlap_count":%s,"partial_tree":%s,"reason":"%s"}' \
     "$STATUS" "${N:-0}" "${K:-0}" "${F:-0}" "${O:-0}" "${PT:-false}" "$REASON_SHORT")"
```

## Phase telemetry (mandatory)

At the **start** of each phase (1 through 5), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so post-run analysis can separate machine time from human-wait time:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 1 — Cluster proposal

Main thread only. **Do NOT spawn a subagent** — cluster proposal is small-context and benefits from sitting alongside the topic.

### 1a. Optional doc grounding (if INDEX.json exists, Setup step 9)

If `docs/llm/INDEX.json` exists, dispatch ONE `doc-fetcher` (Haiku) call for topic grounding:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip the Agent() call. The doc-fetcher grounds Phase 1 cluster naming; drivers that skip it should warn the user that doc context is unavailable. -->
```
Agent(
  subagent_type="doc-fetcher",
  description="Doc context for <root-slug>",
  prompt="query: <one-sentence summary of the topic>\nrepo_root: <abs path>\ndepth: standard"
)
```

If it emits a `DRIFT WARNING`, log a `doc_drift` event per affected concept. Use its synthesis to inform cluster naming. If it returns `STATUS: no_docs` / `no_match`, proceed without doc grounding.

### 1b. Propose 2-6 clusters

Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes**, each as:

- A **kebab-case name** (this becomes the cluster slug + directory name, e.g. `auth-refactor`).
- A **1-line scope description** stating what the cluster IS responsible for and what it is NOT (handoff boundary with siblings).

**Hard limits:**
- If fewer than 2 distinct seams surface, **refuse** the split: print "Topic does not warrant /z-plan-split — only 1 coherent seam found. Run /z-plan <topic> directly." Then emit `phase_end` for Phase 1 and `plan_split_run_end` with `status: "aborted_too_few_clusters"` (per the Early-exit telemetry contract), and exit cleanly. Do not write MANIFEST.md. Per the FINALIZE_STATUS rule, set `FINALIZE_STATUS=aborted` and deregister before exiting:
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  ```
- If more than 6 seams surface, **refuse** the split: print "Topic too broad — >6 seams found. Narrow the topic and re-invoke, or accept a coarser split." Then emit `phase_end` for Phase 1 and `plan_split_run_end` with `status: "aborted_too_many_clusters"`, and exit cleanly. Per the FINALIZE_STATUS rule, set `FINALIZE_STATUS=aborted` and deregister before exiting:
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  ```

If `--clusters="a,b,c"` was passed in Setup step 10, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 10). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `has_existing_plan`, `plan_validation_intent`, `plan_amend_intent`, `docs_stale_or_drifted`, and the current route chain. Set `plan_validation_intent`/`plan_amend_intent` only when the user re-enters this command on a slug with `SPEC.md`+`PLAN.md`+`TASKS.md` all present (see `agents/planning-router.md` for the language-match heuristic).

Deterministic routes:
- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-map` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_terrain_map"]`).
- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-map` with `reason_codes: ["needs_terrain_map"]`.
- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.

Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-map` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.

When the user chooses **switch** or **abandon** at the route gate (ending the run), per the FINALIZE_STATUS rule set `FINALIZE_STATUS=aborted` and deregister before exiting:
```bash
FINALIZE_STATUS=aborted
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status aborted 2>/dev/null || true
```

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

### 1c. Write proposal artifact

Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cluster_proposed \
  "$(printf '{"cluster_id":"%s","cluster_name":"%s","scope":%s}' \
     "$CLUSTER_ID" "$CLUSTER_NAME" "$(printf '%s' "$SCOPE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
```

### 1d. User confirmation

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the cluster-confirmation question (approve / edit / abandon) via their native channel. Silent omission is forbidden. -->
Bracket the wait with `user_wait_start` / `user_wait_end`. Use `AskUserQuestion` with previews — one option per proposed cluster (preview = `<name>: <scope>`), plus three meta-options:

- **Approve as proposed** — proceed to Phase 2 with the listed clusters.
- **Edit** — free-text follow-up; user can rename clusters, rewrite scopes, add/drop clusters (still bounded 2-6).
- **Abandon** — exit cleanly with no further work. Per the Early-exit telemetry contract: emit `phase_end` for Phase 1 first, then `plan_split_run_end` with `status: "abandoned_by_user"` and a short `reason` (e.g. `user_abandoned_phase1`). Per the FINALIZE_STATUS rule, set `FINALIZE_STATUS=aborted` and deregister before exiting:
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  ```

If the user picks **Edit**, re-loop Phase 1c after applying their edits (re-write `proposed-clusters.md`, re-confirm). Maximum 3 edit iterations to avoid pathological loops — after that, ask the user to abandon or commit.

### 1e. Write confirmed-clusters artifact

After approval, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/confirmed-clusters.md` with the final cluster list (name + scope, one block per cluster, fixed display order matching MANIFEST run-order). For each confirmed cluster, log:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cluster_confirmed \
  "$(printf '{"cluster_id":"%s","confirmed_clusters_total":%d}' "$CLUSTER_ID" "$TOTAL")"
```

Send a `PushNotification` if notify.level is `approval_only` or `all` (see [docs/human/config.md](docs/human/config.md)).

---

## Phase 1.5 — Pre-fanout cost gate

This phase runs after Phase 1 cluster confirmation (N is now known) and before Phase 2 dispatch.

Record `T0=$(date +%s%3N)` and `USER_WAIT_MS_THIS_PHASE=0` at phase start.

`N_CLUSTERS` is the count of confirmed clusters from Phase 1d/1e (the length of the confirmed cluster list).

Call the shared gate helper with the confirmed cluster count:

```bash
GATE_JSON="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/pre-run-cost-gate.sh" \
  z-plan-split hard "$RUN" --dispatch "per_cluster=$N_CLUSTERS")"
GATE_DISPOSITION="$(printf '%s' "$GATE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["disposition"])')"
GATE_HUMAN_BLOCK="$(printf '%s' "$GATE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["human_block"])')"
GATE_EST_TOKENS="$(printf '%s' "$GATE_JSON" | python3 -c 'import json,sys; e=json.load(sys.stdin)["estimate"]; print(e.get("estimated_tokens",0))')"
GATE_CONFIDENCE="$(printf '%s' "$GATE_JSON" | python3 -c 'import json,sys; e=json.load(sys.stdin)["estimate"]; print(e.get("confidence","low"))')"
GATE_BASIS="$(printf '%s' "$GATE_JSON" | python3 -c 'import json,sys; e=json.load(sys.stdin)["estimate"]; print(e.get("basis","unknown"))')"
```

Print the estimate block to the user:

```
$GATE_HUMAN_BLOCK
```

Branch on `$GATE_DISPOSITION`:

- **`auto_proceed`**: log `cost_gate_decision` with `choice: auto_proceed` and continue.
- **`halt`**: log `cost_gate_decision` with `choice: halt`, emit `plan_split_run_end status: aborted_by_user` + deregister, and exit.
- **`unhandled_gate`**: treat as `halt` (log + exit).
- **`ask`**: present AskUser gate below.

<!-- RUNTIME-GATE: ask_user; workflow.pre_run_cost_gate; non-supporting drivers must surface the cost gate (proceed / abandon) via their native channel. Silent omission is forbidden. -->
When `GATE_DISPOSITION == "ask"`, bracket the wait with `user_wait_start` / `user_wait_end` and present `AskUserQuestion`:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start \
  '{"phase":"1.5","reason":"cost_gate"}'
_WAIT_T0=$(date +%s%3N)
```

> **Cost gate for `/z-plan-split`**
>
> $GATE_HUMAN_BLOCK
>
> This run will dispatch $N_CLUSTERS cluster-planner(s) in parallel. Proceed?
> 1. **Proceed** — continue to Phase 2 (parallel cluster-planner dispatch)
> 2. **Abandon** — exit cleanly, write nothing further

```bash
USER_WAIT_MS_THIS_PHASE=$(( USER_WAIT_MS_THIS_PHASE + $(date +%s%3N) - _WAIT_T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end \
  "$(printf '{"phase":"1.5","wall_ms":%d}' "$(( $(date +%s%3N) - _WAIT_T0 ))")"
```

Handle response:

- **Proceed**: log `cost_gate_decision` and continue.
- **Abandon**: log `cost_gate_decision` with `choice: abandon`, then per the Early-exit telemetry contract emit `phase_end` for Phase 1.5, then `plan_split_run_end` with `status: "abandoned_by_user"`, deregister, and exit:

  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_split_run_end \
    "$(printf '{"command":"z-plan-split","status":"abandoned_by_user","total_clusters":%d,"clusters_ready":0,"clusters_failed":0,"overlap_count":0,"partial_tree":false,"reason":"cost_gate_abandoned"}' "$N_CLUSTERS")"
  ```

In all non-abandon branches, emit `cost_gate_decision` (after `user_wait_end` for the `ask` path, or immediately for `auto_proceed`/`halt`):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
  "$(printf '{"command":"z-plan-split","choice":"%s","estimated_tokens":%d,"confidence":"%s","basis":"%s"}' \
     "<proceed|abandon|auto_proceed|halt>" "$GATE_EST_TOKENS" "$GATE_CONFIDENCE" "$GATE_BASIS")"
```

Log phase end:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":"1.5","name":"pre-fanout-cost-gate","wall_ms":%d,"user_wait_ms":%d}' \
     "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

---

## Phase 2 — Parallel cluster-planner dispatch

Spawn **all N cluster-planners in parallel in a single message**. Each receives the **identical** root-topic context + the full sibling-cluster list (so each leaf knows what its siblings own and can stay in-scope).

For each confirmed cluster, build the prompt:

```
<topic context — verbatim from $ARGUMENTS>

Sibling clusters (for scope-boundary awareness):
- C1 <name>: <scope>
- C2 <name>: <scope>
- ...

cluster-id: <Cn>
cluster-name: <name>
cluster-scope: <scope>
root-slug: <root-slug>
output-path: z-harness/<root-slug>/<cluster-id>/
run-id: <RUN>
repo-root: <abs path to repo root>
```

Dispatch (single message, N parallel calls):

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch requirement to the user and skip all Agent() calls. The cluster-planner subagents produce the per-cluster SPEC/PLAN/TASKS; drivers that skip them must warn the user that cluster planning is unavailable. -->
```
Agent(
  subagent_type="cluster-planner",
  description="Plan cluster <cluster-id> for <root-slug>",
  prompt="<assembled prompt per above>"
)
```

Each cluster-planner brackets itself with `cluster_planner_start` / `cluster_planner_end` events (the subagent owns those). No further main-thread events fire during Phase 2 dispatch — the subagent telemetry is the bracket.

---

## Phase 3 — Collect leaf returns + handle decision gates

For each cluster-planner return, branch on `STATUS:`:

- **`STATUS: ok`** → mark cluster `ready` in the in-memory MANIFEST state with `attempts: 1`. Record `final_status_at: <UTC ISO>`. Stash the returned `FILES_TOUCHED` JSON array for Phase 4 reconciliation.

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface cluster decision-needed questions (options + abandon) via their native channel. Silent omission is forbidden. -->
- **`STATUS: decision_needed`** → halt only this cluster (siblings continue / are already done). Parse the structured payload (`DECISION_ID`, `QUESTION`, `OPTIONS`, `RECOMMENDED_OPTION`, `IMPACT`, `AFFECTED_FILES`). Bracket the wait with `user_wait_start` / `user_wait_end`. Present to the user via `AskUserQuestion`:
  - **One option per entry in `OPTIONS`**, using each entry's `label` and `description` verbatim. List `RECOMMENDED_OPTION` first (if not `none`).
  - Plus a meta-option **Abandon this cluster** — marks it `failed` with `failure_reason: user_abandoned_decision`.

  Append the question + chosen option + rationale to `$Z_HARNESS_PLAN_DIR/<cluster-id>/archive/$RUN/decisions-late.md`, and echo into MANIFEST's `## Resolved decisions` section. Then re-spawn the cluster-planner with a `RESOLVED_DECISION:` block in the prompt (decision_id, chosen_option, rationale). Increment `attempts` for that cluster. **Sibling clusters continue / their results are unaffected.**

- **`STATUS: spec_problem`** → mark cluster `failed` with `failure_reason: spec_problem`. Surface to user via push-notify (no halt). Other clusters continue.

- **`STATUS: anti_nesting_violation`** → mark cluster `failed` with `failure_reason: anti_nesting_violation`. Log `anti_nesting_violation` event with `ancestor_manifest_path` from the payload. Other clusters continue.

- **`STATUS: unable_to_complete`** → mark cluster `failed` with `failure_reason: unable_to_complete`. Other clusters continue.

For every `failed` cluster, emit:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cluster_failed \
  "$(printf '{"cluster_id":"%s","failure_reason":"%s"}' "$CLUSTER_ID" "$REASON")"
```

**Total-failure gate.** If **all** clusters end in a `failed` state, halt: emit:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" total_cluster_failure \
  "$(printf '{"cluster_ids":%s}' "$ALL_FAILED_IDS_JSON")"
```

…push-notify the user, write a minimal MANIFEST.md (`status: failed`, no SHARED-CONCERNS.md). Then per the Early-exit telemetry contract: emit `phase_end` for Phase 3, followed by `plan_split_run_end` with `status: "total_cluster_failure"`, then exit. Do not proceed to Phase 4.

If ≥1 cluster is `ready`, proceed to Phase 4 — partial trees are valid.

---

## Phase 4 — Reconciliation (file-overlap detection)

**TASKS.md is canonical.** For each `ready` cluster, parse its `TASKS.md` and extract every `**Files:**` line. Build the canonical files-per-cluster set.

**Validation.** Compare each cluster's TASKS.md-parsed set against the `FILES_TOUCHED` JSON array the cluster-planner returned (the fast-path summary). If they disagree (after path normalization, see below), mark the cluster `failed` and emit:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cluster_files_inconsistent \
  "$(printf '{"cluster_id":"%s","files_touched_set":%s,"tasks_md_files_set":%s,"mismatch":%s}' \
     "$CLUSTER_ID" "$FT_JSON" "$TM_JSON" "$DIFF_JSON")"
```

Re-evaluate the total-failure gate after any newly-failed cluster. If after Phase 4 file-inconsistency checks **all** clusters are failed, halt exactly as Phase 3 would: emit `cluster_failed` events (already done), then `total_cluster_failure`, then `phase_end` for Phase 4, then `plan_split_run_end` with `status: "total_cluster_failure"`, then exit (no SHARED-CONCERNS.md; minimal MANIFEST with `status: failed`).

**Re-validation cascade (mandatory after any Phase 4 demotion).** Demoting a previously-ready cluster to `failed` invalidates the overlap index that was built from the full ready set. Before writing any Phase 5 artifact, **rebuild the overlap index from scratch using only the clusters whose status is still `ready` after Phase 4 demotions**:

1. Drop the entire in-memory `path → [(cluster_id, task_id, task_title), ...]` index.
2. Re-iterate the (post-demotion) ready set, re-parse each cluster's `TASKS.md` `**Files:**` lines, re-normalize, and re-insert into a fresh index.
3. Recompute `overlap_count` (count of paths with ≥2 distinct `cluster_id` entries).
4. Recompute `partial_tree` (`true` iff any cluster has status != `ready`, which includes the freshly-demoted ones).
5. Re-emit `overlap_detected` events from the rebuilt index (the prior events from the stale index are now superseded — log a single `overlap_index_rebuilt` event with payload `{"demoted_cluster_ids": [...], "new_overlap_count": <N>}` so the post-run analyzer can reconcile).

Only after the rebuild may Phase 5 write `SHARED-CONCERNS.md`, populate `overlap_count` / `partial_tree`, and set MANIFEST `status`. Skipping the rebuild would write stale overlap data that references files contributed by a now-failed cluster.

**Path normalization (mandatory, applied to BOTH FILES_TOUCHED entries and TASKS.md `**Files:**` entries):**

1. Strip leading `/` or `./`.
2. Collapse `.` and `..` segments (e.g. `a/./b` → `a/b`; `a/b/../c` → `a/c`).
3. Normalize separator to `/`.
4. **Reject** paths that escape the repo root (`..` walks past origin after collapsing) — log a `precontext_freshness_check_failed`-style event and exclude that path from overlap detection (do not fail the cluster on this alone — only on FILES_TOUCHED↔TASKS.md disagreement).

After normalization, build the cross-cluster path index: `path → [(cluster_id, task_id, task_title), ...]`.

**Severity heuristics (cascading precedence — first match wins).** Files touched by exactly 1 cluster are severity `none` and **excluded** from SHARED-CONCERNS.md entirely.

1. **high** — file matches `.*\.(sql|migration|schema|toml|yaml|yml|proto)$`, OR basename is in the extension-less / dependency-manifest allowlist: `Dockerfile`, `Makefile`, `package.json`, `package-lock.json`, `Cargo.lock`, `pnpm-lock.yaml`, `yarn.lock`. Wins regardless of cluster count (so `package.json` touched in 2 clusters is `high`, not `low`; same for any lockfile).
2. **medium** — file matches `.*\.(rs|py|ts|tsx|js|jsx)$` AND appears in **≥3** clusters.
3. **low** — file matches `.*\.(rs|py|ts|tsx|js|jsx)$` AND appears in **exactly 2** clusters.
4. **low** — anything else with ≥2 cluster touches (catch-all).

For each detected overlap, emit:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" overlap_detected \
  "$(printf '{"file_path":"%s","cluster_ids":%s,"severity":"%s"}' "$PATH" "$CIDS_JSON" "$SEVERITY")"
```

---

## Phase 5 — Write SHARED-CONCERNS.md + MANIFEST.md + finalize

### 5a. SHARED-CONCERNS.md

Write `$Z_HARNESS_PLAN_DIR/SHARED-CONCERNS.md` with YAML frontmatter:

```yaml
---
artifact: shared-concerns
slug: <root-slug>
generated_at: <UTC ISO 8601>
acknowledged: false              # user flips to true after reading (auto-true iff overlap_count: 0)
acknowledged_at:
acknowledged_by:
overlap_count: <N>
partial_tree: <true|false>       # true iff any cluster has status != ready
---
```

If `overlap_count: 0`, set `acknowledged: true` in the frontmatter at write time (ack-gate auto-passes). Otherwise leave `acknowledged: false`.

If `partial_tree: true`, set `partial_tree: true` in the frontmatter. This is consumed by `/z-implement-all`'s partial-tree gate (refuses without `--force-partial`).

Body: one block per detected overlap (ordered by descending severity, then by path):

```markdown
# Shared concerns — <root-slug>

## Overlap: `<normalized file path>`

Touched by:
- <cluster-id-1> (<task-ids>): <task title>
- <cluster-id-2> (<task-ids>): <task title>

Likely severity: <low | medium | high>

## ...
```

If `overlap_count: 0`, still write the file with the heading and a single sentence: `No file-path overlaps detected across clusters.`

### 5b. MANIFEST.md

Write `$Z_HARNESS_PLAN_DIR/MANIFEST.md` with YAML frontmatter:

```yaml
---
artifact: manifest
slug: <root-slug>
generated_at: <UTC ISO 8601>
command: /z-plan-split <args>
input_hash: <16 hex>   # sha256(canonicalize(topic + confirmed cluster names + scopes))[:16]
status: ready | partial | failed
total_clusters: <N>
clusters_ready: <K>
---
```

Status field:
- `ready` — all clusters succeeded.
- `partial` — ≥1 cluster `failed` AND ≥1 cluster `ready`.
- `failed` — all clusters failed (total-failure gate already halted; this branch should not normally write a MANIFEST, but if it did emit a minimal one, use `failed`).

Body:

```markdown
# MANIFEST — <root-slug>

## Clusters

| ID | Name (slug) | Scope (one line) | Path | Status | Attempts | Final status at |
|----|-------------|------------------|------|--------|----------|-----------------|
| C1 | <cluster_slug> | <scope> | <root-slug>/<cluster_slug>/ | ready / failed | 1 | <ISO> |
| ...

`ID` is the stable `cluster_id` (`C1`, `C2`, …) used in telemetry. `Name (slug)` is the kebab-case `cluster_slug` used as the on-disk directory.

## Run order

Clusters execute sequentially in this order under `/z-implement-all`. Cross-cluster task parallelism is v2.

1. C1 → C2 → C3 → shared (if user runs `/z-plan --slug=<root>/shared/` manually)

## Shared concerns

See SHARED-CONCERNS.md for detected file-overlap observations (count: <N>). Ack-gate enforced by `/z-implement-all`.

## Resolved decisions

(Populated if any cluster-planner re-spawn cycles fired in Phase 3.)

- <cluster-id> <decision-id>: chose `<option>` — <rationale> (run <RUN>)
- ...
```

### 5c. Finalize

Emit `phase_end` for Phase 5, then log `plan_split_run_end` with the full payload (per the Early-exit telemetry contract — this is the non-early, success/partial path):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_split_run_end \
  "$(printf '{"command":"z-plan-split","status":"%s","total_clusters":%d,"clusters_ready":%d,"clusters_failed":%d,"overlap_count":%d,"partial_tree":%s}' \
     "$STATUS" "$N" "$K" "$F" "$O" "$PT")"
```

where `$STATUS` is `"ready"` (all clusters succeeded) or `"partial"` (≥1 ready and ≥1 failed). The total-failure branch never reaches Phase 5 — it exits in Phase 3 or Phase 4 per the Early-exit telemetry contract.

Push-notify (if policy ≠ `off`) with a next-step recommendation:

```
Split complete: <K>/<N> clusters ready. Overlap count: <M>.

Recommended next:
  1. Read z-harness/<root-slug>/SHARED-CONCERNS.md and flip `acknowledged: true`
     (or pass --ack to /z-implement-all).
  2. /z-implement-all   — walks the tree in MANIFEST run-order.
```

For the partial-tree branch, the push notification also names the failed clusters and reminds the user that `/z-implement-all` will refuse without `--force-partial` until the failures are addressed (drop the cluster, re-plan it, or override the gate).

**Deregister this run** from the active-plan registry (best-effort, non-fatal). Per the FINALIZE_STATUS rule (Setup step 7): normal completion deregisters with `complete`.
```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status "${FINALIZE_STATUS:-complete}" || true   # CLI self-logs registry_error on failure
```

---

## Operating principles

- **One-level recursion only.** Cluster-planners refuse to write inside an existing MANIFEST.md tree (anti-self-nesting guard); the main thread refuses to write a nested MANIFEST.
- **2-6 clusters or refuse.** Below 2 → recommend `/z-plan` directly. Above 6 → ask the user to narrow.
- **TASKS.md is canonical for reconciliation.** `FILES_TOUCHED` is a fast-path summary; mismatch fails the cluster.
- **Partial trees are valid.** ≥1 cluster ready → proceed. All clusters failed → halt with `total_cluster_failure`.
- **No per-leaf cross-LLM consult.** Cost discipline (v1).
- **Decision-gate halts only the affected cluster.** Siblings continue; re-spawn handles the resolution.
- **Ack-gate is mandatory.** `/z-implement-all` refuses to walk a tree with `acknowledged: false` (unless `overlap_count: 0` auto-acks).
- **Path normalization applies everywhere.** Strip `./` / leading `/`, collapse `.`/`..`, reject escapes.
- **Never read `docs/llm/*.json` from main thread.** Always dispatch `doc-fetcher`.
- **Log everything** via `scripts/log-event.sh`.
- **No emojis.**

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 1a doc-fetcher (optional); Phase 2 cluster-planner × N (parallel) |
| `ask_user` | yes | Empty-topic question; Setup slug confirmation; Setup existing-slug decision; Phase 1d cluster confirmation (approve / edit / abandon); Phase 3 cluster decision-needed questions |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
