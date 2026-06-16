# Hermes Integration Protocol v1

> **Audience:** Orchestrator implementers (Hermes or alternative).
> **Status:** DORMANT — gated OFF by default as of 2026-06-16. Hermes parallelism is still present
> in `scripts/hermes/` but all entry points are behind the `workflow.hermes_enabled` config knob
> (default `false`). To revive, set `workflow.hermes_enabled = true` in `.z-harness/config.toml`.
> Deletion of `scripts/hermes/` is a **deferred cleanup** — files are kept to prevent bit-rot until
> a deliberate removal task is planned.
> **Version:** 1.4.0
>
> This document defines the contract between z-harness (the planning layer)
> and any orchestrator (the execution layer) that wants to execute z-harness
> plans in parallel across independent pi sessions.
>
> **v1.0** (in-flight): Hermes reads MANIFEST.md + SHARED-CONCERNS.md directly.
> **v1.1** (this spec, original): z-harness writes `workstreams.json` as the machine-readable contract.
> **v1.2** (amended 2026-06-08): 5-rule DAG derivation, per-workstream `status` field, V1 parallelism constraint, crash-resumption, sanitization, severity alignment with z-plan-split.
> **v1.3** (amended 2026-06-12): `parallel_group` is now populated as a derived `level-{depth}` label; new `scope_unknown` manifest boolean; concurrency execution contract (depends_on-driven level scheduler, HIGH-severity file-conflict serialization, `max_parallel_workstreams` cap, semaphore-for-lifetime); cross-plan `--slugs` mode contract; non-file shared-state limitation documented.
> **v1.4** (amended 2026-06-16): Hermes gated OFF by default (`workflow.hermes_enabled=false`). All concurrency/retry/timeout knobs moved from `HERMES_*` env vars to `workflow.*` file config. File deletion deferred.

---

## Principle

**Harness owns WHAT. Orchestrator owns HOW.**

- z-harness decomposes a plan into parallel workstreams.
  It writes a machine-readable manifest that declares WHAT to run,
  in what dependency order, with what merge constraints.
- The orchestrator reads the manifest and decides HOW to execute:
  session spawning, retry policy, model selection, timeout thresholds,
  question relay strategy, stall detection.
- The manifest IS the API contract. It lives in the harness repo.
  Anyone can build an orchestrator against it.

---

## Artifact: `workstreams.json`

**Location:** `z-harness/<slug>/workstreams.json`

**Generation:** Written by every z-harness planning command that produces
tasks. Each plan type derives workstreams differently:

- `/z-plan-split` — clusters map directly to workstreams (one per cluster).
  Generated during Phase 5 alongside MANIFEST.md.
- `/z-plan` — flat TASKS.md parsed into a task-level DAG from
  `**Depends on:**` lines. Workstreams derived via the 5-rule algorithm
  below. Generated as a post-plan step by z-harness or a Hermes bridge
  command.
- `/z-plan-light` — single workstream containing all tasks. Generated as
  a post-plan step. Optional: the orchestrator MAY treat the absence of
  `workstreams.json` as a single-workstream plan, using the slug
  directory as the sole workstream path.

**Lifecycle:** Generated once per plan run. The orchestrator SHOULD read
`workstreams.json` once at start. Not updated during execution — progress
lives in TASKS.md and `session-status.json`. Modifications to the file
mid-execution are not supported.

### Schema

