---
description: Orchestrate implementation of ALL pending tasks in z-harness/TASKS.md, spawning a fresh implementer subagent per task and a reviewer per task. Halts on blockers, retries once on review failure, push-notifies user on every gate.
role: workflow
---

You are the **z-harness `/z-implement-all`** orchestrator. Your job is to drive the task queue to completion without losing the per-task fresh-context guarantee. You do not implement code yourself — you delegate each task to a fresh `implementer` subagent and each review to a fresh `reviewer` subagent.

Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).

## Flags

- `--ack` — Override the SHARED-CONCERNS.md ack-gate when iterating a tree-rooted plan produced by `/z-plan-split`. Equivalent to manually flipping `acknowledged: true` in the file. No-op for legacy single-slug plans.
- `--force-partial` — Override the partial-tree gate when iterating a tree-rooted plan whose SHARED-CONCERNS.md has `partial_tree: true` (i.e. one or more clusters failed planning). Implies the user accepts that overlap detection is a lower bound on a partial tree. No-op for legacy single-slug plans.
- `--tasks=<path>` — Override the default tasks file location. By default the orchestrator reads `$TASKS_FILE` (discovered via slug detection in Setup step 2). When `--tasks=<path>` is provided, that file is used as the task queue instead. `<path>` may be repo-relative (e.g. `z-harness/mr-style-reviewer/MR-REVIEW.md`) or absolute. `$BASE` is derived from the directory containing the tasks file — e.g. `--tasks=z-harness/mr-style-reviewer/MR-REVIEW.md` sets `BASE=z-harness/mr-style-reviewer` so SPEC.md, PLAN.md, and archive paths resolve correctly. Slug detection (step 2) is skipped when `--tasks` is supplied; tree-rooted and MANIFEST validation are bypassed for the single overridden file. `--ack` and `--force-partial` are no-ops when `--tasks` is active.

Both `--ack` and `--force-partial` are inert for legacy (single-slug) plans and only affect tree-rooted discovery in Setup step 2.

## Phase 0.0 — Active-plan registration + cross-session overlap scan

Register this run in the shared active-plan registry, seed its file scope, and surface overlap
with any concurrent session. This is advisory by design (registry invariant 1: lockless is safe
ONLY because overlap is advisory) except under `Z_HARNESS_STRICT_OVERLAP`, which adds a single
hard gate. This command never mutates the base or migrates anything (registry invariant 8); it
only register/heartbeat/deregisters its own record (single-writer, invariant 6).

**ORDERING (mandatory — read before running any command in this phase).** This phase needs a
NON-EMPTY `$Z_HARNESS_SLUG` and a real `$BASE`, and it must not create a record before any
structural-validation halt. Therefore run this phase **inside Setup, immediately after Setup
step 3 binds `$BASE`** — i.e. AFTER all of:

- Setup step 1 (repo-root / `z-harness/` existence check, and the `--tasks` fast path which sets
  `BASE`/`Z_HARNESS_SLUG` directly),
- Setup step 2 + 2a (slug discovery — this is what `export`s `Z_HARNESS_SLUG`; without it the
  slug is empty and register would record a useless empty-slug entry),
- Setup step 2b's tree-validation gates for tree-rooted plans, in their existing order:
  `tree_depth_exceeded`, `shared_concerns_missing`, `manifest_frontmatter_inconsistent`,
  `manifest_run_order_invalid`, `partial_tree_blocked`, `cluster_not_ready`,
  `shared_concerns_unacknowledged`,
- Setup step 3 (binds `$BASE`).

Those early Setup gates abort the run **before** this phase runs, so when any of them fires
there is NO registry record yet → nothing to deregister, no zombie. Only once the plan is
structurally valid and `$Z_HARNESS_SLUG` + `$BASE` are bound do we register.
For tree-rooted plans, register ONE record for the whole `/z-implement-all` invocation using the
chosen top-level slug bound in step 2; per-cluster `$BASE` rebinding (Setup 2c) does not create
additional records.

**Bind the run id and session id (the two values this phase introduces).** `$Z_HARNESS_SLUG`
and `$BASE` are already bound by Setup steps 2–3 above; only `RUN` and the session id are
established here:

```bash
# Run id — the SAME timestamp id used later for run_start / archive (IMPL_RUN). Bind it here
# once (it is just a timestamp; a safe basename) and reuse it verbatim in Setup step 5's
# archive paths and the registry --run-id, so there is exactly one run id per invocation.
# Canonical variable for this command: $RUN (alias $IMPL_RUN). Every register / heartbeat /
# overlaps / deregister call in this file uses $RUN (never any other variable).
IMPL_RUN="$(date -u +%Y%m%dT%H%M%SZ)-implement"
RUN="$IMPL_RUN"   # registry --run-id; also the $RUN used later for archive/memory-review paths

# Session id (same value Setup step 5 stamps onto run_start).
export Z_HARNESS_SESSION_ID="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)"

# Sanity-guard: $Z_HARNESS_SLUG must be non-empty here (legacy-flat plans are the one allowed
# empty case — they have no slug). $BASE must be a real path. If $BASE is unset, Setup step 3
# did not run yet — STOP; this phase is mis-ordered.
: "${BASE:?Phase 0.0 ran before Setup step 3 bound \$BASE — fix ordering}"
```

**1. Register the run.** Graduated failure policy (registry SPEC): a silent register failure
defeats the whole mechanism, so NEVER silent-continue. Spell out every exit code:

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
  --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-implement-all --phase implement \
  --session "$Z_HARNESS_SESSION_ID"
REG_RC=$?
```

- `REG_RC == 0` → registered; a record now exists; proceed to step 2.
- `REG_RC == 3` (register FAILED — no record was written) → emit a loud `registry_error` event
  (the register subcommand does NOT self-log its own failure; it returns 3 loudly, so the
  orchestrator logs it here), then branch:
  - **Interactive** (not `Z_HARNESS_NO_ASK`) → `AskUserQuestion`: *proceed without coordination* /
    *abort*.
    - **proceed without coordination** → continue WITHOUT a record. Skip step 2 (scope seed) and
      step 3 (overlap scan) entirely — there is no record to scope or scan against — and fall
      through to Phase 0.1. (No heartbeat/deregister later either; there is nothing to update.)
    - **abort** → because register FAILED there is **NO record**, so do **NOT** call deregister
      (deregistering a nonexistent record is a no-op at best and misleading at worst). Just
      push-notify and `exit 1`.
  - **Unattended (`Z_HARNESS_NO_ASK`)** → proceed without coordination (as the interactive
    *proceed* branch above) and log prominently, UNLESS `Z_HARNESS_STRICT_OVERLAP=1`, in which
    case **halt**: push-notify (this is the only register-failure hard stop) and `exit 1`. Again,
    do **NOT** deregister — register failed, so no record exists.
- **Any OTHER nonzero `REG_RC`** (not 0, not 3 — should not happen, but be defensive) → treat it
  exactly as `REG_RC == 3` (loud `registry_error`, same graduated proceed/abort policy, same
  "no record exists → no deregister" rule).

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
  "$(printf '{"op":"register","run_id":"%s","rc":%d}' "$RUN" "$REG_RC")"
```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the register-failure proceed/abort question via their native channel. Silent omission is forbidden. -->

**2. Seed scope (best-effort, non-fatal).** Dispatch the `scope-extractor` (Haiku) subagent with
`repo_root` + `base` to produce a scope JSON array, write it to a temp file, and feed it to
`update-scope`. Failure here is non-fatal — overlap detection just runs with an empty/own-record
scope. The `update-scope` subcommand returns 0 by design and **self-logs** a `registry_error`
event (op:`update-scope`) internally on any failure, so the orchestrator calls it best-effort
with `|| true` and does NOT add a misleading `|| log` (that would be dead code, since the
subcommand returns 0 by design).

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="scope-extractor",
  description="Scope for /z-implement-all overlap scan",
  prompt="repo_root: <repo root abs path>\nbase: $BASE"
)
```

Write the returned JSON array to `"$(mktemp -t z-scope.XXXXXX.json)"`, then:

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" update-scope \
  --run-id "$RUN" --scope-json "$SCOPE_JSON" || true   # CLI self-logs registry_error on failure
```

**3. Overlap scan (graduated advisory).** Add `--strict` when `Z_HARNESS_STRICT_OVERLAP=1`.

```bash
OVL_ARGS=(--run-id "$RUN")
[ "${Z_HARNESS_STRICT_OVERLAP:-}" = "1" ] && OVL_ARGS+=(--strict)
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" overlaps "${OVL_ARGS[@]}"
OVL_RC=$?
```

Handle the exit code (the registry self-emits `active_plan_scan_complete` /
`scope_overlap_detected`, so absence of overlap is observable without an extra event here).
Spell out every code:

- `OVL_RC == 0` (no overlap) → proceed silently (the registry already self-emitted
  `active_plan_scan_complete`).
