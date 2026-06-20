# Follow-up Sink

> Last updated: 2026-06-19
> Covers source: scripts/followup_common.py, scripts/sink-add-helpers.py, scripts/followup-reconcile-notion-impl.py, scripts/sink-claim.sh, scripts/sink-lock.sh, scripts/sink-view-reducer.py, scripts/sink-status-set-impl.py, scripts/sink-add.sh, scripts/sink-status-set.sh, scripts/sink-view-rebuild.sh, scripts/sink-compact.sh, scripts/sink-migrate.sh, scripts/followup-reconcile-notion.sh, scripts/validate-followup-schemas.sh, scripts/followup-view-lookup.py, scripts/sink-claim-helpers.py, scripts/sink-compact-impl.py, scripts/sink-auto-close-check.py, scripts/sink-audit-validate.py, scripts/notion-push.py, scripts/parse-followups-block.py, commands/z-followup-list.md, commands/z-followup-status.md, commands/z-followup-confirm.md, commands/z-followup-dismiss.md, commands/z-followup-refresh.md, commands/z-followup-next.md, docs/schemas/followup-entry.schema.json, docs/schemas/audit-evidence.schema.json

## Overview

The follow-up registry captures "significant but out-of-scope" discoveries during z-harness runs — things the reviewer, implementer, or spec-retro pass flags as worth doing but outside the current plan — and drains them into a durable, priority-ordered, lifecycle-tracked work queue. Instead of letting findings evaporate from chat or pile up as comments, they become structured entries with a recommended command, staleness tracking, and a safe execution path.

Entries flow through a conservative state machine (`open → running → verify → done`) with explicit failure states and three guarded paths to completion: human-confirmed, audit-confirmed, and auto-closed-low-risk. The system coordinates with `/z-implement-*` via a two-tier locking model (per-entry OS flock + global cross-tool flock) so you never run implementation and a follow-up consumer in the same repo simultaneously. All locking primitives converge on a single shared module (`scripts/followup_common.py`) that serializes holder-JSON writes under a dedicated `.hb.lock` sentinel to guarantee atomic, torn-record-free reads.

## What is a follow-up?

A follow-up entry is a single work item with:

- **Priority** (P0–P3)
- **Name** — a short human-readable title
- **Recommended command** — the z-harness command that would complete it (e.g., `/z-do "update README badge URL"`)
- **Cited paths** — files the follow-up concerns, used for staleness detection
- **A prompt page** (`pages/<id>.md`) — the full context of what needs doing and why
- **Lifecycle state** — where the entry sits in the `open → running → verify → done` flow

## The three sinks

Entries live in exactly one of two canonical sinks. The `sink` field is an enum of `{project, global}` — never `notion`.

| Sink | Path | Scope |
|---|---|---|
| `project` | resolved via `plan-path.sh followups_dir` at call time | Repo-specific debt, continuation tasks |
| `global` | `~/.z-harness/followups/` | Harness-wide or cross-project discoveries |
| Notion | n/a (mirror only) | Optional read mirror; one-way push, never primary |

The **project sink root** is resolved by calling `plan-path.sh followups_dir` at invocation time (not frozen at import). This honours the full 5-tier base fallback chain — `Z_HARNESS_BASE_DIR`, `XDG_STATE_HOME`, and others — so the sink follows any external base reconfiguration automatically. The fallback when `plan-path.sh` is unavailable is `<proj_root>/z-harness/followups`. The global sink is always `~/.z-harness/followups` and is intentionally outside this chain.

Notion is a **passive observer** — it mirrors entries from project or global sinks based on `followup.notion_enabled` config. The filesystem is always canonical. Notion sync failure never blocks any local operation.

## Lifecycle: open → running → verify → done

```
                ┌─────► dismissed (terminal, anytime)
                │
   open ───► running ───► verify ───► done
    ▲           │           │           ▲
    │           ▼           ▼           │
    │        failed      blocked        │
    │           │           │           │
    └───────────┴───────────┘           │
       (stale-takeover, retry)          │
                                        │
              (only via human-confirm   │
               OR audit-confirm         │
               OR auto-close-low-risk)──┘
```