```json
{
  "protocol": "hermes-v1",
  "slug": "<plan-slug>",
  "source": "<z-plan-split | z-plan | z-plan-light>",
  "generated_at": "<ISO 8601 UTC>",
  "partial_tree": false,
  "scope_unknown": false,
  "workstreams": [ ... ],
  "file_conflicts": [ ... ],
  "merge_order": [ ... ]
}
```

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `protocol` | string | yes | Always `"hermes-v1"`. Version pin for orchestrator parsing. |
| `slug` | string | yes | Plan identifier. Used for git branch naming (`hermes/<slug>/<id>`). MUST match `^[a-z0-9]+(-[a-z0-9]+)*$` (z-harness planning commands enforce this at generation; orchestrators SHOULD validate on read). |
| `source` | string | yes | Which z-harness command produced this plan: `"/z-plan-split"`, `"/z-plan"`, `"/z-plan-light"`. |
| `generated_at` | string | yes | ISO 8601 UTC timestamp of generation. |
| `partial_tree` | boolean | yes | True if one or more workstreams have `status: "failed"` (present in the `workstreams` array but not executable). Orchestrator SHOULD warn and MUST skip workstreams with `status: "failed"`. |
| `scope_unknown` | boolean | no (default `false`) | True when one or more task blocks in a flat `/z-plan` had no parseable `**Files:**` line, so per-workstream file scope could not be established. When `true`, `file_conflicts` is always `[]` (fail-safe: the orchestrator cannot know what is safe to parallelize). Orchestrators MUST treat `scope_unknown: true` the same as `serialize_all` — serialize all workstreams within this plan. |
| `workstreams` | array | yes | Ordered list of Workstream objects. First entries are setup (no deps); later entries are leaves. |
| `file_conflicts` | array | yes | Cross-workstream file overlaps. Empty array if none. When `scope_unknown` is `true` this is always empty. |
| `merge_order` | array | yes | Ordered list of workstream IDs for merge sequence. Authoritative. |

### Workstream object

```json
{
  "id": "ws-1",
  "status": "ready",
  "name": "Shared types and config",
  "path": "z-harness/add-auth/shared-types/",
  "tasks": ["T001", "T002", "T003", "T004"],
  "depends_on": [],
  "parallel_group": null
}
```

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `id` | string | yes | Stable workstream identifier (`"ws-1"`, `"ws-2"`, …). Referenced by `depends_on`, `merge_order`, and `file_conflicts`. |
| `status` | string | yes | `"ready"` (plan complete, executable) or `"failed"` (planning failed, must not execute). Set during generation. See `partial_tree`. |
| `name` | string | yes | Human-readable one-line description. For dashboards and user-facing messages. Untrusted — orchestrator MUST sanitize before UI rendering. |
| `path` | string | yes | Repo-relative path to the workstream's plan directory. This IS the BASE — `TASKS.md` lives at `<path>/TASKS.md`. |
| `tasks` | array | yes | Ordered task IDs belonging to this workstream. Mirrors TASKS.md. Informational — the orchestrator passes the whole `TASKS.md` to `z-implement-all`, not individual tasks. |
| `depends_on` | array | yes | Workstream IDs that must reach `"done"` before this workstream starts. Empty array means no dependencies. |
| `parallel_group` | string or null | yes | Derived label `"level-{depth}"` where `depth` is the longest path from a root in the workstream `depends_on` graph. All workstreams sharing a label are at the same dependency depth and are mutually independent — by construction they can run concurrently (Rule 7 passes). `null` only in legacy manifests that predate v1.3. |

### File conflict object

```json
{
  "file": "src/payments/handler.rs",
  "workstreams": ["ws-2", "ws-3"],
  "severity": "medium"
}
```

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `file` | string | yes | Repo-relative path touched by multiple workstreams. |
| `workstreams` | array | yes | Workstream IDs that touch this file. Always ≥2 entries. |
| `severity` | string | yes | Cascading precedence — first match wins. `"high"`: file matches `.*\.(sql|migration|schema|toml|yaml|yml|proto)$` OR basename is in `{Dockerfile, Makefile, package.json, package-lock.json, Cargo.lock, pnpm-lock.yaml, yarn.lock}`. `"medium"`: file matches `.*\.(rs|py|ts|tsx|js|jsx)$` AND appears in ≥3 workstreams. `"low"`: exactly 2 workstreams touch the same file (catch-all). Derived from z-plan-split SKILL.md Phase 4 severity heuristics. |