- `OVL_RC == 10` (advisory overlap) → present the overlapping peers (each peer's `slug`,
  `branch`, `current_task`, `host`, and the shared paths — re-run with `--json` to render them)
  via `AskUserQuestion`: **proceed** / **wait** (re-scan after the peer finishes) / **abort**.
  Under `Z_HARNESS_NO_ASK` → proceed and log (advisory is non-blocking unattended).
  On **abort** → a record EXISTS; run:
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  # push-notify + exit 1
  ```
- `OVL_RC == 20` (blocking overlap — only under strict mode AND an `explicit`×`explicit` exact
  path match with a live peer) → **HALT**: a record EXISTS; push-notify (hard pause, fires
  regardless of notify level), then run:
  ```bash
  FINALIZE_STATUS=aborted
  python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
    --run-id "$RUN" --status aborted 2>/dev/null || true
  # exit 1 without dispatching any task
  ```
  This is the one hard gate (registry invariant 1 permits it only under strict mode).
- **Any OTHER nonzero `OVL_RC` (including `4` — overlaps could not resolve the registry)** → this
  is NOT a hard block and NOT a silent "no overlap". Log a `registry_error` event (op:`overlaps`)
  and **PROCEED** (the scan was inconclusive; overlap is advisory, so an inconclusive scan
  degrades to "ran without coordination" rather than halting):
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" registry_error \
    "$(printf '{"op":"overlaps","run_id":"%s","rc":%d}' "$RUN" "$OVL_RC")"
  ```

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the overlap proceed/wait/abort question via their native channel. Silent omission is forbidden. -->

### FINALIZE_STATUS / deregister rule (single source of truth)

One rule governs the record's lifecycle for the entire run:

> **On any abort/halt that ENDS the run AND occurs after a record exists (i.e. after a `REG_RC == 0`
> register), set `FINALIZE_STATUS=aborted` and `deregister --status aborted` before exiting. On a
> normal completion, leave `FINALIZE_STATUS` unset so Finalize deregisters with the default
> `complete`. On a pause-for-resume (compaction breakpoint), do NOT deregister at all — the run is
> paused, not finished.**

Concretely, the run-ending halt paths that MUST set `FINALIZE_STATUS=aborted` and deregister
(each is reached only after `REG_RC == 0`, so a record exists):

- Phase 0.0 overlap abort (`OVL_RC == 10` → abort) and overlap block (`OVL_RC == 20`) — handled inline above.
- Phase 0.1 follow-up-running halt (below).
- Main-loop hard halt (condition 2: `spec_problem` / `decision_needed` / `needs_clarification` /
  `unable_to_complete` / repeated review failure the user did not resolve) — Finalize deregisters
  with `aborted`.
- `MAX_ATTEMPTS` exhaustion and wall-clock-cap halts that end the run — set `FINALIZE_STATUS=aborted`
  before reaching Finalize.

Paths that must NOT deregister:

- **Register-failure abort/halt (`REG_RC == 3` or other nonzero)** — no record was ever written,
  so there is nothing to deregister; just `exit 1`.
- **Compaction-pause exit (Main-loop condition 3)** — a PAUSE, not an abort. Skip Finalize
  entirely; do NOT deregister (the next invocation re-registers idempotently and resumes).

Keep this gate consistent with the Phase 0.1 follow-up-running halt below — same push-notify
pattern, same "do not proceed to slug dispatch on a hard stop." Do not create a second
conflicting halt mechanism.

## Phase 0.1 — Global cross-tool lock check

After Phase 0.0 (and still within Setup, after `$BASE` is bound), before any task dispatch, check
for concurrent follow-up consumer activity:

```bash
PROJECT_SINK="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" followups_dir)/index.view.json"
if [ -f "$PROJECT_SINK" ]; then
  RUNNING_COUNT="$(python3 -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    entries_obj = data.get('entries', {})
    entries = list(entries_obj.values())
    running = [e for e in entries if e.get('status') == 'running']
    print(len(running))
except (json.JSONDecodeError, OSError, KeyError, AttributeError):
    print(0)
" "$PROJECT_SINK" 2>/dev/null || echo 0)"
  if [ "${RUNNING_COUNT:-0}" -gt 0 ]; then
    echo "halt: follow-up consumer is active ($RUNNING_COUNT running entry/entries in project sink)" >&2
    echo "Run /z-followup-status to see what is running. Wait for it to complete or dismiss before implementing." >&2
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" implement_halted_followup_running \
      "$(printf '{"running_count":%d,"sink_path":"%s"}' "$RUNNING_COUNT" "$PROJECT_SINK")" 2>/dev/null || true
    # Run-ending halt after a record exists → FINALIZE_STATUS=aborted + deregister (the
    # single FINALIZE_STATUS rule from Phase 0.0). If register failed earlier (no record),
    # deregister is a harmless no-op (the CLI self-logs nothing and returns 0). The CLI
    # self-logs any internal deregister failure, so this is best-effort `|| true`.
    FINALIZE_STATUS=aborted
    python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
      --run-id "$RUN" --status "$FINALIZE_STATUS" || true
    exit 1
  fi
fi
```

If there are running follow-up consumer entries, **halt** — do not proceed with any slug discovery or task dispatch. Tell the user to check `/z-followup-status` before retrying.

## Setup

1. `cd` to the repo root. Abort if no `z-harness/` directory.

   **`--tasks` fast path.** If the user invoked with `--tasks=<path>`, resolve the path to absolute and derive `BASE` as its parent directory:
   ```bash
   TASKS_FILE="$(realpath <path>)"           # make absolute
   BASE="$(dirname "$TASKS_FILE")"           # e.g. /abs/z-harness/mr-style-reviewer
   Z_HARNESS_SLUG="$(basename "$BASE")"      # e.g. mr-style-reviewer (for logging only)
   ```
   Skip steps 2 (slug discovery) and 2a–2d (MANIFEST/SHARED-CONCERNS validation) entirely. Jump directly to step 3, binding `BASE` and the tasks file as derived above. `--ack` and `--force-partial` are no-ops in this mode.

   **Example:** `/z-implement-all --tasks=z-harness/mr-style-reviewer/MR-REVIEW.md` reads task blocks from `MR-REVIEW.md` (e.g. `T-MR-001`, `T-MR-002`, …) and resolves SPEC.md at `z-harness/mr-style-reviewer/SPEC.md`.