**Key rules:**
- `open → running` requires acquiring both the per-entry lock and the global cross-tool lock (per-entry FIRST, then global — mandatory ordering).
- `running → verify` happens automatically when the recommended command exits 0.
- `verify → done` is **never automatic** unless `auto_close_eligible` is set and the change passes the hard ceiling. Otherwise it requires an explicit `/z-followup-confirm` call.
- `dismissed` is available from any state and is terminal.

## Shared module: followup_common.py

All Python implementations import from `scripts/followup_common.py`, the single home for:

- **Global lock helpers** — `GlobalLockContext` (context manager), `acquire_global_lock`, `release_global_lock`, and the private `_hb_lock_fd` serializer. Every caller uses these identical primitives; there is no per-caller reimplementation.
- **Config helpers** — `get_config_batch(keys, proj_root)` fetches multiple config keys in a single `config.py` subprocess fork. Use this instead of per-key calls.
- **Project sink path** — `project_followups_dir(proj_root)` delegates to `plan-path.sh followups_dir` at call time. Falls back to `proj_root/z-harness/followups` when `plan-path.sh` is unavailable.
- **macOS fork-safety guard** — `os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")` is set at module import. This prevents CoreFoundation abort when Python is invoked from bash (which has already initialised CoreFoundation) and then forks a subprocess with `cwd=` or `env=`.
- **Notion push** — `_notion_push_entry` (synchronous) and `_notion_push_entry_bg` (non-blocking, detached child process). The bg variant launches `followup_common.py --push-entry ...` as a new session so the parent process always returns promptly.
- **Event logging** — `log_sink_event` (appends to `index.jsonl`), `log_metrics_event` (appends to `<base>/metrics.jsonl` — base resolved via `plan-path.sh` at call time), `_log_event_sh` (via `log-event.sh`).
- **Utility** — `iso_now()`, `git_head()` (raises `RuntimeError` on failure; never falls back to a sentinel).

## Lock model

### Global cross-tool lock

Path: `~/.z-harness/.followup-vs-implement.lock` (overridable via `Z_HARNESS_FOLLOWUP_GLOBAL_LOCK` env var).

Files on disk:
- `<lock>.flock` — the OS sentinel; `fcntl.LOCK_EX` is taken on this file.
- `<lock>` — the holder JSON file; written atomically under `<lock>.hb.lock`.
- `<lock>.hb.lock` — serializer sentinel for all JSON reads and writes.

Holder JSON format (written by `GlobalLockContext` / `acquire_global_lock`):
```json
{"holder": "<id>", "pid": <int>, "started_at": "<ISO-UTC>", "last_heartbeat": "<ISO-UTC>"}
```

The OS flock is the **authoritative mutual-exclusion check**. The holder JSON is advisory metadata. Readers must never conclude the lock is free based on an empty holder file alone — they must probe the flock sentinel.

The global lock is held **briefly** during:
- The `open → running` claim transaction (after per-entry lock is already held)
- `index.view.json` rebuild (under global lock, atomic tmpfile+rename)
- Audit evidence validation (after per-entry lock is already held)

The global lock is **never** held during command execution. Holding it longer risks deadlock with `/z-implement-*`.

### Per-entry lock

Path: `pages/<id>.lock` under the sink root.

`sink-lock.sh` uses a background daemon model: `acquire` forks a daemon that holds `fcntl.LOCK_EX` for the lifetime of the lock, writes the holder JSON under `.hb.lock`, and signals the parent. The daemon's PID in the JSON is the liveness indicator for stale-takeover checks.

**Daemon identity verification:** before sending SIGTERM during `release` or stale-takeover, `sink-lock.sh` verifies the PID belongs to a genuine lock daemon by checking for the marker string `zero_lock_under_hblock` in the process command line (via `/proc/<pid>/cmdline` on Linux, `ps -o command=` on macOS). This prevents accidentally killing an unrelated process that happened to reuse the PID.