The orchestrator MAY serialize workstreams that share a `"high"` severity
conflict, even if they share a `parallel_group`. The orchestrator MAY also
ignore conflicts entirely and resolve them at merge time. This is left to
orchestrator discretion.

### Workstream derivation per plan type

**z-plan-split:** Generated from data already computed during
reconciliation (Phase 4–5). Clusters map 1:1 to workstreams.
`depends_on` reflects the cluster dependency DAG (setup clusters have
empty `depends_on`; leaf clusters depend on setup). `file_conflicts[]`
derived from SHARED-CONCERNS.md. `merge_order` from MANIFEST.md
`## Run order`.

> **v1.3 note:** z-plan-split currently produces a linear run order
> (cross-cluster task parallelism is future work). Consequently,
> `workstreams.json` from z-plan-split will have `depends_on: []` for all
> workstreams and `parallel_group: "level-0"` for all workstreams (all at
> the same depth because there are no cross-workstream dependencies). The
> `depends_on` DAG will be populated when z-plan-split grows
> dependency-aware cluster planning.

**z-plan (flat TASKS.md):** Generated by parsing `**Depends on:**`
lines across all tasks into a DAG via a deterministic 5-rule algorithm:

1. **Parse into DAG.** Extract every `**Depends on:** Txxx` line from
   every task block into a directed graph. Each task is a node; each
   `Txxx → this task` is an edge.
2. **Assign depths.** Depth 0 for tasks with no dependencies;
   `depth = max(parent depths) + 1` otherwise. If cycles are detected,
   the TASKS.md is malformed — reject, set `partial_tree: true`, and
   emit a minimal `workstreams.json` with an empty `workstreams` array.
3. **Group by depth.** Each depth group becomes a workstream candidate.
4. **Collapse linear chains.** If depth N has exactly 1 task AND that
   task is the sole dependency of depth N+1 (which also has exactly 1
   task), merge both depth groups into a single workstream. Repeat
   for consecutive 1-task chains (N, N+1, N+2, … all collapse).
5. **Split at parent boundaries.** Tasks at the same depth whose parents
   ended up in different workstreams after step 4 → separate workstreams,
   each at the same dependency level.

**Worked examples:**
- *Linear chain* (T001→T002→T003→T004): steps 4 collapses all into
  1 workstream `{T001,T002,T003,T004}`.
- *Fan-out* (T001→{T002,T003,T004,T005}): depth 0 = `{T001}` (1 task),
  depth 1 = `{T002,T003,T004,T005}` (4 tasks). Step 4 does not collapse
  (depth 1 not 1 task). Step 5: all depth-1 tasks share same parent
  workstream → 1 workstream. Result: ws-1 `{T001}`, ws-2
  `{T002,T003,T004,T005}`.
- *Two independent chains* (T001→T002, T003→T004): depth 0 =
  `{T001,T003}` (2 tasks → no collapse). depth 1 = `{T002,T004}`.
  Step 5: T002 parent is T001 (ws-1), T004 parent is T003 (ws-1).
  Same parent workstream → 1 workstream. Result: ws-1
  `{T001,T003}`, ws-2 `{T002,T004}`.
- *Deep fork* (T001 forks to T002→T003 and T004→T005;
  T006 depends on both T003 and T005): depth 0 = `{T001}`,
  depth 1 = `{T002,T004}`, depth 2 = `{T003,T005}`,
  depth 3 = `{T006}`. Step 4: depths 0-1 (1→2 tasks) no collapse;
  depths 1-2 (2→2 tasks) no collapse; depths 2-3 (2→1 tasks, but
  T006 has 2 parents) no collapse. Step 5: at depth 1, T002 and
  T004 share parent T001 (ws-1) → stays 1 workstream. At depth 2,
  T003 parent is T002, T005 parent is T004 (both in ws-2) → stays
  1 workstream. Result: ws-1 `{T001}`, ws-2 `{T002,T004}`,
  ws-3 `{T003,T005}`, ws-4 `{T006}` with
  `depends_on: ["ws-3"]`.

