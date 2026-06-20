---
name: z-reconcile
disable-model-invocation: false
description: "Read-mostly workspace audit: surveys git worktrees, plan slugs, the active-plan registry, claim locks, uncommitted work, and follow-up entries; cross-references them into a single consistency report. Default run is pure read (zero mutations); cleanup is opt-in per-flag with per-item confirmation."
argument-hint: "[--prune-worktrees] [--reap-registry] [--clean-locks] [--archive-plans] [--open-followups] [--save] [<save-path>]"
runtime: c1
driver_features_required:
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-reconcile`**. Read-mostly workspace audit and reconciliation. Uses only Bash/Python; no subagent dispatch, no LLM calls.

**DEFAULT RUN IS ZERO MUTATIONS.** A run with no flags prints a grouped report and exits. Every mutation phase is gated behind an explicit flag AND a per-item confirmation via `AskUserQuestion`.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## Phase 0 — Parse arguments

Parse `$ARGUMENTS` for the following flags and the optional positional `<save-path>`:

- `--prune-worktrees` — opt-in prune phase (Phase 2)
- `--reap-registry` — opt-in registry reap phase (Phase 5)
- `--clean-locks` — opt-in lock cleanup phase (Phase 4)
- `--archive-plans` — opt-in plan archive phase (Phase 3)
- `--open-followups` — opt-in follow-up creation phase (Phase 6)
- `--save` — write report to disk (Phase 7)
- `<save-path>` — optional positional (non-flag) argument: the path to write the report; implies `--save`. Defaults to `RECONCILE.md` at the repo root when `--save` is present and no positional path is given.

If any unrecognized flag is present, emit:

```
Error: unknown flag '<flag>'.
Usage: /z-reconcile [--prune-worktrees] [--reap-registry] [--clean-locks] [--archive-plans] [--open-followups] [--save] [<save-path>]
```

and stop.

Store: `DO_PRUNE_WORKTREES`, `DO_REAP_REGISTRY`, `DO_CLEAN_LOCKS`, `DO_ARCHIVE_PLANS`, `DO_OPEN_FOLLOWUPS`, `DO_SAVE`, `SAVE_PATH`.

## Phase 1 — Collect facts and render read-only report

### Step 1a — Resolve paths and defaults

```bash
_ZR_PLUGIN="${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}"
_ZR_BASE="$(bash "$_ZR_PLUGIN/scripts/plan-path.sh" base_dir 2>/dev/null)"
_ZR_REPO_ROOT="$(git -C "${_ZR_BASE:-$PWD}" rev-parse --show-toplevel 2>/dev/null || echo "${_ZR_BASE:-$PWD}")"

# Default save path
if [ -z "$SAVE_PATH" ]; then
  SAVE_PATH="$_ZR_REPO_ROOT/RECONCILE.md"
fi
```

### Step 1b — Resolve default branch dynamically

```bash
_ZR_DEFAULT_BRANCH="$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')"
if [ -z "$_ZR_DEFAULT_BRANCH" ]; then
  _ZR_DEFAULT_BRANCH="main"