The `read-holder` subcommand provides a programmatic interface to read the current holder JSON without acquiring or releasing the lock — useful for diagnostics and for consumers that need to verify lock identity without touching lock state.

Heartbeat interval: 30 seconds. Stale threshold: 7200 seconds (2 hours). Stale-takeover logs `followup_lock_takeover` and appends a `running → open` recovery event.

**Lock ordering invariant (MANDATORY):** any code path that needs both locks MUST acquire per-entry FIRST, then global. Inverting the order is a deadlock risk. This ordering is UNCHANGED.

### Wrappers exit 4 when global lock is not held

`sink-view-rebuild.sh` verifies at startup that the global lock is held (JSON content check OR OS flock check). It exits 4 if the lock is free. Do not call it without holding the lock.

## View reducer: incremental rebuild + checkpoint (T010)

`sink-view-reducer.py` replays `index.jsonl` into `index.view.json` via an atomic tmpfile+rename. The reducer supports **incremental rebuild**:

`index.view.json` carries a `_checkpoint` field:
```json
{
  "_checkpoint": {
    "event_count": <int>,
    "journal_byte_length": <int>,
    "tail_sha256": "<hex>",
    "tail_len": <int>
  },
  "entries": { ... }
}
```

On rebuild, the reducer:
1. Loads the existing view + checkpoint from `index.view.json`.
2. Validates the checkpoint: if the journal is now shorter than `journal_byte_length`, or if the bytes at the stored boundary do not hash to `tail_sha256`, falls back to full cold replay.
3. Incremental path: seeks to `journal_byte_length` and folds only the suffix bytes — O(new bytes) not O(journal).

The tail SHA-256 fingerprint defends against same-length rewrites (e.g., compaction that produces an equal-length journal with different prefix content), which a byte-length comparison alone would miss.

**Determinism invariant:** incremental replay must produce the same result as full replay. The `--full` flag forces a cold replay; `--repair` strips a broken tail and rebuilds with a fresh checkpoint.

## Corruption detection

When `sink-view-reducer.py` encounters a non-parseable line:
- Emits `followup_journal_truncated` event (to `log-event.sh` or fallback to `events.jsonl`).
- Exits 3. The existing `index.view.json` is left **untouched** (not overwritten from a corrupt journal).
- `--repair` strips the broken tail line(s) (tail-only truncation; interior corruption is a hard error), logs `followup_journal_repaired`, rewrites `index.jsonl` atomically, then rebuilds with a fresh checkpoint.

## Compaction: sink-compact.sh / sink-compact-impl.py (T021)

Compaction evicts terminal (done/dismissed) entries from the live journal:

1. Full-replay to identify terminal entry IDs.
2. Classify each line by entry ownership.
3. Append terminal lines to `index.archive.jsonl` (append-only; never overwritten).
4. Atomically rewrite `index.jsonl` with only live (non-terminal) lines.
5. **Delete `index.view.json`** to invalidate the T010 checkpoint — any in-place journal rewrite invalidates the stored byte-length/tail fingerprint.
6. Run `sink-view-rebuild.sh --full` to generate a fresh view and checkpoint.
7. Log `followup_log_compacted` event.

The script MUST be invoked while the global cross-tool lock is held. It does NOT acquire the lock itself (double-acquire would deadlock).

## View lookup helper: followup-view-lookup.py

`scripts/followup-view-lookup.py` is a CLI helper that abstracts view loading for consumers that need to locate entries across both sinks.

Two modes:
- `--mode=find --id=<entry-id>` — searches project and global views; prints `{"found": bool, "entry": {...}, "sink": "project"|"global"}`. Returns `{"found": false}` on miss or missing view.
- `--mode=load --sink=project|global` — dumps all entries from the specified view. Stamps `entry["sink"] = sink_label` on any entry that is missing the field. Returns `[]` on missing or invalid view (never errors).

Both modes fail gracefully — they never raise on a missing or malformed view.