**z-plan-light (FIX.md):** Single workstream containing all tasks.
Identical to a flat z-plan with one task chain. `workstreams.json`
is optional for this source type; the orchestrator MAY treat its
absence as a single-workstream plan using the slug directory as the
sole workstream path.

---

## Execution contract

The orchestrator reads `workstreams.json` and follows this lifecycle:

### 1. Resolve dependency order

Build a DAG from `depends_on`. Identify execution levels using the
longest-path depth of each workstream:

```
Level 0 (no deps):    ws-1
Level 1 (after ws-1): ws-2, ws-3   ← share parallel_group "level-1"
```

`depends_on` is the sole scheduling gate (INV-2). `parallel_group` is a
derived label for orchestrator convenience — it is NOT a scheduling
mechanism. A workstream is eligible to start iff every id in its
`depends_on` has reached `"done"`.

**Concurrency cap (v1.3):** The orchestrator applies a
`max_parallel_workstreams` limit (default 1 ≡ sequential, matching
pre-v1.3 behavior — INV-5). The limit is implemented as a semaphore
**held for the full workstream lifetime** (from worktree creation through
merge), NOT just at spawn time. This bounds the number of live sessions,
not merely the spawn rate.

**File-conflict serialization:** Before dispatching a dependency level,
the orchestrator partitions its ready workstreams into sub-batches such
that no two workstreams in the same sub-batch share a `file_conflicts`
entry whose `severity == "high"`. High-severity pairs are always
serialized (even within a level) unless `serialize_high_severity` is
explicitly disabled in orchestrator config.

**Fail-safe serialization (INV-4):** If `manifest.scope_unknown` is
`true`, the orchestrator MUST treat the plan as fully serial (batch size
1, equivalent to `serialize_all`). Silent blind parallelism is forbidden
when conflict data is absent or low-confidence.

The orchestrator MAY also serialize workstreams at the same level based
on `"medium"` or `"low"` severity conflicts — this is left to orchestrator
discretion.

### 2. Create worktrees for independent workstreams

When a dependency level is unlocked (all deps satisfied):

```bash
git worktree add ../hermes-<slug>-<id> -b hermes/<slug>/<id>
```

Branch namespace: `hermes/<slug>/<id>`. Hermes owns this namespace.

Worktrees at the same level are created before spawning sessions. When
`max_parallel_workstreams > 1`, multiple worktrees are created
concurrently — they share the same base commit (INV-1: concurrent
workstreams write to isolated worktrees; the working tree is never
shared). Before spawning, the orchestrator sets `gc.auto=0` and
`GIT_OPTIONAL_LOCKS=0` to prevent concurrent auto-gc against the shared
object store.

### 3. Spawn pi sessions

Each session runs in its own worktree:

```bash
pi z-implement-all --tasks=<workstream.path>/TASKS.md
```

The `--tasks` flag targets exactly one workstream's task list. The
session runs the full z-harness loop: precheck → implement → review →
mark done. It commits changes to its own branch.

> **Note:** The `--tasks` fast path in `/z-implement-all` skips
> tree-validation gates (shared-concerns acknowledgement, partial-tree
> opt-in). The orchestrator is responsible for pre-validating these
> gates at the plan level before spawning individual workstream
> sessions. See `/z-implement-all` SKILL.md Setup step 1 (`--tasks`
> fast path) for details.

> **Non-file shared-state limitation:** Worktree isolation covers the
> git working tree only. It does NOT cover ports, databases, remote
> sandboxes, in-memory caches, or other process-level resources.
> Workstreams that share any such resource MUST be serialized by the
> orchestrator via `serialize_all: true` in orchestrator config. The
> `file_conflicts` list does not model these dependencies; the operator
> must identify them manually and set `serialize_all` accordingly.