fi
```

### Step 1c — Collect worktree facts

For each entry in `git worktree list --porcelain` (excluding the main worktree if desired — include all), collect `WorktreeFacts` fields:

- `path` — the worktree path
- `branch` — branch name (from `branch` line), or `null` if detached HEAD
- `head_sha` — HEAD SHA (from `HEAD` line)
- `is_detached` — true when the `branch` line is absent or reads `detached`
- `has_uncommitted` — from `git -C <path> status --porcelain` (non-empty output = true)
- `remote_reachable` — attempt `timeout 5 git -C <path> ls-remote --exit-code origin HEAD 2>/dev/null` (the `timeout 5` is mandatory: a hung or unreachable remote must not block this read-only audit, which iterates every worktree); if this times out (exit 124) or fails for any other reason, set `remote_reachable=false`
- `has_unpushed` — if `remote_reachable` is true: count commits via `git -C <path> log @{u}..HEAD 2>/dev/null | wc -l`; > 0 means unpushed; set to `null` if remote unreachable or no upstream set
- `is_head_ancestor_of_default` — `git -C <path> merge-base --is-ancestor HEAD origin/$_ZR_DEFAULT_BRANCH 2>/dev/null`; true on exit 0, false on exit 1, `null` if the check cannot run
- `default_branch` — `$_ZR_DEFAULT_BRANCH`
- `merge_evidence` — `merged` if `git -C <path> branch -r --merged origin/$_ZR_DEFAULT_BRANCH 2>/dev/null` contains the current branch; `merged-uncertain` if the branch is absent from `--merged` but `git -C <path> log --oneline -1 2>/dev/null` finds a squash-pattern match (heuristic: commit subject contains "(#" suggesting a squash PR); otherwise `not-merged`; `unknown` if the check fails

Classify each worktree by passing the facts JSON to `scripts/reconcile.py`:

```bash
_ZR_WT_CLASS_JSON="$(python3 "$_ZR_PLUGIN/scripts/reconcile.py" classify-worktree --json "$_ZR_WT_FACTS_JSON")"
_ZR_WT_CLASS="$(echo "$_ZR_WT_CLASS_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['class'])")"
_ZR_WT_ACTION="$(echo "$_ZR_WT_CLASS_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['action'])")"
```

### Step 1d — Collect plan facts

```bash
_ZR_PLANS_BASE="$_ZR_BASE/plans"
```

Enumerate all plan slugs via:

```bash
_ZR_ALL_SLUGS="$(bash "$_ZR_PLUGIN/scripts/plan-path.sh" all_plan_slugs 2>/dev/null)"
```

**Exclude** any slug whose path is under `$_ZR_PLANS_BASE/.abandoned/`. For each remaining slug, collect `PlanFacts`:

- `slug` — the slug string
- `path` — resolved plan dir path (`bash scripts/plan-path.sh resolve_plan_path "$slug"`)
- `has_tasks_file` — true if `$path/TASKS.md` exists
- `all_tasks_done` — true if every task line in TASKS.md matches `[x]`; null if no TASKS.md
- `has_only_precontext` — true if only INTENT.md / precontext files exist (no TASKS.md, no LEDGER.md, no events.jsonl)
- `has_merge_evidence` — true if any of: a `plan_merged` event exists in events.jsonl for this slug, a `MERGED.md` or `ARCHIVED.md` or `RECONCILE-ARCHIVED.md` sentinel file exists, or a git merge commit message containing the slug is reachable (`git log --oneline --grep="$slug" --merges 2>/dev/null` is non-empty)
- `latest_activity_ts` — `max(latest events.jsonl mtime for slug, max mtime of files in plan dir)`; null if no signals available
- `is_abandoned` — false (abandoned plans are excluded by the scan above)

Classify each plan:

```bash
_ZR_PL_CLASS_JSON="$(python3 "$_ZR_PLUGIN/scripts/reconcile.py" classify-plan --json "$_ZR_PL_FACTS_JSON")"
_ZR_PL_CLASS="$(echo "$_ZR_PL_CLASS_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['class'])")"
_ZR_PL_ACTION="$(echo "$_ZR_PL_CLASS_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['action'])")"
```

### Step 1e — Collect registry records

```bash
_ZR_REGISTRY_JSON="$(python3 "$_ZR_PLUGIN/scripts/active-plan-registry.py" list --json 2>/dev/null || echo "[]")"
```

Parse the JSON array into a list of `RegistryRecord` objects. If JSON is invalid or command fails, treat as empty list and note `(registry unavailable)`.

### Step 1f — Collect claim lock facts

Claim lock files live under the claims directory (`bash "$_ZR_PLUGIN/scripts/plan-path.sh" claims_dir`). Resolve the per-slug path as:

```bash
_ZR_CLAIMS_DIR="$(bash "$_ZR_PLUGIN/scripts/plan-path.sh" claims_dir)"
_ZR_LOCK_PATH="$_ZR_CLAIMS_DIR/$slug.lock"
```

For each slug where `$_ZR_LOCK_PATH` exists on disk, collect `ClaimLockFacts`:

- `slug` — the slug
- `lock_path` — absolute path to the lock file
- `daemon_pid` — parse the `pid` field from the lock file JSON (if parseable)
- `daemon_alive` — `kill -0 $daemon_pid 2>/dev/null` returns 0
- `reap_status` — call `bash "$_ZR_PLUGIN/scripts/plan-claim.sh" reap-stale --slug "$slug" 2>/dev/null`; map exit codes: 0=`held`, 1=`free`, 2=`stale`, 3=`corrupt`; on any other error set `unknown`

### Step 1g — Collect uncommitted work attributed to plan slugs

```bash
_ZR_GIT_STATUS="$(git -C "$_ZR_REPO_ROOT" status --porcelain 2>/dev/null)"
```

For each line in git status output, extract the file path and check whether it overlaps with any plan slug's directory (`$_ZR_PLANS_BASE/<slug>/`). Collect the set of slugs with attributed uncommitted changes (`uncommitted_slugs`).

### Step 1h — Run cross-reference join

Call `cross_ref_join` from `scripts/reconcile.py` by constructing the `CrossRefInput` bundle from the collected facts and invoking the Python function directly:

```python
import sys
sys.path.insert(0, "<_ZR_PLUGIN>/scripts")
from reconcile import (
    CrossRefInput, cross_ref_join,
    WorktreeFacts, PlanFacts, RegistryRecord, ClaimLockFacts,
)
# ... build inp from collected facts ...
flags = cross_ref_join(inp)
```

Store `flags` for use in the report.

### Step 1i — Render the report

Print a grouped report with exactly these six sections. Each item carries its classification and recommended action. Surface-only items are annotated `[surface-only]`; auto-prune-eligible items (class `dead`) are annotated `[auto-prune-eligible]` only when `--prune-worktrees` was passed.

```
=== /z-reconcile report — <ISO timestamp> ===