## Notion sync state (T018)

The reducer materializes `entry["notion_sync_pending"]` from three event kinds:

| Event | Effect on `notion_sync_pending` |
|---|---|
| `notion_sync_pending` | Set to `True` |
| `notion_synced` | Set to `False` |
| `notion_sync_cleared` | Set to `False` |

Last-writer-wins semantics (events are replayed in journal order). `/z-followup-list` shows a Notion column; `/z-followup-status` reports a pending count. The reconciler's `_find_pending_entry_ids` uses the same event-replay logic to find entries whose latest notion-related event is `notion_sync_pending`.

## Notion token env override

`Z_HARNESS_NOTION_TOKEN` — when set, overrides the configured token path entirely. `notion-push.py` checks this environment variable first before reading `~/.z-harness/secrets.toml`. Wrappers and callers **must not** run under `set -x` when this variable is set, as doing so would leak the token value into logs.

## Migration stub: sink-migrate.sh (T020)

`sink-migrate.sh <sink-root> [--from=N] [--to=N]` is the migration driver. Contract:
1. Rebuild view (under global cross-tool lock).
2. Write entries at the new `schema_version`.
3. Append a `schema_migrated` sentinel event.
4. **Never edit existing JSONL lines.**

For v1→v1 (the current version), `sink-migrate.sh` is a documented no-op: it confirms the sink root exists and the global lock is held, then exits 0. No event is appended because there is no migration to record.

## Schema locations

JSON schemas have moved:
- **Entry schema:** `docs/schemas/followup-entry.schema.json` (previously `schemas/followup-entry.json`)
- **Audit evidence schema:** `docs/schemas/audit-evidence.schema.json` (previously `schemas/audit-evidence.json`)
- **Fixtures:** `docs/schemas/fixtures/`
- **Validator:** `scripts/validate-followup-schemas.sh`

## When to use each completion path

### Human-confirmed (`/z-followup-confirm <id> --via=human`)

Use this when you reviewed the result yourself and are confident it is correct. The command presents an `AskUserQuestion` confirmation and on approval transitions the entry to `done` with `completion_mode=human_confirmed`. This is the simplest and most common path.

### Audit-confirmed (`/z-followup-confirm <id> --via=audit --evidence=<path>`)

Use this when you want a machine-verifiable audit trail. The command validates an `audit_evidence.json` blob against an 11-point checklist:

1. File exists
2. `schema_version == 1`
3. `entry_id` matches
4. `review_verdict_path` and `diff_artifact_path` both exist (non-empty string paths)
5. `review_verdict == "PASS"` (literal)
6. `test_exit_code == 0`
7. `git merge-base --is-ancestor <capture_head> <verify_head>` passes (no force-push escape)
8. `verified_by_run` is a valid run id in a plan's archive (both legacy `z-harness/<plan>/archive/` and canonical `z-harness/plans/<plan>/archive/` layouts accepted; path traversal in run id is rejected)
9. The diff touches at least one of the entry's `cited_paths` (prevents auditing something unrelated)
10. The verdict file mentions the `entry_id` or `recommended_command` (verdict must say what it audited)
11. Evidence lives under `z-harness/<plan>/archive/<RUN>/audit_evidence/<entry-id>/audit_evidence.json` (run-archive path only; both legacy and canonical layouts accepted)

On all-pass, transitions to `done` with `completion_mode=audit_confirmed`. On any failure, stays at `verify` and logs `followup_audit_evidence_rejected` with the failing check number.

### Auto-closed-low-risk

This path is **opt-in**: the entry must have `auto_close_eligible=true` (set by the producer) and the consumer ceiling must pass:

- **Condition A:** `diff_stat == 0` AND no touched paths (true no-op — the command made no changes at all). A diff with file headers but zero content lines (binary, rename, mode-only) is not a noop.
- **Condition B:** All touched paths match `followup.auto_close_low_risk_path_allowlist` AND none match `followup.auto_close_low_risk_path_denylist` (denylist wins)
- Plus: tests exit 0
- Plus: master kill-switch `followup.auto_close_low_risk_enabled` must be true (fails closed when config is present but unreadable)