### 4. Monitor all sessions

Each session writes `z-harness/<slug>/<id>/session-status.json`.
The orchestrator polls these files to track progress.

> **Resumption after orchestrator crash:** If the orchestrator process
> itself restarts, it recovers state by re-reading `workstreams.json`
> and scanning for existing worktree branches matching
> `hermes/<slug>/*`. For each branch found: read its
> `session-status.json` to determine whether the workstream is
> `"done"`, `"running"`, `"halted"`, or `"paused"`. Workstreams
> without a corresponding branch are not started. Workstreams with
> `"running"` or `"paused"` status are re-spawned (re-running
> `/z-implement-all --tasks=<path>/TASKS.md` in the existing worktree).
> Merged branches (no longer present on disk) are treated as done.

```json
{
  "status": "running" | "done" | "halted" | "paused",
  "halt_reason": "decision_needed" | "spec_problem" | "needs_clarification" | null,
  "halt_description": "Free-text summary of the halt (untrusted — orchestrator MUST sanitize before shell interpolation or UI rendering)",
  "tasks_done": 2,
  "tasks_total": 5,
  "current_task": "T003",
  "updated_at": "2026-06-08T14:30:00Z"
}
```

**Status handling:**
- `"running"` → continue polling.
- `"done"` → workstream complete. Unlock dependents.
- `"halted"` → blocked on user input. Relay `halt_reason` + `halt_description` to user.
- `"paused"` → compaction breakpoint. Re-spawn same invocation (resumes from TASKS.md).
- Session exits without updating status → treat as crash. Retry once.

**Question relay with dedup:**

Before surfacing a halt, check if another session has the same
`halt_reason` + `halt_description`. If yes, present as a single
question: "Sessions ws-2 and ws-3 both need: …"

Answers are written back to `z-harness/<slug>/<id>/hermes-resolve.json`:

```json
{
  "decision_id": "DEC-001",
  "chosen": "User's chosen option",
  "rationale": "User's rationale"
}
```

**Stuck detection:**

If `current_task` and `tasks_done` haven't changed in N minutes
(orchestrator-configurable, default 15), surface: "ws-2 appears stuck
on T003 (15 min no progress). Kill? Wait? Investigate?"

### 5. Merge worktrees in declared order

When ALL workstreams in a dependency level reach `"done"`:

```bash
# Merge in merge_order sequence
git merge hermes/<slug>/ws-2
git merge hermes/<slug>/ws-3
```

Each merge completes before the next begins. After a successful merge:
delete the worktree and branch. Preserve the plan directory for post-run
analysis.

### 6. Surface merge conflicts to user

If a merge fails:

The orchestrator halts and presents:
- Conflicting file(s)
- Which workstream caused the conflict
- `git diff` output

User options:
- **Resolve manually** — edit file, `git add`, `git merge --continue`
- **Spawn resolution session** — Hermes starts a pi session to resolve
- **Skip this workstream** — leave it unmerged, continue with partial plan
- **Abort plan** — revert all merged workstreams

### 7. Cleanup

After all workstreams are merged:
- Delete all worktrees and branches.
- The plan is fully applied to main.

---

## Cross-plan orchestration (v1.3 contract — `--slugs` mode)

> **Status:** Contract documented here. Implementation lives in
> `scripts/hermes-execute.py --slugs` and `scripts/hermes/cross_plan.py`.
> Refer to those modules for runtime behavior.

When the orchestrator is invoked with multiple plan slugs
(`--slugs=a,b,c` or `--plan-set FILE`), it runs all plans as a
coordinated plan-set. The contract:

### Scope conflict detection

Before scheduling, the orchestrator builds a **plan conflict graph**:
two plans conflict iff their file-scope path-sets intersect, OR either
plan has `scope_unknown: true` (fail-safe — INV-4). Scope is read from
the active-plan registry and/or each plan's `workstreams.json`
`file_conflicts` / `scope_unknown`.