## Worktrees

  <path>  [<class>]  <recommended action>  [surface-only | auto-prune-eligible]
  ...
  (none found)

## Plans

  <slug>  [<class>]  <recommended action>
  ...
  (none found)

## Registry

  <run_id>  slug=<slug>  status=<status>  hb_age=<age>  pid=<pid>
  ...
  (none found / registry unavailable)

## Locks

  <slug>  lock=<lock_path>  reap=<reap_status>  daemon_alive=<true|false>
  [orphan — no live registry record]
  ...
  (none found)

## Uncommitted

  <slug>  <N> files with uncommitted changes attributed to this plan slug
  ...
  (none)

## Follow-ups

  (pass --open-followups to create entries for advisory findings)
  Advisory findings flagged:
    <slug>  tasks-complete-unmerged — all tasks [x] but no merge evidence
    ...
  (none)

=== Cross-reference flags ===
  merged_worktree_on_disk:         <true|false>
  complete_plan_no_merge_evidence: <true|false>
  orphan_claim_lock:               <true|false>
  uncommitted_work_for_plan:       <true|false>
```

**Worktree classification surface rules (always enforced):**
- `dirty`, `detached`, `merged-uncertain`, `unknown-remote` — always `[surface-only]`; never offered for auto-prune regardless of flags.
- `dead` — auto-prune-eligible only when `--prune-worktrees` is passed; show `[auto-prune-eligible]`.
- `active` — no action annotation.

**Plan classification notes:**
- `tasks-complete-unmerged` — always advisory; flagged in Follow-ups section; never auto-acted even when `--archive-plans` is passed.

After rendering, if no mutation flags were passed, print:

```
Run with --prune-worktrees, --archive-plans, --clean-locks, --reap-registry, or --open-followups to perform cleanup actions (each with per-item confirmation).
```

## Phase 2 — --prune-worktrees (opt-in)

Skip this phase unless `DO_PRUNE_WORKTREES` is set.

For each worktree classified `dead` (and ONLY `dead` — never `dirty`, `detached`, `merged-uncertain`, `unknown-remote`, or `active`):

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the per-item confirmation question and accept yes/no before calling git worktree remove -->
Use `AskUserQuestion` to prompt:

```
Prune worktree?

  Path:   <worktree path>
  Branch: <branch>
  Class:  dead (clean, no unpushed, HEAD ancestor of <default_branch>)

Remove this worktree with `git worktree remove`? [yes/no]
```

If the user answers `yes`:

```bash
git worktree remove --force "<path>" 2>&1
```

Print:
```
  Pruned: <path>
```

If the user answers anything other than `yes` (case-insensitive):
```
  Skipped: <path>
```

If no worktrees are classified `dead`, print:
```
Phase 2 (--prune-worktrees): no dead worktrees found. Nothing to prune.
```

## Phase 3 — --archive-plans (opt-in)

Skip this phase unless `DO_ARCHIVE_PLANS` is set.

Eligible plans for archiving: those classified `precontext-only-aged` or `stale-in-progress`.

**NEVER** offer `tasks-complete-unmerged` plans for archive — those are advisory only and handled via `--open-followups`. **NEVER** archive an `in-progress` plan.

For each eligible plan:

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the per-item confirmation question and accept yes/no before moving any plan directory -->
Use `AskUserQuestion` to prompt:

```
Archive plan?

  Slug:   <slug>
  Path:   <path>
  Class:  <class>
  Reason: <recommended action>