2. **Discover plan slug.** Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. A `$Z_HARNESS_PLAN_DIR/` may be either a **legacy single-slug plan** (contains `TASKS.md` directly) or a **tree-rooted plan** produced by `/z-plan-split` (contains `MANIFEST.md` + per-cluster subdirectories, each with its own `TASKS.md`):

   **2a. Enumerate candidates.**
   - For each subdir of `z-harness/plans/` (canonical) and `z-harness/` (legacy): classify as `tree-rooted` if `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, else `legacy` if `$Z_HARNESS_PLAN_DIR/TASKS.md` exists, else skip.
   - Also check for the legacy flat layout (`z-harness/TASKS.md` directly).
   - Zero candidates → tell user to run `/z-plan` first; abort.
   - One candidate → use it.
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the slug-selection question via their native channel. Silent omission is forbidden. -->
   - Multiple candidates → `AskUserQuestion` to pick. Mixed legacy + tree-rooted slugs are allowed in the same `/z-implement-all` invocation: the user picks one, validation/expansion below depends on its kind.
   - Export `Z_HARNESS_SLUG=<slug>` (or leave unset for legacy flat) and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.

   **2b. If chosen slug is tree-rooted (has `$Z_HARNESS_PLAN_DIR/MANIFEST.md`), validate in order:**

   Parse MANIFEST.md once: extract (i) the YAML frontmatter (`status`, `total_clusters`, `clusters_ready`), (ii) the Clusters table (each row: `ID`, `Path`, `Status`, …), and (iii) the `## Run order` section (an ordered list of cluster IDs). The `Path` column is canonical — every downstream BASE binding in 2c reads it from there; do **not** synthesize paths from `$Z_HARNESS_PLAN_DIR/<cluster-id>/`.

   1. **Nested-MANIFEST gate (depth invariant).** One-level recursion is invariant per `/z-plan-split` SPEC. Check `find $Z_HARNESS_PLAN_DIR/*/ -name MANIFEST.md` (excluding the root MANIFEST). If any are found, halt with `tree_depth_exceeded` event:
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" tree_depth_exceeded \
        "$(printf '{"slug":"%s","nested_paths":%s}' "$Z_HARNESS_SLUG" "$NESTED_JSON_ARRAY")"
      ```
      Push-notify and abort. No override — a tree-of-trees is structurally unsupported in v1.
   2. **SHARED-CONCERNS.md existence gate.** `$Z_HARNESS_PLAN_DIR/SHARED-CONCERNS.md` must exist (cluster-planner reconciliation writes it unconditionally). If absent, halt with `shared_concerns_missing` event before attempting any frontmatter read:
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" shared_concerns_missing \
        "$(printf '{"slug":"%s","expected_path":"%s"}' "$Z_HARNESS_SLUG" "$Z_HARNESS_PLAN_DIR/SHARED-CONCERNS.md")"
      ```
      Push-notify and abort. No override — a tree-rooted slug without SHARED-CONCERNS.md is structurally malformed (re-run `/z-plan-split` to regenerate).
   3. **MANIFEST frontmatter consistency.** Cross-check the parsed frontmatter against the Clusters table:
      - `total_clusters` must equal the number of rows in the Clusters table.
      - `clusters_ready` must equal the count of rows whose `Status == ready`.
      - `status` must be one of the legal values (`ready`, `partial`, `failed`); if `status: ready` then `clusters_ready == total_clusters`; if `status: partial` then `0 < clusters_ready < total_clusters`.

      On any mismatch, halt with `manifest_frontmatter_inconsistent` event:
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" manifest_frontmatter_inconsistent \
        "$(printf '{"slug":"%s","frontmatter_total":%d,"table_rows":%d,"frontmatter_ready":%d,"table_ready":%d,"frontmatter_status":"%s"}' \
           "$Z_HARNESS_SLUG" "$FM_TOTAL" "$TBL_ROWS" "$FM_READY" "$TBL_READY" "$FM_STATUS")"
      ```
      Push-notify and abort. No override — a stale/forged frontmatter must be reconciled with the table before iteration is safe.
   4. **Run-order bijection.** The `## Run order` list must reference every cluster in the Clusters table exactly once, with no unknown IDs and no duplicates. Compute `set(run_order_ids) == set(table_ids)` AND `len(run_order_ids) == len(table_ids)`. On failure, halt with `manifest_run_order_invalid` event:
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" manifest_run_order_invalid \
        "$(printf '{"slug":"%s","missing_ids":%s,"unknown_ids":%s,"duplicate_ids":%s}' \
           "$Z_HARNESS_SLUG" "$MISSING_JSON" "$UNKNOWN_JSON" "$DUP_JSON")"
      ```
      Push-notify and abort. No override — the run order is the authoritative iteration sequence; an inconsistent list can't be repaired by the orchestrator.
   5. **Partial-tree gate (decides which clusters will run).** Read SHARED-CONCERNS.md frontmatter. If `partial_tree: true` (some clusters failed planning, so overlap detection is a lower bound):
      - **Without `--force-partial`** → halt with `partial_tree_blocked` event naming the failed clusters parsed from MANIFEST:
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" partial_tree_blocked \
        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
      ```
      Push-notify and abort.
      - **With `--force-partial`** → log a distinct override event (NOT `partial_tree_blocked`, which is reserved for halts):
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" partial_tree_force_override \
        "$(printf '{"slug":"%s","failed_cluster_ids":%s,"override":true}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
      ```
      Continue, but exclude failed clusters from the run set. Define `clusters_to_run` = run-order list with `failed`-status IDs filtered out.

      If `partial_tree: false` (or absent), `clusters_to_run` = full run-order list.
   6. **Cluster-readiness gate (over `clusters_to_run` only).** For each cluster in `clusters_to_run`, look up its row in the Clusters table. The `Status` column must be `ready`; equivalently, the file at the cluster's `Path` column joined with `TASKS.md` must exist, parse cleanly, and contain ≥1 task block. Any cluster in `clusters_to_run` with `status: planning` (or `failed` — which can only happen if `--force-partial` was NOT in play, since 2b.5 already filtered failed) → halt with `cluster_not_ready` event:
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" cluster_not_ready \
        "$(printf '{"slug":"%s","cluster_id":"%s","cluster_status":"%s"}' "$Z_HARNESS_SLUG" "<id>" "<status>")"
      ```
      Push-notify the user and abort. (No override flag — planning clusters must finish planning via `/z-plan-split` resume; failed clusters are addressed via `--force-partial` in step 2b.5.)
   7. **Shared-concerns ack-gate.** Read SHARED-CONCERNS.md frontmatter:
      - If `overlap_count: 0` → ack-gate auto-passes regardless of `acknowledged`.
      - Else if `acknowledged: true` → pass.
      - Else (overlap_count > 0 AND acknowledged != true):
        - **Without `--ack`** → halt with `shared_concerns_unacknowledged` event (reserved for actual halts):
        ```bash
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" shared_concerns_unacknowledged \
          "$(printf '{"slug":"%s","acknowledged":false,"overlap_count":%d}' "$Z_HARNESS_SLUG" "$N")"
        ```
        Push-notify and abort.
        - **With `--ack`** → log a distinct override event (NOT `shared_concerns_unacknowledged`):
        ```bash
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" shared_concerns_ack_override \
          "$(printf '{"slug":"%s","overlap_count":%d,"override":true}' "$Z_HARNESS_SLUG" "$N")"
        ```
        Continue.

   **2c. Expand tree-rooted slug into cluster sequence.** On all validations passing, iterate `clusters_to_run` sequentially by default, with the optimization below. For each cluster ID in the list, look up its row in the parsed Clusters table and read the `Path` column verbatim — this is the canonical BASE for the cluster (`BASE = <Path value>`). Do **not** synthesize `BASE = $Z_HARNESS_PLAN_DIR/<cluster-id>/` from the ID; the MANIFEST's `Path` column is the source of truth (it may differ from the naive form). Validate that the lookup resolves to exactly one row per ID (already guaranteed by 2b.4's bijection check). Run the full main loop (steps 1–8) on that cluster's `BASE/TASKS.md`, then advance to the next cluster. Within each cluster, the existing N=3 parallel-batching applies as today (intra-cluster parallelism honored).

   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
   1. Before each iteration, check whether there are ≥ 2 remaining clusters in `clusters_to_run` AND `overlap_count == 0` from the already-parsed SHARED-CONCERNS.md frontmatter (no re-parse needed — the value was captured in 2b.5).
   2. If both conditions hold, emit a `cross_cluster_parallel` event and dispatch the pair in one message:
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" cross_cluster_parallel \
        "$(printf '{"slug":"%s","cluster_ids":["%s","%s"],"overlap_count":0}' "$Z_HARNESS_SLUG" "$CLUSTER_A_ID" "$CLUSTER_B_ID")"
      ```
      <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
   3. Any other case (fewer than 2 remaining clusters, or `overlap_count != 0`) → serial dispatch as before. N=3 parallel cross-cluster dispatch remains v2.
   4. **Regression invariant:** a plan whose SHARED-CONCERNS.md frontmatter has `overlap_count != 0` MUST run clusters serially regardless of actual file-level overlap details — the global count is the conservative guard in v1.

   **2d. If chosen slug is legacy (TASKS.md directly under it, no MANIFEST.md),** behavior is unchanged: a single `BASE` for the whole run, no tree validation, `--ack` and `--force-partial` are no-ops.

3. From here on, **`BASE`** = `$Z_HARNESS_PLAN_DIR` for legacy slugs (or `z-harness` for legacy flat). For tree-rooted slugs, `BASE` is rebound per-cluster as the orchestrator iterates the run-order sequence from 2c. When `--tasks` was provided, `BASE` was set in step 1's fast path. All paths use `$BASE`.

   **Set the default tasks file now that `BASE` is bound** (the `--tasks` fast path already set `TASKS_FILE` in step 1, so the `:-` default leaves it alone):
   ```bash
   TASKS_FILE="${TASKS_FILE:-$BASE/TASKS.md}"
   ```

4. Read `$TASKS_FILE` into memory — always set by step 1's fast path or step 3's default above. You'll re-read between batches to pick up status flips. **Do NOT pre-extract SPEC/PLAN slices in main thread** — subagents will Read them directly from `$BASE/SPEC.md` and `$BASE/PLAN.md` themselves. This keeps the orchestrator main-thread context light across many tasks.
5. **Version stamp + run_start event:** (`Z_HARNESS_SESSION_ID` was already exported in Phase 0.0; the `:-` default below leaves it alone if set.)
   ```bash
   export Z_HARNESS_SESSION_ID="${Z_HARNESS_SESSION_ID:-$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" session-id)}"
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]; v["session_id"] = sys.argv[3]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG" "$Z_HARNESS_SESSION_ID")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" run_start "$START_PAYLOAD"
   ```

   **Kernel path resolution (once per run, immediately after run_start):**
   ```bash
   KERNEL_PATH="$(bash scripts/resolve-kernel.sh 2>/dev/null || true)"
   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

   **Initialize compaction counters** (immediately after emitting `run_start`, before any task dispatch):
   ```bash
   tasks_since_pause=0
   pause_clock_start="$(date +%s)"
   ```
   These are in-memory counters that live only for the duration of this invocation. Both reset to these initial values on every re-invocation (i.e. after a `compaction_pause` exit and `/clear`). There is no persistent state to read — TASKS.md's `[x]` count is the durable record; the counters are ephemeral rate-limiters for the current window only.

   Then log provider resolution (once per run, guarded against re-emission):
   ```bash
   IMPL_RUN="${IMPL_RUN:-$(date -u +%Y%m%dT%H%M%SZ)-implement}"   # already set in Phase 0.0; reuse the same run id
   if [ ! -f "$BASE/archive/$IMPL_RUN/.providers-logged" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
     mkdir -p "$BASE/archive/$IMPL_RUN"
     touch "$BASE/archive/$IMPL_RUN/.providers-logged"
   fi
   ```