### Lock ordering (INV-6: deadlock-free)

Plan-level claim locks are always acquired in **sorted ascending slug
order**. This applies even when two super-orchestrators run concurrently
— the fixed ordering prevents AB/BA deadlocks.

### Scheduling

- Scope-disjoint plans run concurrently, bounded by `max_parallel_plans`.
- Conflicting plans serialize against each other.
- Each plan internally runs its own within-plan scheduler (section 1–7
  above), so per-plan concurrency is independently governed by
  `max_parallel_workstreams`.
- A plan that fails does NOT abort scope-disjoint peers; its lock is
  released, its dependents (if any) are blocked.

### Global merge mutex

A single in-process lock serializes the final merge-to-base step across
all plans in the set. This prevents two plans from merging into the
shared base concurrently (cross-plan merge race).

---

## Operator runbook

> **Dormancy notice:** Hermes is gated OFF by default. The steps below only apply after you have
> opted in by adding `workflow.hermes_enabled = true` to `.z-harness/config.toml`.

### Reviving Hermes

Add the following to `.z-harness/config.toml` (create the file if it does not exist):

```toml
[workflow]
hermes_enabled = true
```

With `hermes_enabled = false` (the default), all workstream-generation and cross-plan dispatch
calls inside `/z-plan`, `/z-implement-all`, and `/z-plan-split` are no-ops. The existing inline
`**Files:**`-dedup fallback handles deduplication in the single-session path.

### Within-plan parallel execution

Enable concurrency by setting `max_parallel_workstreams` in the config file:

```toml
[workflow]
hermes_enabled = true
max_parallel_workstreams = 3
```

With the default `max_parallel_workstreams = 1`, execution is fully sequential and
byte-identical to pre-v1.3 behavior (INV-5).

**Config knobs (all file-based via `.z-harness/config.toml`):**

| Key | Default | Effect |
|-----|---------|--------|
| `workflow.hermes_enabled` | `false` | Master gate — must be `true` for any parallelism |
| `workflow.max_parallel_workstreams` | `1` | Max concurrent workstreams within one plan |
| `workflow.serialize_all` | `false` | Force fully-sequential; overrides conflict analysis |
| `workflow.serialize_high_severity` | `true` | Serialize HIGH-severity file-conflict pairs within a level |
| `workflow.max_parallel_plans` | `1` | Max concurrent plans within one cross-plan run |
| `workflow.workstream_timeout_minutes` | `60` | Per-workstream wall-clock cap |
| `workflow.max_retries` | `1` | Max re-spawns on workstream crash |

> **Note:** The old `HERMES_MAX_PARALLEL`, `HERMES_MAX_PARALLEL_PLANS`, `HERMES_SERIALIZE_ALL`,
> `HERMES_SERIALIZE_HIGH_SEVERITY`, `HERMES_WORKSTREAM_TIMEOUT_MINUTES`, and `HERMES_MAX_RETRIES`
> environment variables have been **removed** (as of v1.4). Setting them has no effect. Use the
> `workflow.*` file knobs above.

### Cross-plan execution

Run multiple slugs as a coordinated plan-set:

```bash
python3 scripts/hermes-execute.py --slugs slug-a,slug-b,slug-c

# File listing slugs (one per line)
python3 scripts/hermes-execute.py --plan-set plans.txt
```

`--slugs` and `--plan-set` are mutually exclusive with `--slug`. Plans with
overlapping file scope are automatically serialized; disjoint plans run
concurrently up to `workflow.max_parallel_plans` (set in config file).

### Non-file shared-state limitation and escape hatch

**Important:** Worktree isolation covers the git working tree only. It does
NOT protect databases, ports, remote sandboxes, in-memory caches, or other
process-level resources. The `file_conflicts` list does not model these
dependencies.