Move to <_ZR_PLANS_BASE>/.abandoned/<slug>/ and write RECONCILE-ARCHIVED.md sentinel? [yes/no]
```

If the user answers `yes`:

```bash
_ZR_ARCHIVE_DEST="$_ZR_PLANS_BASE/.abandoned/$slug"
mkdir -p "$_ZR_ARCHIVE_DEST"
# Move the plan directory contents (NOT a delete)
cp -r "$plan_path/." "$_ZR_ARCHIVE_DEST/"
# Write sentinel
cat > "$_ZR_ARCHIVE_DEST/RECONCILE-ARCHIVED.md" <<SENTINEL
# RECONCILE-ARCHIVED

archived_at: <ISO timestamp>
reason: <class> — <recommended action>
original_path: <plan_path>
SENTINEL
# Remove original after copy
rm -rf "$plan_path"
```

Print:
```
  Archived: <slug> → <_ZR_ARCHIVE_DEST>
```

**Invariants:**
- `INTENT.md`, `SPEC.md`, `TASKS.md`, `LEDGER.md` are never deleted — they are moved with the directory.
- A subsequent `/z-reconcile` run sees the slug under `.abandoned/` and excludes it from slug scans; the `RECONCILE-ARCHIVED.md` sentinel is how the exclusion is recognized.

If the user answers anything other than `yes`:
```
  Skipped: <slug>
```

If no eligible plans found:
```
Phase 3 (--archive-plans): no archivable plans found (precontext-only-aged or stale-in-progress).
```

## Phase 4 — --clean-locks (opt-in)

Skip this phase unless `DO_CLEAN_LOCKS` is set.

**The lock removal policy is strict and non-negotiable:**

A lock may only be removed when ALL THREE conditions hold simultaneously:
1. `plan-claim.sh reap-stale --slug <S>` exits 1 (`free`), 2 (`stale`), or 3 (`corrupt`).
2. There is **no matching live registry record** for this slug (i.e., slug not in `$_ZR_REGISTRY_JSON`).
3. The daemon PID (parsed from the lock file) is **not alive** (`kill -0 $pid` fails).

**Never** call `rm` directly on a lock file. Always go through `plan-claim.sh reap-stale` first. Never remove a lock whose daemon PID is alive, regardless of reap-stale output.

For each lock where reap-stale reported `held` (exit 0): skip silently (lock is live).

For each lock where all three conditions hold:

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the per-item confirmation question and accept yes/no before removing any claim lock file -->
Use `AskUserQuestion` to prompt:

```
Remove claim lock?

  Slug:        <slug>
  Lock path:   <lock_path>
  Reap status: <free|stale|corrupt>
  Registry:    no live record
  Daemon PID:  <pid or none> (not alive)

Remove this stale lock file? [yes/no]
```

If the user answers `yes`:

```bash
rm -f "<lock_path>"
```

Print:
```
  Removed lock: <lock_path>
```

If the user answers anything other than `yes`:
```
  Skipped: <lock_path>
```

If no locks meet the removal criteria:
```
Phase 4 (--clean-locks): no removable locks found.
```

## Phase 5 — --reap-registry (opt-in)

Skip this phase unless `DO_REAP_REGISTRY` is set.

Enumerate all registry records via `active-plan-registry.py list --json`. Identify stale records: those with `status == "stale"` or whose `last_heartbeat` is more than 30 minutes old and `status != "running"`.

**Do NOT call the global `reap` subcommand** (`active-plan-registry.py reap`) — it is all-or-nothing and is not used for per-item flow. Each record is deregistered individually via `deregister --run-id <id>`.

For each stale record:

<!-- RUNTIME-GATE: ask_user; category=risk; non-supporting drivers must surface the per-item confirmation question and accept yes/no before calling active-plan-registry.py deregister -->
Use `AskUserQuestion` to prompt:

```
Deregister stale registry record?

  run_id:    <run_id>
  slug:      <slug>
  status:    <status>
  hb_age:    <age>
  host:      <host>

Remove this record via `active-plan-registry.py deregister --run-id <run_id>`? [yes/no]
```

If the user answers `yes`:

```bash
python3 "$_ZR_PLUGIN/scripts/active-plan-registry.py" deregister --run-id "<run_id>" 2>&1
```

Print:
```
  Deregistered: <run_id> (slug=<slug>)
```

If the user answers anything other than `yes`:
```
  Skipped: <run_id>