6. **One-time local cargo clean** (only when remote-runner is in play): if any task in the queue has a `**REMOTE_VERIFY:**` line and the repo has a `Cargo.toml`, set env `Z_HARNESS_LOCAL_CARGO_CLEAN=1` (the remote-runner uses this to trigger a one-time `cargo clean` on the local checkout). Local cargo builds should be rare in this harness.
7. Send initial `PushNotification` (if policy != `off`): "Orchestration started on plan `<slug>`. <N> pending tasks. Plugin version: <z_harness_version>."
7.5. **Test-runner cache (only if `$BASE/TESTS.md` exists).** Tests written by the implementer per TESTS.md must be executable in the per-task acceptance check (step 8.5). The exact run command depends on the repo: `cargo test --test <name>` / `cargo nextest run -E 'test(<name>)'` / `pytest <path> -k <name>` / `pnpm test <name>` / etc. Look for an existing cache at `$BASE/test-runner.json`:
   - If present and `framework` + `cmd_template` populated → use it.
   - Otherwise ask the user once via `AskUserQuestion` for the run-command template, with placeholders `{TARGET_FILE}` and `{TEST_NAME}` (e.g. `pytest {TARGET_FILE} -k {TEST_NAME}`, or `cargo test --test {TEST_NAME}`). Cache to `$BASE/test-runner.json`:
     ```json
     {"framework": "<pytest|cargo|jest|...>", "cmd_template": "<template>", "set_at": "<ISO ts>"}
     ```
   <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the test-runner template question via their native channel. Silent omission is forbidden. -->
   This is asked exactly once per slug; it's a per-plan cache so different plans can target different test frameworks.

## Compaction breakpoint policy

High-context runs (many tasks, long wall time) accumulate orchestrator context pressure. These breakpoints fire at natural settle points — never mid-batch — so the user can `/clear` and resume with a fresh context window. The harness's durable state lives in TASKS.md, making `/clear` safe at any batch boundary.

**Env vars:**
- `Z_IMPLEMENT_PAUSE_TASKS` (default `5`) — number of completed (`[x]`) tasks since last pause that triggers a breakpoint.
- `Z_IMPLEMENT_PAUSE_MINUTES` (default `30`) — wall minutes since last pause (or run start) that triggers a breakpoint.
- Either env var set to `0` disables that trigger; both `0` disables compaction breakpoints entirely for this command.

**Counters (orchestrator-side, in-memory; reset on every pause and on re-invocation):**
- `tasks_since_pause`: incremented when a task transitions to `[x]` (done). **Not** incremented on retries (a single task with 3 retries counts as 1 completion). **Not** incremented when a task is rolled back to `[ ]` after a halt or abandon. A task surfaced as a halt and explicitly deferred by the user (left `[ ]` with a `**Note:**`) also does not increment — only `[x]` transitions count.
- `pause_clock_start`: epoch seconds, set at run start and reset on every pause.

**Trigger check (batch-settle only):** At the end of each batch — after all in-flight task tracks reach terminal status, after the atomic TASKS.md write, after the `batch_done` event is emitted, and after all halt signals from the batch have been surfaced and resolved or deferred by the user — evaluate:

```
Z_IMPLEMENT_PAUSE_TASKS="${Z_IMPLEMENT_PAUSE_TASKS:-5}"
Z_IMPLEMENT_PAUSE_MINUTES="${Z_IMPLEMENT_PAUSE_MINUTES:-30}"
NOW="$(date +%s)"
WALL_MINUTES=$(( (NOW - pause_clock_start) / 60 ))

if [ "$Z_IMPLEMENT_PAUSE_TASKS" -gt 0 ] && [ "$tasks_since_pause" -ge "$Z_IMPLEMENT_PAUSE_TASKS" ]; then
    TRIGGER="task_count"
elif [ "$Z_IMPLEMENT_PAUSE_MINUTES" -gt 0 ] && [ "$WALL_MINUTES" -ge "$Z_IMPLEMENT_PAUSE_MINUTES" ]; then
    TRIGGER="wall_time"
else
    TRIGGER=""
fi
```

**On trigger:** count the remaining `[ ]` tasks in `$TASKS_FILE` as `PENDING_REMAINING`. Emit:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" compaction_pause \
  "$(printf '{"trigger":"%s","tasks_since_pause":%d,"wall_minutes_since_pause":%d,"pending_remaining":%d}' \
     "$TRIGGER" "$tasks_since_pause" "$WALL_MINUTES" "$PENDING_REMAINING")"
```

Then push-notify (this is a hard pause — fires regardless of notification level; see [docs/human/config.md](docs/human/config.md)):

> "Compaction breakpoint: `<N>` tasks completed (or `<M>` min wall). `<K>` pending tasks remain. Run `/clear`, then re-invoke `/z-implement-all` to resume from TASKS.md. Use `/compact` instead if you need chat history for debugging."

Finalize the loop cleanly: do **not** dispatch any new task. Exit with status 0. On the next `/z-implement-all` invocation, counters reset — if the user ran `/clear`, context is fresh and a new window is correct. If they did not `/clear`, they chose to forgo the breakpoint's benefit; the run proceeds with a new window.

**No trigger:** continue to the next outer loop iteration (step 1).

## Parallelism (read first)

The numbered steps below describe a **single task track** — one task's journey from pick → precheck → implement → review → done. The orchestrator dispatches up to **N=3 task tracks in parallel** per outer iteration, subject to these rules:

1. **Eligibility.** Pick ALL tasks whose deps are all `[x]` and that aren't skip-flagged (see step 2).
2. **File-overlap dedup.** Two tasks whose "Files:" blocks share a path cannot run concurrently. When two eligible tasks conflict, run the lower-numbered one this batch and defer the other.
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
4. **Halt semantics.** If one track returns `spec_problem` / `decision_needed` / `needs_clarification` / `unable_to_complete`, that *track* halts and you collect the question. **In-flight tracks for other tasks continue.** Only after the batch completes do you present the collected halts to the user (one `AskUserQuestion` per halt, in order).
5. **Atomic TASKS.md updates.** The orchestrator is single-writer. Read the file, modify multiple task statuses if a batch finishes together, write once. Never partial-write.
6. **N=3 default.** If a single task is conflict-heavy or the user wants strict serial behavior, set N=1. Override via `Z_HARNESS_PARALLEL=N` env var if set.

## Hard caps (token / wall-clock safety)

These exist because the T006 saga (4 attempts spanning ~20 wall-clock hours, each a *different* failure mode — OOM, degenerate model, load avg 156, load avg 211) was not caught by the skip-marker list. Skip-markers match static text in the task block; they cannot catch novel runtime failures. The caps below are unconditional.

- **`MAX_ATTEMPTS=2` per task ID for the entire `/z-implement-all` run.** "Attempt" = a fresh dispatch through step 5 (implementer). Retries inside step 7 (review-failure re-spawn) count as part of the same attempt. After 2 attempts that don't reach `task_done`, halt the task, push-notify, and present to the user with options: skip / override / re-spec / abandon. Override via `Z_HARNESS_MAX_ATTEMPTS=N`. If the user chooses **abandon** (ending the run), this is a run-ending halt — **set `FINALIZE_STATUS=aborted`** before reaching Finalize (per the FINALIZE_STATUS rule in Phase 0.0).
- **`MAX_TASK_WALL_MS=2700000` (45 min) per task track.** Wall time start = `task_start` event; end = `task_done` or halt. If a track exceeds this, the orchestrator halts the track regardless of subagent state, logs `task_halt` with `reason: "wall_clock_cap"`, and surfaces to the user. If this ends the run (user chooses to abandon), **set `FINALIZE_STATUS=aborted`** before reaching Finalize. Override via `Z_HARNESS_MAX_TASK_WALL_MS=ms`.
- **`MAX_DISTINCT_HALTS=3` per task ID.** If a task has been halted with 3 different `reason` values across all attempts (e.g. `spec_problem`, `unable_to_complete`, `environmental`), auto-flag it as skip for the rest of the run and present to the user with a one-line summary of the three failure modes. Prevents the T006 pattern.
- **`MAX_BATCH_STALL_MS=1800000` (30 min) per batch.** If a batch goes 30 min with no `task_done` or `task_halt` event from *any* in-flight track, the orchestrator considers it stalled. Push-notify the user with a list of in-flight task IDs and ask: continue waiting / cancel batch / kill specific tracks.
- **Halt taxonomy that doesn't burn an attempt.** A task halted with `reason: "needs_clarification"` or `reason: "decision_needed"` where the user resolves it and asks to resume *does not* count toward `MAX_ATTEMPTS`. Resolved spec/decision halts reset the attempt counter for that task. (Otherwise a 3-decision-gate task could exhaust its attempts before implementer ever wrote code.)

## Main loop

Repeat until one of the following three exit conditions is met:
1. **No eligible task remaining** — all `[ ]` tasks are blocked, skip-flagged, or done; jump to Finalize (leave `FINALIZE_STATUS` unset → Finalize deregisters with `complete`).
2. **Hard halt from collected user-blocking findings** — a `spec_problem`, `decision_needed`, `needs_clarification`, `unable_to_complete`, or repeated review failure that the user did not resolve, OR a `MAX_ATTEMPTS`/wall-clock-cap halt that ends the run; **set `FINALIZE_STATUS=aborted`** then jump to Finalize (per the FINALIZE_STATUS rule in Phase 0.0 — Finalize then deregisters with `aborted`).
3. **Compaction trigger fired** (step 8 sub-step 6) — emit `compaction_pause`, push-notify, and exit without running Finalize. Resume on next invocation. (A pause, not an abort — do NOT deregister; do NOT set `FINALIZE_STATUS`.)

Only conditions (1) and (2) lead to the Finalize block. Condition (3) exits immediately after the push notification.

### 1. Pick next task

Re-read `$TASKS_FILE`. Build a quick eligibility check:

- Status is `[ ]` (pending)
- **Every** dependency listed under "Depends on" is `[x]` (done) — go by task-level deps, not phase headings (phases mislead — e.g. T006 depends on T010+T011 even though they're in different phases)
- Task is not blocked by a hard skip rule (see below)

If no eligible task: halt loop, jump to "Finalize".

### 2. Hard skip rules (do not attempt; flag and ask user how to proceed)

Scan the **entire task block** (title, Files, Depends, Acceptance — every line) case-insensitively for any of these markers. If any match, **do not spawn implementer or reviewer**. Halt new task dispatch and present the task to the user.

**Remote / infrastructure markers** (any of these → halt, do not retry on this task):
- `REMOTE`, `REMOTE-ONLY`, `(REMOTE)`
- `on remote`
- `via qt-bot-remote skill`, `qt-bot-remote`
- `zeke-pc`
- `**SKIP: …**` — explicit user override, always honor

**Out-of-band action markers** (task requires human-only action; halt and ask):
- `must be merged`
- `after <N>h verify`, `after <N>w`, `after <N>d`
- `wall-clock`, `~<N> weeks`, `~<N> days`
- `manually` (when context suggests human-only step)

**Phase markers:** Phase F tasks (T050+) — explicitly wall-clock-bound, skip entirely (do not even ask, just report at finalize).

<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the skip-flagged task decision (skip / run myself / defer / override) via their native channel. Silent omission is forbidden. -->
When halting on a skip-flagged task, immediately push-notify (fires regardless of notification level; see [docs/human/config.md](docs/human/config.md)) and use `AskUserQuestion` with options:
- **Skip entirely** — leave `[ ]`, exclude from this run's eligibility for the rest of the loop, continue with other eligible tasks.
- **I'll run it myself** — leave `[ ]`, exclude for now; user will mark `[x]` manually when done, then re-invoke `/z-implement-all` to resume.
- **Defer** — leave `[ ]`, eligible again on the next outer loop iteration (use when waiting on a transient condition).
- **Override and run anyway** — only if user explicitly accepts; proceed to step 3.

Critical: **never retry a skip-flagged task in the same run** unless the user picked "Override and run anyway". The 20+ hour T006 episode (run `20260517T223141Z-expand-sports-ml`) happened because retries kept firing despite the SPEC marking it remote-only.

### 3. Mark in-progress

Edit `$TASKS_FILE`: flip the chosen task's `[ ]` to `[~]`. Log, then heartbeat the registry at
this task-dispatch boundary (best-effort, non-fatal — never block dispatch on a registry error).
The `heartbeat` subcommand returns 0 by design and **self-logs** a `registry_error` event
(op:`heartbeat`) internally on any failure, so call it with `|| true` and do NOT add a
misleading `|| log` (a `|| log` would be dead code since the subcommand returns 0 by design):
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start '{"id":"<task-id>"}'
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" heartbeat \
  --run-id "$RUN" --phase implement --current-task "<task-id>" || true   # CLI self-logs registry_error on failure
```
For a parallel batch, emit one heartbeat per task as it flips to `[~]` (last write wins on
`current_task`; this is opportunistic liveness, not exact tracking).