Default allowlist: `docs/**/*.md`, `**/CHANGELOG`, `**/CHANGELOG.md`.
Default denylist: `commands/**/*.md`, `agents/**/*.md`, `.claude/**/*.md`, `/*.md` (root-level).

If neither condition passes, the entry stays at `verify` for HITL review.

## How to invoke /z-followup-next

`/z-followup-next` is the interactive consumer that works through the queue one entry at a time. It runs in 10 phases:

1. **Phase 0 — Nest guard:** refuses if `Z_HARNESS_FOLLOWUP_CALLER_DEPTH >= 1`.
2. **Phase 0.1 — Heuristic lock probe (5 s timeout):** fast-fail if `/z-implement-*` is actively holding the lock. This is a heuristic for user friendliness and is **NOT a mutual-exclusion guarantee** — acquire+release in sequence proves nothing about concurrent access.
3. **Phase 0.2 — Running-entry check:** refuses if any project sink entry has `status=running`, even if the global lock is currently free.
4. **Phase 1 — Enumerate:** scans both sinks, merges into priority-sorted view (P0 first, then by creation time); excludes `depth=1` entries.
5. **Phase 2 — Select:** presents top entries (configurable via `Z_HARNESS_FOLLOWUP_TOP_N`, default 10); `--non-interactive` claims entry [1] automatically.
6. **Phase 3 — Worktree check:** verifies clean working tree (use `--force-dirty` to override; pre-run diff is captured).
7. **Phase 4 — Staleness check:** compares `file_blob_hashes`/`dir_blob_hashes` and commit distance; prompts if stale.
8. **Phase 5 — Claim:** acquires per-entry lock first, then global (`sink-claim.sh`). Spawns heartbeat subprocess after successful claim with trap for cleanup on abnormal exit.
9. **Phase 6 — Execute:** sets `Z_HARNESS_FOLLOWUP_CALLER_DEPTH=1`, invokes `recommended_command` via Skill tool, then unsets the variable immediately after the Skill call returns.
10. **Phase 7 — Status writeback:** writes `verify` on exit 0, `failed` on non-zero; uses claim ticket for identity verification.
11. **Phase 8 — Auto-close attempt:** attempts auto-close if eligible.
12. **Phase 9 — Cleanup:** kills heartbeat subprocess BEFORE releasing per-entry lock (kill-before-release ordering is required), then disables the EXIT trap.
13. **Phase 10 — Push-notify:** triggers Notion sync push if configured.

Typical session:

```
/z-followup-list                          # see what's queued
/z-followup-next                          # work one entry
/z-followup-confirm <id> --via=human      # approve the result
```

## Common gotchas