If workstreams or plans share any such resource, force fully-sequential
execution via the config file:

```toml
[workflow]
hermes_enabled = true
serialize_all = true
```

The operator must identify non-file shared-state dependencies manually and set
`workflow.serialize_all = true` (or `workflow.max_parallel_workstreams = 1`)
accordingly. There is no automatic detection for these cases.

### Deferred cleanup

The `scripts/hermes/` directory and `scripts/hermes-execute.py` are intentionally **not deleted**
in this release. They are kept dormant (behind the `hermes_enabled` gate) to prevent bit-rot.
A future cleanup task will remove these files once the gating strategy is confirmed stable.

---

## Orchestrator discretion

The following decisions belong to the orchestrator, NOT the manifest:

| Concern | Manifest provides | Orchestrator decides |
|---------|-------------------|---------------------|
| Concurrency cap | `parallel_group` (level labels) | `max_parallel_workstreams` (default 1 = sequential) |
| Serialize all | `scope_unknown` | `serialize_all` flag (overrides conflict analysis; also triggered by `scope_unknown`) |
| High-severity serialize | `file_conflicts[].severity` | `serialize_high_severity` flag (default `true` — HIGH pairs always serialized) |
| Low/medium serialize | `file_conflicts` | Whether to serialize workstreams with `"medium"` or `"low"` severity |
| Cross-plan concurrency cap | — | `max_parallel_plans` (default 1 per plan-set run) |
| Retry policy | — | Max retries, backoff, re-spawn on crash |
| Model selection | — | Which model per session (may respect task `**Complexity:**` stamps) |
| Timeout | `tasks` count (hint) | Per-workstream wall-clock cap |
| Stall threshold | — | Minutes before flagging a session as stuck |
| Question batching | `halt_reason` | Dedup strategy, presentation order |
| Merge auto-resolution | — | Whether to attempt trivial conflict resolution before surfacing |

---

## Schema validation

A valid `workstreams.json` MUST satisfy:

1. Every `depends_on` ID exists in `workstreams[].id`
2. No dependency cycles
3. `merge_order` is a permutation of `workstreams[].id`
4. `file_conflicts[].workstreams` entries reference valid workstream IDs
5. Every path is repo-relative (no `../`, no absolute, no `//`, no trailing `/`)
6. `workstreams[].path + "/TASKS.md"` resolves to an existing file
7. No workstream in a `parallel_group` may appear in the transitive `depends_on` of any other workstream in the same group, and vice versa (parallel-grouped workstreams must be mutually independent)
8. (v1.3) `scope_unknown` is a boolean (`true` or `false`); if `scope_unknown` is `true`, `file_conflicts` MUST be `[]`

---

## Example

```json
{
  "protocol": "hermes-v1",
  "slug": "add-payment-system",
  "source": "/z-plan-split",
  "generated_at": "2026-06-12T10:00:00Z",
  "partial_tree": false,
  "scope_unknown": false,
  "workstreams": [
    {
      "id": "ws-1",
      "status": "ready",
      "name": "Payment types and config",
      "path": "z-harness/add-payment-system/shared-types/",
      "tasks": ["T001", "T002", "T003"],
      "depends_on": [],
      "parallel_group": "level-0"
    },
    {
      "id": "ws-2",
      "status": "ready",
      "name": "Stripe payment handler",
      "path": "z-harness/add-payment-system/stripe-handler/",
      "tasks": ["T004", "T005", "T006", "T007", "T008"],
      "depends_on": ["ws-1"],
      "parallel_group": "level-1"
    },
    {
      "id": "ws-3",
      "status": "ready",
      "name": "PayPal payment handler",
      "path": "z-harness/add-payment-system/paypal-handler/",
      "tasks": ["T009", "T010", "T011", "T012", "T013", "T014"],
      "depends_on": ["ws-1"],
      "parallel_group": "level-1"
    }
  ],
  "file_conflicts": [
    {
      "file": "src/payments/handler.rs",
      "workstreams": ["ws-2", "ws-3"],
      "severity": "medium"
    }
  ],
  "merge_order": ["ws-1", "ws-2", "ws-3"]
}
```