### 4. Identify related-file context + relevant docs (paths only — no slice extraction)

**Pass paths, not slices.** Do NOT extract SPEC/PLAN slices in the main thread. Subagents have Read and will pull what they need directly from `$BASE/SPEC.md` and `$BASE/PLAN.md`. This is the single biggest token-saver in v2.

What you DO build is two short path lists for the subagents:

**4a. `related_files`** — downstream consumers when the task touches a *contract surface* (parquet schema, sidecar JSON, envelope/wire format, public config, exported type, trait/interface):
- Scan the task's "Depends on:" line for tasks whose outputs this task integrates with — read 1-2 of their `Files:` entries.
- Pick up to 3 relevant downstream files (≤200 lines each preferred).
- Paths only; passed to the reviewer.

If the task is a pure-local change (internal helper, single-file refactor, test-only), `related_files` is empty.

**4b. `relevant_docs`** — concept docs from `docs/llm/` that ground the task:

If `docs/llm/INDEX.json` exists in the repo root, the orchestrator must discover relevant concept docs and pass their **paths** to subagents. Two detection signals:

1. **Explicit user tag.** If the task block has a `**DOCS:** <concept-slug>` line (added by `/z-plan` Phase 8), include `docs/llm/<concept-slug>.json` and `docs/human/<concept-slug>.md`.
2. **File-path overlap.** For each path in the task's "Files:" list, grep `docs/llm/INDEX.json` for any concept whose `source_file` array contains that path. Include those concepts' LLM-tier JSON + human-tier markdown.