- **`sink=notion` is not valid.** Notion is a mirror, not a sink. Entries always have `sink ∈ {project, global}`. The optional `notion_remote_id` field tracks the Notion page ID.
- **depth=1 entries are inert.** If `/z-followup-next` fires a command that itself creates a new follow-up, that nested entry gets `depth=1` and the consumer will not claim it automatically. You must review, confirm, or dismiss it manually.
- **auto_close_eligible is necessary but not sufficient.** The producer sets the flag; the consumer ceiling (diff check + allowlist + kill-switch) is what actually gates the transition.
- **The denylist wins.** A path matching both the allowlist and the denylist is denied for auto-close. The auto-close kill-switch (`followup.auto_close_low_risk_enabled`) fails closed when config is present but unreadable.
- **Condition A for auto-close requires both `diff_stat == 0` AND no touched paths.** A binary rename or mode-only change can produce `diff_stat == 0` but still has touched paths and must pass the allowlist check.
- **Staleness hard-dismiss is disabled by default.** Set `followup.staleness_hard_dismiss_days` to a positive integer to enable TTL-based auto-dismiss.
- **The global lock is never held during command execution.** Holding it longer would create a deadlock risk with `/z-implement-*`. The lock is only held briefly for the claim transaction, view rebuild, and evidence validation.
- **Lock order is mandatory: per-entry first, then global.** Any code that inverts this order risks deadlock. This ordering is UNCHANGED.
- **Notion sync failure is silent.** If Notion push fails after 3 retries, `notion_sync_pending` is stamped in the event log and the local operation continues. Run `/z-followup-reconcile-notion` manually to retry pending pushes.
- **Compaction must delete `index.view.json` before rebuilding.** After any in-place journal rewrite, the T010 checkpoint is invalid. `sink-compact-impl.py` does this. Any custom compaction that skips this step will produce a corrupt incremental rebuild.
- **`Z_HARNESS_NOTION_TOKEN` must not appear under `set -x`.** Bash `set -x` echo mode would log the token value to stderr.
- **Schema files have moved.** Old paths `schemas/followup-entry.json` and `schemas/audit-evidence.json` no longer exist. Current paths: `docs/schemas/followup-entry.schema.json` and `docs/schemas/audit-evidence.schema.json`.
- **Reviewer follow-ups are opportunistic.** The `**FOLLOWUPS:**` block in a reviewer return is parsed best-effort; parse failures log `followup_block_parse_failed` and proceed without follow-ups. A reviewer return is never blocked by follow-up wiring.
- **`/z-implement-*` checks for running follow-ups.** Phase 0 scans the project sink for any entry with `status=running`. If found, it refuses to start. This is separate from the lock check and fires even if the global lock is currently free.
- **Dedup hash uses only `name` and `recommended_command`.** `source_artifact` is intentionally excluded so the same logical follow-up is deduped regardless of which artifact (per-task diff vs. cumulative findings) surfaced it.
- **`sink-view-rebuild.sh` exits 4 when the lock is not held.** It verifies lock-held state at startup (JSON content check OR OS flock check). Calling it without the lock causes an exit 4 error.
- **Project sink root is resolved at call time.** `project_followups_dir()` calls `plan-path.sh followups_dir` on every invocation so the path follows any live base reconfiguration. It is not frozen at process start or module import.
- **`OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` is set at module import.** `followup_common.py` sets this env var via `os.environ.setdefault` before any subprocess call. Without it, Python processes forked from a bash parent that initialised CoreFoundation can abort on macOS.
- **Daemon identity verification is mandatory before SIGTERM.** `sink-lock.sh` checks for the `zero_lock_under_hblock` marker in the process command line before killing a daemon PID. Skipping this check risks killing an unrelated process that reused the PID.
- **Phase 9 kill-before-release ordering.** `/z-followup-next` kills the heartbeat subprocess BEFORE releasing the per-entry lock. Releasing the lock first could allow another consumer to acquire it while the heartbeat daemon is still alive and writing to `.hb.lock`.
- **`followup-view-lookup.py` returns `[]` on missing or malformed view files.** It never errors on a bad view; callers must not interpret an empty return as "no entries exist" without also checking that the view file exists.

## Persistence layout

```
z-harness/followups/          # project sink (path from plan-path.sh followups_dir)
├── index.jsonl               # append-only event log (never edit directly)
├── index.view.json           # materialized view (rebuilt under lock; carries _checkpoint)
├── index.archive.jsonl       # archived terminal-entry events (append-only; compaction output)
├── pages/
│   ├── <id>.md               # prompt page (immutable)
│   ├── <id>.lock             # per-entry flock holder JSON
│   ├── <id>.lock.flock       # per-entry OS flock sentinel
│   └── <id>.lock.hb.lock     # serializer for JSON reads/writes
└── audit_evidence/<entry-id>/<RUN>/
    ├── audit_evidence.json
    ├── verdict.md
    ├── test_exit
    └── cumulative.diff

~/.z-harness/followups/                          # global sink (same layout)
~/.z-harness/.followup-vs-implement.lock         # global lock holder JSON
~/.z-harness/.followup-vs-implement.lock.flock   # global lock OS sentinel
~/.z-harness/.followup-vs-implement.lock.hb.lock # global lock JSON serializer

docs/schemas/followup-entry.schema.json          # JSON Schema (Draft 2020-12)
docs/schemas/audit-evidence.schema.json          # JSON Schema (Draft 2020-12)
docs/schemas/fixtures/                           # test fixtures
```

