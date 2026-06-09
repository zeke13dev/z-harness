# Hermes Integration Protocol v1

> **Audience:** Orchestrator implementers (Hermes or alternative).
> **Status:** REVISED — amended from review 2026-06-08.
> **Version:** 1.2.0
>
> This document defines the contract between z-harness (the planning layer)
> and any orchestrator (the execution layer) that wants to execute z-harness
> plans in parallel across independent pi sessions.
>
> **v1.0** (in-flight): Hermes reads MANIFEST.md + SHARED-CONCERNS.md directly.
> **v1.1** (this spec, original): z-harness writes `workstreams.json` as the machine-readable contract.
> **v1.2** (amended 2026-06-08): 5-rule DAG derivation, per-workstream `status` field, V1 parallelism constraint, crash-resumption, sanitization, severity alignment with z-plan-split.

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
| `workstreams` | array | yes | Ordered list of Workstream objects. First entries are setup (no deps); later entries are leaves. |
| `file_conflicts` | array | yes | Cross-workstream file overlaps. Empty array if none. |
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
| `parallel_group` | string or null | yes | Label (e.g., `"leaf-a"`) shared by workstreams that can run concurrently. `null` means this workstream runs alone at its dependency level. |

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

> **V1 constraint:** z-plan-split currently produces a linear run order
> ("Cross-cluster task parallelism is v2"). Consequently, V1
> `workstreams.json` from z-plan-split will have `depends_on: []` for all
> workstreams and `parallel_group: null` for all workstreams. The
> `depends_on` DAG and `parallel_group` fields are reserved for V2 when
> z-plan-split grows dependency-aware cluster planning.

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

Build a DAG from `depends_on`. Identify execution levels:

```
Level 0 (no deps):  ws-1
Level 1 (after ws-1): ws-2, ws-3
```

Workstreams at the same level that share a `parallel_group` can run
concurrently. The orchestrator MAY serialize workstreams at the same
level based on `file_conflicts` (especially `"high"` severity).

### 2. Create worktrees for independent workstreams

When a dependency level is unlocked (all deps satisfied):

```bash
git worktree add ../hermes-<slug>-<id> -b hermes/<slug>/<id>
```

Branch namespace: `hermes/<slug>/<id>`. Hermes owns this namespace.

Worktrees at the same level are created in parallel — they share the
same base commit.

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

## Orchestrator discretion

The following decisions belong to the orchestrator, NOT the manifest:

| Concern | Manifest provides | Orchestrator decides |
|---------|-------------------|---------------------|
| Concurrency cap | `parallel_group` | How many sessions to run at once (resource limit) |
| Serialize decision | `file_conflicts` | Whether to serialize workstreams with `"medium"` or `"low"` severity |
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

---

## Example

```json
{
  "protocol": "hermes-v1",
  "slug": "add-payment-system",
  "source": "/z-plan-split",
  "generated_at": "2026-06-08T14:22:00Z",
  "partial_tree": false,
  "workstreams": [
    {
      "id": "ws-1",
      "status": "ready",
      "name": "Payment types and config",
      "path": "z-harness/add-payment-system/shared-types/",
      "tasks": ["T001", "T002", "T003"],
      "depends_on": [],
      "parallel_group": null
    },
    {
      "id": "ws-2",
      "status": "ready",
      "name": "Stripe payment handler",
      "path": "z-harness/add-payment-system/stripe-handler/",
      "tasks": ["T004", "T005", "T006", "T007", "T008"],
      "depends_on": [],
      "parallel_group": null
    },
    {
      "id": "ws-3",
      "status": "ready",
      "name": "PayPal payment handler",
      "path": "z-harness/add-payment-system/paypal-handler/",
      "tasks": ["T009", "T010", "T011", "T012", "T013", "T014"],
      "depends_on": [],
      "parallel_group": null
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

**What the orchestrator does (V1 — sequential execution):**

1. Read `workstreams.json`. All workstreams have `status: "ready"`,
   `partial_tree: false`. Run order is ws-1 → ws-2 → ws-3.
2. Spawn ws-1 in worktree. Wait for `"done"`.
3. Spawn ws-2 in worktree (on the base commit that already includes
   ws-1's merge). Wait for `"done"`.
4. Spawn ws-3 in worktree. Wait for `"done"`.
5. All three merge cleanly (sequential, per `merge_order`).

> In V2, with `depends_on` and `parallel_group` populated, ws-2 and
> ws-3 would spawn in parallel after ws-1 completes, and the orchestrator
> would handle merge conflicts for shared files like `handler.rs`.

---

## Versioning

The `protocol` field is the version pin. Orchestrators MUST reject
manifests with unrecognized protocol versions.

Schema evolution rules:
- New top-level fields may be added in minor versions; orchestrators MUST
  ignore unknown fields (forward compatibility).
- Removing or renaming existing fields is a major version bump.
- `protocol` is always a string and always present.

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