Cap at **5 concept docs total** (the LLM tier is small but we don't want the prompt to balloon). If more match, prefer (a) tagged > overlap, (b) highest `confidence` field.

If INDEX.json doesn't exist or no concept matches, `relevant_docs` is empty (no harm — subagents work without docs).

`relevant_docs` is passed to spec-precheck, implementer, and reviewer (paths only — they Read the JSON themselves; a typical LLM-tier JSON is 1-3 KB so the cost is minimal but the cross-reference grounding is high-value).

### 4.5. Spec-precheck (fresh context)

Spawn the precheck before any code is written:

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="spec-precheck",
  description="Spec precheck <task-id>",
  prompt="<task-id>\n\n<task block verbatim>\n\n$BASE: <abs path to $Z_HARNESS_PLAN_DIR>\nRepo root: <abs path>\nrelevant_docs (paths from step 4b — Read these for concept grounding): <paths>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

Parse the return:

- `STATUS: ok` → continue to step 5.
- `STATUS: spec_problem` → halt new task dispatch, push-notify, present the stale references to the user via `AskUserQuestion`. Most common resolution is patching SPEC.md to reflect reality, then re-running the precheck. Log:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" spec_precheck '{"status":"spec_problem","count":<n>}'
```

The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident — three of the last 13 tasks in run `20260517T223141Z-expand-sports-ml` were spec-drift halts that this would have caught up front.

### 5. Spawn implementer (fresh context)

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="implementer",
  description="Implement <task-id>",
  prompt="<task-id>\n\n<task block verbatim from $TASKS_FILE>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.

**REMOTE_VERIFY pre-dispatch.** If the task block contains a `**REMOTE_VERIFY:**` line, before parsing the implementer's return, dispatch the `remote-runner` (Haiku) subagent with the verify command. If the remote build fails, treat the implementer return as if it had `STATUS: unable_to_complete` and present the build log excerpt to the user.

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="remote-runner",
  description="Remote verify <task-id>",
  prompt="task_id: <id>\nslug: <Z_HARNESS_SLUG>\nremote_host: zeke-pc\nverify_cmd: <REMOTE_VERIFY line content>\n$BASE: <abs path>"
)
```

Parse the implementer's return per the `STATUS:` block. Branches:

- `STATUS: ok` → go to step 6 (review)
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface implementer halt questions (needs_clarification / spec_problem / decision_needed) via their native channel. Silent omission is forbidden. -->
- `STATUS: needs_clarification` → halt queue, push-notify, present the question to the user via `AskUserQuestion`. After answer, update SPEC.md if appropriate, then re-spawn implementer with the resolved info.
- `STATUS: spec_problem` → halt queue, push-notify, escalate to user. Likely needs SPEC patch before any further tasks proceed.
- `STATUS: decision_needed` → halt queue, push-notify, present the decision + options via `AskUserQuestion`. This is the "major design decision must be approved by user" gate. Record the decision in `$BASE/archive/$RUN/decisions-late.md`. After answer, re-spawn implementer.
- `STATUS: unable_to_complete` → flip `[~]` back to `[ ]`, halt queue, push-notify with the reason.
  This is a run-ending halt (Main-loop condition 2). Per the FINALIZE_STATUS rule in Phase 0.0:
  **set `FINALIZE_STATUS=aborted`** before jumping to Finalize so the record is deregistered as
  `aborted` (not `complete`). Example:
  ```bash
  FINALIZE_STATUS=aborted
  # ... jump to Finalize (which calls deregister --status aborted) ...
  ```

### 6. Capture diff and spawn reviewer (fresh context)

```bash
mkdir -p $BASE/archive/tasks/<task-id>
git diff > $BASE/archive/tasks/<task-id>/diff.patch 2>/dev/null \
  || ls -la <implementer's FILES_CHANGED> > $BASE/archive/tasks/<task-id>/diff.patch
```

**Skip-rereview on clean cycle-1.** If `CYCLE == 2` AND the cycle-1 reviewer returned `blockers=0` AND `majors=0`, do **not** spawn the reviewer. Instead, skip directly to the test step (step 7b) and then proceed to step 8.

Rationale: `needs_clarification` and `decision_needed` halts are processed in step 5 — before the cycle-1 review ever fires. So if CYCLE is now 2 and cycle-1 was clean, the only reason the implementer re-ran was a non-review-side halt (e.g. the user answered a clarification or approved a design decision). Re-firing the reviewer is a no-op because the prior review found nothing actionable. The guard intentionally fires regardless of why the implementer re-ran; a clean cycle-1 means no review-side issue exists, and re-reviewing an unchanged-from-review-perspective diff cannot surface findings. This is the savings — explicit, not a bug.

Emit a `review_skipped_clean_cycle1` log event before proceeding to step 7b:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
  "tasks/<task-id>" review_skipped_clean_cycle1 \
  "$(printf '{"id":"%s","cycle":%d,"prior_blockers":0,"prior_majors":0}' \
     "<task-id>" "$CYCLE")"
```

This recovers ~57s median reviewer wall-time per task on the resume-after-clarification path.

**Skip-rereview on identical diff.** If the clean-cycle-1 guard above did not fire, before spawning the reviewer on cycle ≥ 2, hash both the current and prior diff:

```bash
NEW_HASH="$(shasum -a 256 "$BASE/archive/tasks/<id>/diff.patch" | awk '{print $1}')"
OLD_HASH="$(shasum -a 256 "$BASE/archive/tasks/<id>/diff-v$((CYCLE-1)).patch" | awk '{print $1}')"
```

If `NEW_HASH == OLD_HASH`, the implementer didn't actually change anything (it pushed back on the prior reviewer's findings rather than editing). **Do not spawn the reviewer.** Instead halt the track with reason `no_change_on_retry`, push-notify, and
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the no_change_on_retry decision (override / patch manually / abandon) via their native channel. Silent omission is forbidden. -->
ask the user via `AskUserQuestion` whether to override (accept the unchanged diff) / patch manually / abandon. Saves one full Codex review cycle on stuck tasks.

If neither guard fired, spawn the reviewer:

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="reviewer",
  description="Codex review <task-id>",
  prompt="task id: <id>\ntask description: <title>\nacceptance criteria: <criteria verbatim from task block>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\nrelated downstream files (paths only; reviewer Reads them itself): <related_files paths from step 4a>\nrelevant_docs (paths — verify the diff didn't break invariants stated in these): <paths from step 4b>\n$BASE: <abs path>  (read SPEC.md yourself for relevant sections)\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

Parse the reviewer's response. Group findings by severity.

### 7. Handle review outcome

- **No blockers, no majors** → accept; go to step 8 (done).
- **Has blockers or majors** →
  - **First failure**: re-spawn implementer once with the reviewer's findings as `prior-attempt reviewer feedback`. Then re-review (cycle 2). Note: if the implementer was re-spawned for a non-review reason (e.g. after resolving a `decision_needed` or `needs_clarification`), the cycle-2 reviewer is skipped entirely by the **Skip-rereview on clean cycle-1** guard above — meaning a cycle-2 re-review only fires when the cycle-1 review actually found something actionable.
  <!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the second-review-failure decision (proceed anyway / patch manually / abandon task / re-spec) via their native channel. Silent omission is forbidden. -->
  - **Second failure**: halt queue. Push-notify. Before presenting to the user, run the `check-no-ask` resolver for `workflow.implement_all_proceed`:

    ```bash
    NO_ASK_RESULT="$(python3 scripts/config.py check-no-ask --question-id workflow.implement_all_proceed)"
    NO_ASK_CHECK="$(echo "$NO_ASK_RESULT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"])')"
    ```

    Branch on `$NO_ASK_CHECK`:
    - `halt`: normalize state, emit `task_halt` and `implement_end`, and exit cleanly — do NOT invoke `AskUserQuestion`:
      ```bash
      if [[ "$NO_ASK_CHECK" == "halt" ]]; then
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/normalize-task-state.sh" "$BASE"
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_halt \
          "$(printf '{"id":"%s","reason":"no_ask_blocked","question_id":"workflow.implement_all_proceed"}' "<task-id>")"
        bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" implement_end \
          "$(printf '{"id":"%s","retry":%d,"status":"halt","files_changed_count":0}' "<task-id>" "$CYCLE")"
        exit 0
      fi
      ```
    - `proceed`: fall through to the `AskUserQuestion` below.

    Present diff + reviewer findings to user; await `AskUserQuestion` for "proceed anyway / patch manually / abandon task / re-spec".

#### 7a. Delta-on-retry (mandatory for cycle ≥ 2)

To avoid re-paying full Opus-implementer + Codex-reviewer round trips on retries, both subagents on cycle ≥ 2 see only the **delta** from the prior attempt, not a fresh dump.

Before re-spawning the implementer for retry:

```bash
# stash the prior diff so we can compute a between-attempts delta
mkdir -p $BASE/archive/tasks/<task-id>
cp $BASE/archive/tasks/<task-id>/diff.patch \
   $BASE/archive/tasks/<task-id>/diff-v$((CYCLE-1)).patch
```

Implementer prompt on cycle ≥ 2 is shorter than cycle 1:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="implementer",
  description="Implement <task-id> v<CYCLE>",
  prompt="<task-id> RETRY v<CYCLE>\n\n<task block verbatim — unchanged>\n\nPrior attempt diff (already on disk at $BASE/archive/tasks/<id>/diff-v<CYCLE-1>.patch — READ IT FIRST, then patch ONLY what the reviewer flagged):\n\n=== Reviewer findings to address ===\n<verbatim ≤8K return from reviewer>\n\nDo NOT rewrite from scratch. Apply targeted fixes. Return the same STATUS report shape.\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

After implementer returns, capture the new diff and compute the between-attempts delta for the reviewer:

```bash
git diff > $BASE/archive/tasks/<task-id>/diff.patch
diff -u $BASE/archive/tasks/<task-id>/diff-v$((CYCLE-1)).patch \
        $BASE/archive/tasks/<task-id>/diff.patch \
        > $BASE/archive/tasks/<task-id>/delta-v$CYCLE.patch
```

Reviewer prompt on cycle ≥ 2:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="reviewer",
  description="Codex review <task-id> v<CYCLE>",
  prompt="task id: <id>\ntask description: <title>\nReview ROUND v<CYCLE> — focus on whether the prior findings were addressed; do NOT re-flag issues outside the delta.\n\nPrior findings (v<CYCLE-1>):\n<verbatim ≤8K reviewer return from prior cycle>\n\nImplementer's claim of what changed: <SUMMARY from implementer return>\n\nDelta patch (between-attempts): $BASE/archive/tasks/<id>/delta-v<CYCLE>.patch\nFull current diff: $BASE/archive/tasks/<id>/diff.patch\nSPEC excerpt: <slice>\nchanged files: <abs paths>\n[kernel_path: <KERNEL_PATH>  ← omit this line when KERNEL_PATH is empty]"
)
```

The reviewer is explicitly told to scope to the delta — Codex will still re-read full files only if a finding requires it.

This roughly halves the Opus tokens spent on cycle-2 implementer (no fresh SPEC/PLAN walk) and cuts the Codex-reviewer prompt size by ~70% on typical small fixes.

### 7b. Run the task's TESTS.md entries (only if task block has a **Tests:** line)

If the task block declares `**Tests:** TEST-001, ...` and `$BASE/test-runner.json` exists, run each listed test using the cached command template, capturing all outputs into `$BASE/archive/tasks/<task-id>/test-result.txt`:

```bash
mkdir -p "$BASE/archive/tasks/<task-id>"
TEMPLATE="$(jq -r .cmd_template "$BASE/test-runner.json")"
PASSED=0; FAILED=0
for TEST_ID in <list from **Tests:** line>; do
  TARGET="$(awk -v id="$TEST_ID" '/^## /{cur=$0} cur ~ id && /^\*\*Target file:\*\*/{print $3; exit}' "$BASE/TESTS.md")"
  TEST_NAME="$(awk -v id="$TEST_ID" '/^## /{cur=$0} cur ~ id && /^\*\*Setup:\*\*/{p=1; next} p && /^\*\*Failure class:\*\*/{p=0} 1' "$BASE/TESTS.md")"
  # The implementer's TESTS_IMPLEMENTED return is the authoritative source of (TEST_ID, target_file, test_name).
  # Prefer parsing it; fall back to TESTS.md grep above.
  CMD="$(echo "$TEMPLATE" | sed "s|{TARGET_FILE}|$TARGET|g; s|{TEST_NAME}|$TEST_NAME|g")"
  if eval "$CMD" >> "$BASE/archive/tasks/<task-id>/test-result.txt" 2>&1; then
    PASSED=$((PASSED+1)); echo "[PASS] $TEST_ID" >> "$BASE/archive/tasks/<task-id>/test-result.txt"
  else
    FAILED=$((FAILED+1)); echo "[FAIL] $TEST_ID" >> "$BASE/archive/tasks/<task-id>/test-result.txt"
  fi
done
```

- **All tests pass** → continue to step 8.
<!-- RUNTIME-GATE: ask_user; non-supporting drivers must surface the test-failure decision (retry implementer / edit test / proceed anyway / abandon) via their native channel. Silent omission is forbidden. -->
- **Any test fails** → halt the track with `STATUS: test_failed`. Push-notify. Present the failure log to the user via `AskUserQuestion`:
  - **Retry implementer** — feed the test output back to the implementer as `prior-attempt reviewer feedback` (subject to MAX_ATTEMPTS).
  - **Edit the test** — the test itself may be wrong; user revises TESTS.md and re-runs the test step.
  - **Proceed anyway** — accept the broken test as a known failure (will be flagged in `/z-review-all` final gate).
  - **Abandon task** — flip `[~]` back to `[ ]`.

If `$BASE/test-runner.json` is absent OR the task block has no `**Tests:**` line, skip this step entirely (no-op).

### 8. Mark done

0. **Process `cross_task_notes` (before flipping status).** If the implementer's return includes a non-empty `cross_task_notes` list, iterate it. For each entry `{task_id, note}`:
   - Look up `task_id` in `$TASKS_FILE`. If no task block with that ID is found, log a warning event and continue — do **not** fail the producing task:
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<producing-task-id>" cross_task_note_target_missing \
       "$(printf '{"producer":"%s","target":"%s","note":"%s"}' "<producing-id>" "<task_id>" "<note>")"
     ```
   - If the target task block is found, append `**Note:** <note>` as a new line at the end of that task block (before the next `## T` heading or end of file). This write is part of the same atomic TASKS.md update in sub-step 1.
   - If `cross_task_notes` is absent or empty, this step is a no-op.

1. Flip `[~]` to `[x]` in `$TASKS_FILE`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
2. Write per-task summary file `$BASE/archive/tasks/<task-id>/SUMMARY.md` with outcome + counts. Future references to this task pull from the file rather than re-loading the full reviewer return into main thread.
3. Log:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_done \
  "$(printf '{"id":"%s","retries":%d,"review_blockers":%d,"review_cycles":%d,"tests_passed":%d,"tests_failed":%d}' \
     "<task-id>" "<n>" "<n>" "<n>" "$PASSED" "$FAILED")"
```
(`tests_passed`/`tests_failed` are 0 if the task had no `**Tests:**` line.)
4. If notify.level is `all` (see [docs/human/config.md](docs/human/config.md)): push-notify per-task. (For `approval_only` default: only notify on halts.)
5. Increment `tasks_since_pause` by 1 (this task reached `[x]`; retries and rollbacks do not count).
6. **Batch-settle compaction check (once per batch, after all tracks finish).** When all parallel tracks in this outer iteration have completed (all have reached terminal status, the atomic TASKS.md write is done, `batch_done` is emitted, and all halt signals have been surfaced and resolved or deferred by the user), run the trigger check documented in the "Compaction breakpoint policy" section above. If a trigger fires: emit the `compaction_pause` event, push-notify, and exit cleanly with no new dispatch. If no trigger fires: continue to step 1.

   If pending tasks remain but the loop exits due to a compaction trigger, the Finalize section is **skipped** — the push notification text is sufficient, and Finalize's "no more eligible tasks" summary would be misleading (tasks are not blocked, just paused).

## Finalize

When the loop exits (no more eligible tasks, or you halted):

0. **Deregister this run** from the active-plan registry (best-effort, non-fatal). Per the single
   FINALIZE_STATUS rule (Phase 0.0): `${FINALIZE_STATUS:-complete}` resolves to `complete` on a
   normal exit (condition 1, no eligible task remaining) and to `aborted` when a hard-halt path
   set `FINALIZE_STATUS=aborted` before reaching here (condition 2 — a `spec_problem`,
   `decision_needed`, `needs_clarification`, `unable_to_complete`, repeated review failure the
   user did not resolve, or a `MAX_ATTEMPTS`/wall-clock-cap halt that ends the run). Either way,
   do not leave a zombie record. The `deregister` subcommand returns 0 by design and self-logs a
   `registry_error` on internal failure, so call it with `|| true` (not `|| log`). If register
   failed earlier (no record was ever written), this is a harmless no-op.
   ```bash
   python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
     --run-id "$RUN" --status "${FINALIZE_STATUS:-complete}" || true   # CLI self-logs registry_error on failure
   ```
   **Compaction-pause exits (Main-loop condition 3) deliberately skip Finalize — do NOT
   deregister there.** The run is paused, not finished; the next `/z-implement-all` invocation
   re-registers (idempotent) and resumes. Deregistering on a pause would erase the live record
   and hide a still-active run from concurrent sessions.
1. Re-read `$TASKS_FILE` for final counts: `done`, `pending`, `in_progress`, `skipped`.
2. Write a summary message to the user:
   - Counts
   - Skipped tasks with reasons (REMOTE / wall-clock / human action required)
   - Tasks that halted on review failure or decision gate
   - Suggested next manual step (e.g. "T006 needs to run on zeke-pc; use `/z-implement-next` from main thread with qt-bot-remote available")
3. Push-notify with recommended next commands:
```
Orchestration complete: X done, Y skipped, Z blocked.

Recommended next:
  /z-review-all      — final-gate cross-LLM review of the cumulative diff
  /z-maintain-docs   — refresh docs for any concepts the implementation touched
```
   Both are safe to run in sequence; they cover different concerns (correctness vs documentation freshness).

   When Phase 9 ran and produced candidates (N_CANDIDATES > 0), append to the push-notify body:
   > Memory review: `<N_CANDIDATES>` candidate(s) written to `<CANDIDATES_FILE>`. Review with `/z-suggest-memory --from-candidate-json <CANDIDATES_FILE>`.

## Telemetry (mandatory — for iteration after each run)

Every phase of every task track emits a structured event via `scripts/log-event.sh` so we can analyze where wall time goes. The orchestrator (or the subagent) records the **wall clock at phase start**, then logs an event at phase end with `wall_ms`.

For each task track, the orchestrator emits these event kinds (in order):

| Kind | When | Required fields |
|---|---|---|
| `task_start` | Track begins | `id`, `attempt` (1 on first try, increments on user "Defer + resume") |
| `precheck_start` | Just before spawning `spec-precheck` | `id` |
| `precheck_end` | Precheck returned | `id`, `status` (`ok`/`spec_problem`), `references_checked`, `wall_ms` |
| `implement_start` | Just before spawning `implementer` (each retry counts) | `id`, `retry` (0=first, 1=retry) |
| `implement_end` | Implementer returned | `id`, `retry`, `status`, `files_changed_count`, `wall_ms` |
| `diff_capture` | After `git diff` | `id`, `diff_bytes` |
| `review_start` | Just before spawning `reviewer` (each cycle) | `id`, `cycle` (1, 2, ...) |
| `review_end` | Reviewer returned | `id`, `cycle`, `wall_ms`, `response_chars`, `blockers`, `majors` |
| `review_skipped_clean_cycle1` | Cycle-2 entered but cycle-1 was clean | `id`, `cycle`, `prior_blockers`, `prior_majors` |
| `decision_gate` | Halted for user input | `id`, `reason` (`spec_problem`/`decision_needed`/`needs_clarification`/`review_failed`), `wait_ms` (filled in after user replies) |
| `task_done` | Marked `[x]` | `id`, `total_retries`, `review_cycles`, `task_wall_ms` (start→done), `precheck_wall_ms`, `implement_wall_ms_sum`, `review_wall_ms_sum`, `user_wait_ms_sum` |
| `task_skip` | Skip rule hit, user picked Skip/Run-myself/Defer | `id`, `marker_matched`, `user_choice` |

**Implementation pattern for any subagent call:**

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

For orchestrator-side events (`task_start`, `task_done`, `task_halt`, `decision_gate`, `batch_done`) use `log-phase.sh wrap` when timing a single shell op, or the explicit `start`/`end` pair when timing spans multiple shell calls:

```bash
TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" start "batch" batch \
  "$(printf '{"slug":"%s","n_pending":%d,"parallel":%d}' "$SLUG" "$N" "$N_PAR")")"
# ... dispatch tasks, await completions ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$TOKEN" \
  "$(printf '{"tasks_dispatched":%d,"tasks_done":%d,"tasks_halted":%d,"parallel_factor":%.2f}' \
     "$DISPATCHED" "$DONE" "$HALTED" "$PFACTOR")"
```

For `decision_gate` (halted for user input), bracket the `AskUserQuestion` call with `start` (reason) / `end` (resolution). The helper auto-computes `wall_ms` so you get user-wait time for free.

**Per-batch aggregate event (one per outer iteration):**

| Kind | Fields |
|---|---|
| `batch_done` | `tasks_dispatched`, `tasks_done`, `tasks_halted`, `batch_wall_ms`, `parallel_factor` (actual concurrency observed) |

This is enough to answer, post-run:
- Average wall time per task, and the std deviation
- Codex review wall + size distribution
- Precheck hit rate (how often does it catch real spec drift?)
- Retry rate per task type
- Total user-wait time (decision gates)
- Whether parallelism actually helped (compare `parallel_factor` to N=3)

Repo-wide aggregate stays in `z-harness/metrics.jsonl`. The `scripts/log-event.sh` already appends to both per-run and repo-wide; no orchestrator change needed there.

## Detecting stalls (post-run + during-run heuristics)

In the `20260519T022355Z-data-overhaul` run, a parallel batch (T001/T010/T020) sat between `implement_start` and `review_start` for **189 minutes** with zero intermediate events. Three identical-length stalls = session pause (user away), not a runaway. To distinguish runaway from pause:

**During-run.** If you (the orchestrator) notice that more than 15 wall-clock minutes have passed since the last in-flight `implement_start` without any `implement_end` event, do one of:
- Push-notify the user with the in-flight task IDs and the elapsed time.
- If the user is the one driving the session and visible, just say so in chat.

<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->

**Post-run.** Use `jq` on `$BASE/metrics.jsonl` to flag gaps > 30 min between consecutive events of the same `run`/`id`:

```bash
jq -r '[.ts, .kind, (.id//.run//"")] | @tsv' "$BASE/metrics.jsonl" \
  | awk -F'\t' '{
      cmd = "date -j -f \"%Y-%m-%dT%H:%M:%SZ\" \"" $1 "\" +%s 2>/dev/null"
      cmd | getline ts; close(cmd)
      if (prev_ts && (ts - prev_ts) > 1800) {
        printf "GAP %dm at %s before %s/%s\n", (ts - prev_ts)/60, $1, $2, $3
      }
      prev_ts = ts
    }'