## Schema versioning and migration

All follow-up entries carry `schema_version` (currently `1`). Because the log is append-only, schema evolution requires the migration contract so the store remains consistent.

Schema version bumps are reserved for **breaking changes**: new required fields, removed or renamed fields, or changed semantics the reducer cannot handle via forward-compat defaults. Additive changes (new optional fields with safe defaults) do not require a bump.

When a bump occurs, `sink-migrate.sh <sink-root> [--from=N] [--to=N]` executes the migration:
1. Rebuild the view under the global cross-tool lock.
2. Future appends automatically stamp the new `schema_version`.
3. Backfill old entries via append-only corrective events.
4. Append a `schema_migrated` sentinel: `{"ts":"...", "kind":"schema_migrated", "from_version":N, "to_version":M, "migrated_by":"scripts/sink-migrate.sh"}`.

For v1→v1 (current): no-op. The script verifies lock-held state and exits 0.

## Commands quick reference

| Command | Purpose |
|---|---|
| `/z-followup-list` | Read-only view of all entries; supports `--status=`, `--sink=`, `--priority=`, `--json`; shows Notion sync column |
| `/z-followup-status` | Diagnostic counts per status, lock state (flock-probed), oldest open entry, Notion sync pending count, last sync error |
| `/z-followup-next` | Interactive consumer; select and execute one entry (10 phases) |
| `/z-followup-confirm <id> --via=human` | Approve a `verify`-state entry as done |
| `/z-followup-confirm <id> --via=audit --evidence=<path>` | Audit-validated completion |
| `/z-followup-dismiss <id> --reason='...'` | Dismiss an entry from any state |
| `/z-followup-refresh <id>` | Re-stamp staleness data and transition `blocked → open` |

## Depth cap and the `Z_HARNESS_FOLLOWUP_CALLER_DEPTH` env var

Follow-up commands use the `Z_HARNESS_FOLLOWUP_CALLER_DEPTH` environment variable to prevent recursive consumer nesting.

- `/z-followup-next` checks this env var at startup. If it is `>= 1`, the command refuses to run.
- Before invoking the `recommended_command`, `/z-followup-next` sets `Z_HARNESS_FOLLOWUP_CALLER_DEPTH=1`.
- `sink-add-helpers.py` reads this variable and stamps `depth=<value>` on each new entry. Entries at `depth=1` are inert — the consumer filters them out (`depth < 1` clamp in Phase 1).
- After the Skill call returns, `/z-followup-next` unsets the variable so the depth cap does not leak to subsequent commands in the same shell session.

`depth=0` means "created by a top-level producer; claimable." `depth=1` means "created inside a running consumer; requires human review."

## `done → dismissed` field policy

When an entry transitions from `done` to `dismissed`, the reducer keeps `closed_at` and `completion_mode` intact and stamps `dismissed_after_done: True` on the entry. This preserves the audit trail. When computing metrics, filter out entries where `dismissed_after_done == true` if you only want entries that reached a clean `done` state.

## Key event kinds

```
entry_created               followup_created
entry_refreshed             followup_dedup_skipped
status_changed              followup_depth_exceeded
evidence_attached           followup_status_changed
dismissed                   followup_lock_takeover
closed                      followup_lock_timeout
notion_sync_pending         followup_unsafe_command
notion_synced               followup_audit_evidence_rejected
notion_sync_cleared         followup_staleness_drift
schema_migrated             followup_notion_sync_failure
followup_journal_truncated  followup_notion_remote_id_mismatch
followup_journal_repaired   followup_block_parse_failed
followup_log_compacted      followup_cited_paths_too_diffuse
```