```

If no stale records found:
```
Phase 5 (--reap-registry): no stale registry records found.
```

## Phase 6 — --open-followups (opt-in)

Skip this phase unless `DO_OPEN_FOLLOWUPS` is set.

Collect advisory findings that warrant follow-up entries:
- Plans classified `tasks-complete-unmerged`: each warrants a follow-up to verify the branch was merged.
- The `complete_plan_no_merge_evidence` cross-reference flag being true surfaces these.

For each advisory finding:

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the per-item confirmation question and accept yes/no before calling sink-add.sh -->
Use `AskUserQuestion` to prompt:

```
Create follow-up entry?

  Slug:   <slug>
  Finding: tasks-complete-unmerged — all tasks [x] but no merge evidence
  Action:  Verify the branch was merged, then archive or close the plan.

Create a follow-up entry via sink-add.sh? (idempotent — no duplicate if entry already exists) [yes/no]
```

If the user answers `yes`:

```bash
bash "$_ZR_PLUGIN/scripts/sink-add.sh" \
  --sink=project \
  --priority=P2 \
  --name="Verify merge for plan: $slug" \
  --recommended-command="/z-reconcile --archive-plans" \
  --source-artifact="$plan_path/TASKS.md" \
  --cited-paths="$plan_path" \
  --prompt-body="Plan '$slug' has all tasks marked [x] but no merge/commit evidence was found. Verify the branch was merged into the default branch, then archive this plan directory." \
  2>&1
```

Map exit codes:
- 0 — print `Created follow-up for: $slug`
- 3 — print `Skipped (duplicate): $slug — entry already exists`
- 4 — print `Skipped (depth guard): $slug`
- other — print `Error creating follow-up for $slug (exit $?)`

If the user answers anything other than `yes`:
```
  Skipped: <slug>
```

If no advisory findings:
```
Phase 6 (--open-followups): no advisory findings to open as follow-ups.
```

## Phase 7 — --save (opt-in)

Skip this phase unless `DO_SAVE` is set.

Write the full report rendered in Phase 1 to `$SAVE_PATH`:

```bash
cat > "$SAVE_PATH" <<'REPORT'
<full report text from Phase 1>
REPORT
```

Print:
```
Report saved to <SAVE_PATH>
```

---

## Hard rules

- **Default run is ZERO MUTATIONS.** No file is written, no lock removed, no worktree pruned, no plan moved, no registry record deleted, no follow-up created unless the corresponding flag was explicitly passed.
- **No subagent dispatch.** This command runs using only Bash and Python.
- **No LLM calls.** Shell + Python only.
- **No hardcoded branch names.** The default branch is always resolved dynamically via `git symbolic-ref refs/remotes/origin/HEAD`; fallback to `main` only when that command fails.
- **Classification is delegated to scripts/reconcile.py.** The command body is a thin orchestrator; do not re-implement classification logic here.
- **Worktrees classified dirty / detached / merged-uncertain / unknown-remote are never offered for auto-prune.** They are surface-only in the report and skipped by Phase 2 even when `--prune-worktrees` is passed.
- **plan-claim.sh reap-stale is the only path to lock removal.** Never use `rm` on a lock without first calling reap-stale and confirming all three removal conditions.
- **Global `active-plan-registry.py reap` is never called.** Per-item deregistration only, via `deregister --run-id`.
- **tasks-complete-unmerged plans are never auto-archived.** Advisory only; offered as follow-ups via `--open-followups`.
- **Scans exclude `<base>/plans/.abandoned/`.** Plans already archived are not re-reported as fresh.
- **Robust to registry unavailability.** If the registry is absent or errors, print `(registry unavailable)` and continue.
- **Per-item confirmation is non-negotiable for every mutation.** Each `AskUserQuestion` gate must fire individually; batch confirmation is not permitted.

---

## Runtime contract conformance

| Feature        | Used | Gates                                                                    |
|----------------|------|--------------------------------------------------------------------------|
| `subagent`     | no   | —                                                                        |
| `ask_user`     | yes  | Phase 2 (per-worktree prune), Phase 3 (per-plan archive), Phase 4 (per-lock removal), Phase 5 (per-registry-record deregister), Phase 6 (per-followup creation) |
| `skill_invoke` | no   | —                                                                        |

Driver support requirements: see frontmatter `driver_features_required`.

Each `AskUserQuestion` call site is annotated with a `<!-- RUNTIME-GATE: ask_user; ... -->` comment immediately before it.