```

If gaps line up across multiple parallel tracks → session pause (benign). If only one track stalls → that subagent is stuck (real bug; escalate).

## Phase 9 — Memory review (auto)

This phase fires once per run, after the Finalize push-notify, before the session ends. It is a soft phase: all failure paths are silent skips — no halt, no retry.

1. **Run the memory-review helper:**

   ```bash
   MEMORY_REVIEW_OUT="$(bash scripts/run-memory-review.sh "$RUN" "implement-all")"
   MEMORY_REVIEW_FIRST_LINE="$(printf '%s' "$MEMORY_REVIEW_OUT" | head -1)"
   ```

2. **Skip path — first line is `STATUS: skipped <reason>`:**

   ```bash
   if [[ "$MEMORY_REVIEW_FIRST_LINE" == STATUS:\ skipped* ]]; then
     SKIP_REASON="${MEMORY_REVIEW_FIRST_LINE#STATUS: skipped }"
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$PHASE9_TOKEN" \
       "$(printf '{"phase":9,"name":"memory_review","skipped":true,"skip_reason":"%s"}' "$SKIP_REASON")"
     # exit phase quietly — no push-notify
   fi
   ```

   (Emit `PHASE9_TOKEN` just before the helper call: `PHASE9_TOKEN="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" start "phase9" memory_review '{}')"`)