**What the orchestrator does (v1.3 — concurrency-capable execution):**

1. Read `workstreams.json`. All workstreams have `status: "ready"`,
   `partial_tree: false`, `scope_unknown: false`. Dependency levels:
   - Level 0: ws-1 (no deps)
   - Level 1: ws-2, ws-3 (both depend on ws-1; share `parallel_group: "level-1"`)

2. Start Level 0: spawn ws-1 in a worktree. Wait for `"done"`.

3. Start Level 1: ws-2 and ws-3 are both ready. Check file conflicts:
   `handler.rs` has `severity: "medium"` — serialized or run in parallel
   per orchestrator config (`serialize_high_severity` only serializes
   `"high"` severity by default). With default `max_parallel_workstreams=1`,
   ws-2 and ws-3 run sequentially (INV-5: cap=1 ≡ legacy sequential).
   With `max_parallel_workstreams=2`, ws-2 and ws-3 spawn concurrently,
   each in its own worktree.

4. All three merge cleanly in `merge_order` sequence (merge is always
   sequential — INV-3).

> **Legacy manifests** (pre-v1.3) will have `parallel_group: null` for all
> workstreams and may omit `scope_unknown`. Orchestrators MUST treat
> `null` parallel_group as equivalent to `scope_unknown: true` —
> serialize all workstreams (fail-safe, INV-4). Missing `scope_unknown`
> defaults to `false` (additive field, forward-compatible — INV-7).

---

## Versioning

The `protocol` field is the version pin (`"hermes-v1"`). It remains
unchanged across v1.x minor revisions. Orchestrators MUST reject
manifests with unrecognized protocol versions (e.g., `"hermes-v2"`).

Schema evolution rules:
- New top-level fields may be added in minor versions; orchestrators MUST
  ignore unknown fields (forward compatibility — INV-7).
- Removing or renaming existing fields is a major version bump
  (would require `"hermes-v2"`).
- `protocol` is always a string and always present.
- The `scope_unknown` and populated `parallel_group` fields (v1.3) are
  additive. Pre-v1.3 manifests omitting `scope_unknown` default to
  `false`; pre-v1.3 manifests with `parallel_group: null` are treated
  as scope-unknown (fail-safe) by v1.3+ orchestrators.

| Version | Key changes |
|---------|-------------|
| v1.0 | Hermes reads MANIFEST.md + SHARED-CONCERNS.md directly (pre-schema) |
| v1.1 | `workstreams.json` schema introduced; `protocol: "hermes-v1"` pin |
| v1.2 | 5-rule DAG derivation, `status` field, crash-resumption, sanitization |
| v1.3 | `parallel_group` populated (`level-{depth}`); `scope_unknown`; concurrency execution contract; cross-plan `--slugs` mode; non-file shared-state limitation |
| v1.4 | Hermes gated OFF by default (`workflow.hermes_enabled=false`); `HERMES_*` env vars removed; all knobs via `workflow.*` file config; file deletion deferred |

---

## Relationship to other artifacts

| Artifact | Audience | Role |
|----------|----------|------|
| `MANIFEST.md` | Human | Readable plan overview, clusters table, decisions log |
| `SHARED-CONCERNS.md` | Human | File-overlap narrative with ack-gate |
| `workstreams.json` | Machine | Decomposition for orchestrator consumption |
| `TASKS.md` (per workstream) | Both | Durable task list; consumed by `z-implement-all` |
| `session-status.json` | Machine | Per-session liveness signal for orchestrator monitoring |
| `hermes-resolve.json` | Machine | Answer channel for halted sessions |
| `SPEC.md` / `PLAN.md` | Both | Design documents; read by implementer subagents, not by orchestrator |