3. **Ready path — first line is `STATUS: ready`:** parse the three artifact paths from subsequent lines:

   ```bash
   CUMULATIVE_DIFF_PATH="$(printf '%s' "$MEMORY_REVIEW_OUT" | sed -n '2p')"
   SPEC_PATH="$(printf '%s' "$MEMORY_REVIEW_OUT" | sed -n '3p')"
   TAGS_PATH="$(printf '%s' "$MEMORY_REVIEW_OUT" | sed -n '4p')"
   RUN_DIR="$(dirname "$CUMULATIVE_DIFF_PATH")"
   SLUG_FOR_DESC="${Z_HARNESS_SLUG:-$(basename "$BASE")}"
   ```

4. **Dispatch the review-agent:**

   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="review-agent",
     description="Memory review for <SLUG_FOR_DESC>",
     prompt="run_dir: <RUN_DIR>
   cumulative_diff_path: <CUMULATIVE_DIFF_PATH>
   spec_path: <SPEC_PATH>
   tags_path: <TAGS_PATH>
   index_path: docs/llm/INDEX.json
   run_id: <RUN>
   parent_command: implement-all"
   )
   ```

4a. **Optionally dispatch the axiom-extractor (if `AXIOM_READY` was emitted):**

    If `run-memory-review.sh` output contains a line starting with `AXIOM_READY`, parse the artifact path from that line and dispatch the axiom-extractor **alongside** the review-agent (parallel, fresh context):

    ```bash
    AXIOM_READY_LINE="$(printf '%s' "$MEMORY_REVIEW_OUT" | grep '^AXIOM_READY ' || true)"
    ```

    ```
    <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
      subagent_type="axiom-extractor",
      description="Axiom extraction for <SLUG_FOR_DESC>",
      prompt="mode: post-run <RUN>
    repo_root: <REPO_ROOT>"
    )
    ```

    **Proposes only — no auto-approve:** the axiom-extractor returns ≤5 candidate axioms as a fenced JSON array; nothing is written to the axiom store and no axiom is approved automatically. The candidates surface opportunities for later `/z-axiom-scan` / `/z-axiom-approve` review. Do not block on the axiom-extractor's return or error if it is unavailable.

5. **Parse agent return — extract single fenced ```json block:**

   ```python
   import re, json
   raw = agent_return_text
   m = re.search(r'```json\s*([\s\S]*?)```', raw)
   if not m:
       # no fenced block → review_agent_failed
       raise ValueError("no_fenced_block")
   try:
       candidates = json.loads(m.group(1))
   except json.JSONDecodeError as e:
       raise ValueError("json_parse_error") from e
   ```

   - **Parse failure (malformed output — no fenced block or invalid JSON):**
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" review_agent_malformed \
       "$(printf '{"run":"%s","excerpt":"%s"}' "$RUN" "$(printf '%s' "$raw" | head -c 200 | tr '"' "'")")"
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$PHASE9_TOKEN" \
       "$(printf '{"phase":9,"name":"memory_review","skipped":true,"skip_reason":"malformed_output"}')"
     ```
     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
     Exit phase.

   - **Agent errored / no fenced block:**
     ```bash
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" review_agent_failed \
       "$(printf '{"run":"%s","reason":"no_fenced_block"}' "$RUN")"
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$PHASE9_TOKEN" \
       "$(printf '{"phase":9,"name":"memory_review","skipped":true,"skip_reason":"agent_error"}')"
     ```
     Push-notify: "Memory review skipped (malformed output). Check `agents/review-agent.md` or run `/z-stats` to see recent review_agent_failed events."
     Exit phase.

6. **Empty candidates (`[]`):**

   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" review_agent_call \
     "$(printf '{"run":"%s","parent_command":"implement-all","candidates_emitted":0}' "$RUN")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$PHASE9_TOKEN" \
     "$(printf '{"phase":9,"name":"memory_review","skipped":false,"candidates_emitted":0}')"
   ```
   Exit phase quietly — no push-notify.

7. **Candidates ≥ 1:**

   a. **Persist to JSONL:**
      ```bash
      CANDIDATES_FILE="$RUN_DIR/memory-candidates.jsonl"
      python3 -c '
      import json, sys
      candidates = json.loads(sys.argv[1])
      with open(sys.argv[2], "w") as f:
          for c in candidates:
              f.write(json.dumps(c) + "\n")
      ' "$CANDIDATES_JSON_STR" "$CANDIDATES_FILE"
      ```

   b. **Log `review_agent_call`** (with token counts from Agent return usage block):
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" review_agent_call \
        "$(printf '{"run":"%s","parent_command":"implement-all","subagent_model":"haiku","subagent_input_tokens":%d,"subagent_output_tokens":%d,"candidates_emitted":%d}' \
           "$RUN" "$INPUT_TOKENS" "$OUTPUT_TOKENS" "$N_CANDIDATES")"
      ```

   c. **Emit `memory_review_complete` and exit phase:**
      ```bash
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" memory_review_complete \
        "$(printf '{"run":"%s","candidates_written":%d,"path":"%s"}' "$RUN" "$N_CANDIDATES" "$CANDIDATES_FILE")"
      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end "$PHASE9_TOKEN" \
        "$(printf '{"phase":9,"name":"memory_review","skipped":false,"candidates_emitted":%d}' "$N_CANDIDATES")"
      ```
      Store `N_CANDIDATES` and `CANDIDATES_FILE` in variables for Finalize to use in the push-notify. Exit phase.

**Event-kind reference for this phase:**

| Event kind | When emitted |
|---|---|
| `review_agent_call` | Agent returned candidates (including empty-array case) |
| `review_agent_failed` | Agent returned without a fenced block |
| `review_agent_malformed` | Agent returned with a fenced block that failed `json.loads` |
| `memory_review_complete` | N ≥ 1 candidates written to JSONL; Finalize will surface path in push-notify |

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

## Hard rules

- **Never** edit code yourself. Always go through `implementer` subagent.
- **Never** call Gemini/Codex CLIs directly. Always go through subagents.
- **Always** halt rather than guess on `decision_needed` / `spec_problem` / `needs_clarification`.
- **Always** push-notify on halts (regardless of `approval_only` vs `all`).
- **Never** auto-skip a non-eligible task forever — present it in the finalize summary so the user knows what's outstanding.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Setup 4.5 spec-precheck; Step 5 implementer; Step 5 remote-runner (REMOTE_VERIFY tasks); Step 6 reviewer; Phase 9 review-agent (memory review) |
| `ask_user` | yes | Setup 2a slug selection; Setup 7.5 test-runner template; Step 2 skip-flagged task decision; Step 5 implementer halt questions (needs_clarification / spec_problem / decision_needed); Step 6 no_change_on_retry decision; Step 7 second-review-failure decision; Step 7b test-failure decision |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
