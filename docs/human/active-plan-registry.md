# active-plan-registry — Cross-session awareness registry

> Last updated: 2026-06-19
> Covers source: scripts/active-plan-registry.py, scripts/plan-path.sh, scripts/migrate-plan-layout.sh, agents/scope-extractor.md, commands/z-implement-all.md, commands/z-implement-next.md, commands/z-plan.md

## Overview

The active-plan-coordination system adds two tightly coupled capabilities to z-harness:

1. **Durability (external base)** — the artifact base (`z-harness/` plans, metrics, followups) is relocated outside the gitignored working tree by default, so a parallel session's `git clean -fdx` cannot destroy every session's plans simultaneously (the 2026-06-01 incident root cause).

2. **Awareness registry** — a lockless, per-run JSON registry living under the shared external base (`<base>/active-plans/`) that lets concurrent sessions discover each other's active plans and likely file scope. Overlaps are surfaced advisorily at implement Phase 0 — no blocking mutex is taken.

See `docs/human/config.md` (section "Base-dir + registry env knobs") for the full env-var table and fallback chain, and `docs/human/PLAN-LAYOUT.md` for the overall plan-directory layout.

---

## The durability problem it solves

z-harness stores all run artifacts (plans, archives, metrics, locks, followups) under the repo's `z-harness/` tree, which is gitignored. Those files are ephemeral working-tree state. When any concurrent Claude Code session running the same checkout does a `git clean -fdx` (a routine branch-hygiene operation), it deletes the entire tree — every plan from every session at once, unrecoverably.

The 2026-06-01 incident lost ~24 plan directories mid-run in exactly this way. The external-base design (B + session stamping, documented in `docs/handoff-parallel-session-safety.md`) addresses this by resolving the artifact base through a five-tier fallback chain that places artifacts outside the git worktree by default. `git clean` cannot touch files outside the checkout.

---

## How it works

### Base fallback chain

`scripts/plan-path.sh`'s `z_harness_base()` function resolves the artifact base via the following priority chain (highest priority first):

| Tier | Path | Notes |
|------|------|-------|
| 1 | `$Z_HARNESS_BASE_DIR` | Explicit absolute override — TRUE ESCAPE HATCH; bypasses anchor |
| 2 | `$XDG_STATE_HOME/z-harness/<repo-id>` | If `$XDG_STATE_HOME` set + writable |
| 3 | `$HOME/.local/state/z-harness/<repo-id>` | If `$HOME` set + writable |
| 4 | `<git-common-dir>/z-harness` | Inside `.git/`; survives `git clean`; shared across worktrees |
| 5 | `$(pwd)/z-harness` | Last resort (clean-vulnerable; pre-flip legacy behavior) |

When `Z_HARNESS_EXTERNAL_DEFAULT` is unset or `1` (the default after Phase-D flip), tiers 2–5 apply. When `Z_HARNESS_EXTERNAL_DEFAULT=0`, only tiers 1 and 5 are active (opt-out to legacy behavior).

### Base anchor

All processes for a given repo must agree on the same base. The first `z_harness_base()` call writes a small anchor file at `<git-common-dir>/.z-harness-base` (JSON: `{tier, path, repo_id}`, atomic tmpfile+rename). Every subsequent call reads the anchor: if the freshly-resolved path differs, it emits `base_mismatch_detected` and hard-fails before any artifact write. The anchor lives in `git-common-dir` (shared by all worktrees of one repo, and survives `git clean`).

**Tier 1 escape hatch.** When `Z_HARNESS_BASE_DIR` is explicitly set, `z_harness_base()` returns it immediately with no anchor interaction whatsoever — no read, no validate, no write. This is intentional: CI/benchmark environments that relocate artifacts to hermetic temp dirs must not hard-fail against a dev machine's pre-existing anchor.

### Repo-id

`z_harness_repo_id()` produces a stable, short safe-basename for the per-repo directory:
- Format: `<repo-basename>-<8hex>` (e.g. `z-harness-1a2b3c4d`)
- The 8-hex suffix is derived from `sha256(realpath(git-common-dir))[0:8]`
- Keying on `git-common-dir` means all worktrees of one repo produce the same id
- Falls back to `sha256(realpath(pwd))` when not in a git repo

### Registry layout

The registry lives under the external base, not under the git checkout:

```
<base>/                          <- z_harness_base()
├── active-plans/                <- active_plans_dir()
│   ├── <run-id>.json            <- one file per live run
│   └── claims/                  <- claims_dir() — per-slug hard claim locks (plan-claim)
├── plans/
│   └── <slug>/
│       ├── SPEC.md, PLAN.md, TASKS.md, ...
│       └── archive/<run-id>/
├── followups/                   <- followups_dir()
└── metrics.jsonl
```

Each `<run-id>.json` record (schema_version 2) contains:

```json
{
  "schema_version": 2,
  "run_id": "...",
  "session_id": "...",
  "slug": "...",
  "command": "/z-implement-all",
  "command_version": "<z_harness_version>",
  "phase": "implement",
  "status": "running",
  "pid": 12345,
  "host": "zeke-mbp",
  "repo_id": "z-harness-1a2b3c4d",
  "repo_root": "/abs/path",
  "git_common_dir": "/abs/path/.git",
  "worktree_path": "/abs/path",
  "branch": "main",
  "started_at": "ISO-UTC",
  "last_heartbeat": "ISO-UTC",
  "current_task": "T007",
  "scope": [
    {"path": "scripts/plan-path.sh", "confidence": "explicit", "reason": "TASKS T003 File changes"}
  ],
  "held_paths": [{"path": "scripts/plan-path.sh", "since": "ISO-UTC"}],
  "waiting_on": []
}
```

**Schema v2 back-compat:** a v2 reader treats any record with `schema_version < 2` OR missing `held_paths` as **lease-incapable** — such a peer contributes to soft scope overlap only, never to held-path waiting. Missing `held_paths` is NEVER interpreted as "holds nothing."

---

## Registry subcommands

`scripts/active-plan-registry.py` provides the following subcommands (all operate on `active_plans_dir()`):

| Subcommand | Purpose |
|------------|---------|
| `session-id` | Prints a stable session id for the current shell session. Returns `$Z_HARNESS_SESSION_ID` if set; otherwise derives `<ppid>-<start_epoch>` (Linux: from `/proc`; macOS: pure-Python fallback). Callers should `export Z_HARNESS_SESSION_ID="$(session-id)"` once at run start. |
| `register --run-id ID --slug S --command C --phase P [--session SID]` | Creates/overwrites `<active>/ID.json` atomically. Idempotent. Emits `plan_registered`. |
| `heartbeat --run-id ID [--phase P] [--current-task T] [--status running\|paused]` | Updates `last_heartbeat`, `phase`, `current_task`, and (when provided) `status` in the own record. There is **no `--waiting-on` CLI flag** — the paused beat's combined atomic write of `status=paused + waiting_on` is performed internally by `_set_waiting_on()` inside `wait-for`'s poll loop, ensuring no window where status=paused but waiting_on is stale. If the record is absent (reaped or never registered), emits `registry_error(reason:missing_record)` and returns 0 — does NOT recreate a zombie record. |
| `update-scope --run-id ID --scope-json FILE` | Merges a scope array `[{path, confidence, reason}]` into the record. |
| `claim --run-id ID --paths p1,p2[,...]` | Stage and claim per-file leases. Performs a check-after-claim: re-reads all peer records, applies lexicographic run_id tiebreak (lower run_id = senior wins). Persists only the won set into `held_paths`. Stdout: JSON `{"claimed":[...],"conceded":[{"path","holder_run_id"}]}`. Exit 0 always (advisory). `Z_HARNESS_REGISTRY_ENABLED=0` → silent no-op. |
| `release --run-id ID (--paths p1,p2 \| --all)` | Remove named paths (or all) from own `held_paths`. Best-effort, exit 0. Emits `lease_released`. `Z_HARNESS_REGISTRY_ENABLED=0` → silent no-op. |
| `wait-for --run-id ID --on RUNID[,...] [--paths p1,p2]` | Park the current run behind one or more senior peers (run_id < mine) until their records clear or budget expires. See "Lease mechanics and wait-for" section below for full semantics. |
| `overlaps --run-id ID [--strict] [--scope-json FILE]` | Computes path intersection against every other live record's scope AND `held_paths`. JSON payload includes a `peers` array (per-peer scope overlaps) and a top-level `held_conflict` flat array (held×held intersections across all live lease-capable peers; each entry: `{"path","peer_run_id","holder_seniority"}`). `held_conflict` is absent when there are no held-path conflicts — it is NOT nested inside each peer entry. Exit codes: `0` none, `10` advisory, `20` blocking (strict mode + explicit×explicit exact match). |
| `list [--json]` | Returns all records (live and stale). |
| `reap` | Deletes records where (a) host=localhost AND pid is dead, OR (b) past 2× stale threshold AND NOT a live-local-pid (see "Reaper carve-out" below). Marks remote/unknown-host records as `status:"stale"` at 1× threshold (no delete). |
| `deregister --run-id ID [--status complete\|aborted]` | Removes `<active>/ID.json`. Emits `plan_deregistered`. |

### Scope-extractor integration

At Phase 0 of `/z-implement-all`, `/z-implement-next`, and Phase 8 of `/z-plan`, a Haiku subagent (`agents/scope-extractor.md`) reads SPEC.md + PLAN.md + TASKS.md (and optionally a specific task block) and emits a JSON scope array `[{path, confidence, reason}]`. The orchestrator writes the result via `update-scope`.

Confidence levels: `explicit` (path literally named in a Files: line) > `inferred` (strongly implied) > `broad` (directory/glob) > `unknown` (work named but files not).

Overlap comparison uses `path` (normalized repo-relative) only. Confidence ordering determines advisory vs. blocking tier.

### Overlap response protocol

Two dimensions of overlap exist: **scope overlap** (path appears in both runs' `scope` arrays — planned but not necessarily editing NOW) and **held conflict** (`held_paths` of both runs intersect — actively editing NOW). The held conflict is what drives `wait-for`.

| Overlap type | Default behavior (`Z_HARNESS_AUTO_WAIT=1`) | Strict (`Z_HARNESS_STRICT_OVERLAP=1`) |
|-------------|------------------------------------------|---------------------------------------|
| Held conflict with senior peer | Auto-park via `wait-for --on <holder_run_id>` (budget: `Z_HARNESS_AUTO_WAIT_BUDGET_SECS=300`). On exit 0 (cleared): re-`claim` and proceed. On exit 10 (timeout): AskUser proceed/abort; under `Z_HARNESS_NO_ASK` → abort task + loud log. | Same — held conflict is never a silent proceed regardless of strict mode. |
| Held conflict with junior peer | Proceed. A schema-v2 junior cannot structurally hold a path over a senior — its `claim` would have conceded that path. If `overlaps` reports a junior held-conflict (e.g., schema-v1 peer or concurrent race window), no wait is needed: the tiebreak guarantees the junior holds nothing the senior doesn't own. | Same. |
| Scope `explicit` × `explicit` path match (no held conflict) | AskUserQuestion: proceed / **wait** (calls `wait-for`) / abort | Hard halt (exit 20 treated as blocking) |
| Scope `inferred` or `broad` overlap | Warning + offer-wait | Same (advisory) |
| Scope `unknown` confidence | Log + proceed | Same |
| Same session | Ignored | Ignored |
| Stale peer | Shown as stale, non-blocking | Shown as stale, non-blocking |

**"Wait" in the overlap menu is now a real mechanism.** When the user selects "wait" in the scope-overlap AskUserQuestion, the orchestrator calls `wait-for --on <peer_run_id>` and parks the current run in a real poll loop until the peer deregisters or budget expires. It no longer silently proceeds.

**`Z_HARNESS_AUTO_WAIT=0`** disables auto-park and restores the interactive proceed/wait/abort menu for held conflicts (mirroring the old advisory-only behavior). Set this if you prefer manual control over automatic parking.

---

## Lease mechanics and wait-for

### What a lease is

A **lease** is a per-file advisory claim recorded in the run's own JSON record under `held_paths`. There is no global lock table — each run owns its own record and only writes its own `held_paths`. The lockless invariant is preserved: lease contention is advisory and self-gating, never a hard gate.

### run_id total order and seniority

run_ids are compared **lexicographically** (string order). A peer whose `run_id < mine` is the **senior** — it wins any contended path. `started_at` is display-only and has no ordering role. This means:

- The senior always holds the path when both claim simultaneously.
- A junior that loses a claim concedes to the eldest (lowest) senior when multiple seniors hold one path.
- There is **no preemption** — the senior is NEVER auto-killed by the registry.

### claim / check-after-claim tiebreak

When a run calls `claim --run-id $MY_RUN --paths p1,p2`:

1. The paths are staged in memory with `since=now`.
2. All peer records are re-read (check-after-claim, F2).
3. For each staged path: if a live, lease-capable peer has `run_id < mine` AND holds that path → **concede** (report under `conceded` with the eldest senior's `run_id` as `holder_run_id`).
4. **Persist only the won set** into `held_paths`. The loser's record NEVER contains the conceded path. This ensures that a post-`wait-for` re-claim is a genuine acquisition, not a dedup no-op.

Stdout: `{"claimed": [...], "conceded": [{"path": "...", "holder_run_id": "..."}]}`.

### wait-for poll loop

`wait-for --run-id $MY_RUN --on $PEER_RUN [--paths p1,p2]`:

1. Drops any non-senior (run_id >= mine) or absent targets immediately; if none remain, exits 0 (`nothing_to_wait_on`).
2. Every `Z_HARNESS_WAIT_POLL_SECS` (default 30 s) beats:
   a. Single atomic write: `status=paused` + `waiting_on=[remaining targets]` while preserving `held_paths` — one write, no window where status=paused but waiting_on is stale (MINOR-1).
   b. Runs `_reap_inline()` (inline reap with pre-resolved `active_dir` to avoid redundant plan-path.sh subprocesses on each poll iteration).
   c. Re-reads targets: a target is **cleared** when its record is gone, or `status` is `complete`/`aborted`/`stale`, or the record is age-stale.
   d. TOCTOU re-scan: adds any NEW senior holders of `--paths` that appeared since the last poll. Junior claimers are ignored — the deterministic tiebreak already gave them nothing.
3. All targets cleared and no new senior holder → clear `waiting_on=[]`, set `status=running`, exit 0 (`cleared`).
4. On any exit: `waiting_on` is cleared (via `finally`). No paused zombie is ever left behind.

### Dual budget

Two distinct time ceilings exist — they are NOT the same knob:

| Mode | Knob | Default | When active |
|------|------|---------|-------------|
| **Auto-wait** (orchestrator-initiated, unattended) | `Z_HARNESS_AUTO_WAIT_BUDGET_SECS` | 300 s (5 min) | `claim` concedes; `Z_HARNESS_AUTO_WAIT=1` |
| **Explicit wait** (user selected "wait" in the menu) | `Z_HARNESS_WAIT_TIMEOUT_SECS` | 1800 s (30 min) | `AskUserQuestion → wait` branch |

On budget expiry (`exit 10`): `waiting_on=[]` is cleared, `status=running` is restored, and a LOUD `wait_timeout` event is emitted. The caller then surfaces the menu or (under `Z_HARNESS_NO_ASK`) aborts the task. **Never silently proceed on exit 10** — that recreates the collision.

### Unattended behavior on timeout

Under `Z_HARNESS_NO_ASK=halt`, a `wait-for exit 10` causes the orchestrator to **abort the current task** and emit a loud log. It does NOT silently proceed and does NOT automatically re-enter `wait-for` on the same blocker within the same task (that would mask a real hang). Re-waiting is only legitimate after the task is abandoned and re-queued by the user.

### Release granularity: per task, not per merge

`release` is called on **each task's clean success** — not when the branch merges. A waiter unblocks within one poll interval of the senior finishing its edits to the contended file. "Wait for plan X" means "wait for X's current task to stop editing the file," unless `Z_HARNESS_WAIT_REQUIRE_MERGE=1` (reserved/deferred — see below) opts into the branch-ancestor cleared signal.

### merge-verify (`Z_HARNESS_WAIT_REQUIRE_MERGE`) — reserved/deferred

`Z_HARNESS_WAIT_REQUIRE_MERGE=1` would make a target "cleared" only when its branch is an ancestor of HEAD (`git merge-base --is-ancestor <peer_branch> HEAD`). This knob is present in the code with a `_DEFAULT_WAIT_REQUIRE_MERGE = 0` constant for discoverability but **its branch-ancestor cleared logic is not yet wired** (deferred to a later plan). Leave it unset. The default deregister-only cleared signal is the operative behavior.

### Reaper carve-out (live-local-pid)

The `reap` subcommand (and its inline counterpart `_reap_inline()`) has a specific carve-out for slow-but-alive local processes:

- **Case (a): dead local pid.** `host == this host` AND `pid` is an integer AND `os.kill(pid, 0)` raises `ESRCH` → delete the record immediately, regardless of heartbeat age.
- **Live-local-pid carve-out.** `host == this host` AND `pid` is an integer AND `os.kill(pid, 0)` succeeds (pid is confirmed alive) AND past the 2× margin → mark `status:"stale"` but **do NOT delete**. A 2-hour local test run must not have its leases reaped out from under it. Deletion is deferred until the pid dies and case (a) fires on a subsequent reap cycle. **The carve-out requires a confirmed-alive pid.** A local record whose `pid` field is missing or non-integer does NOT qualify; it falls through to case (b) and is deleted.
- **Case (b): past 2× stale margin AND not a live local pid.** Covers remote/unknown-host records, local records with no `pid` field, and local records whose pid is dead. → delete.
- **Remote/unknown host at 1× threshold.** Mark `status:"stale"` (no delete). Remote hosts can never be confirmed dead.

**Note:** `_reap_inline()` is the inline version called inside `wait-for`'s poll loop. It shares identical deletion/carve-out policy with `cmd_reap` but accepts a pre-resolved `active_dir` to avoid repeated `plan-path.sh` subprocess calls in tight poll loops.

### Wedged-but-alive senior: no auto-preemption (known limitation)

**If a senior run is stuck** (e.g., waiting on user input, hung in a network call, or paused by the OS) but its pid is still alive on the same host, the reaper carve-out keeps its leases alive indefinitely. Juniors will burn their full budget then abort.

There is **no automatic preemption**. By design — preemption would require a distributed lock or compare-and-delete, which the lockless registry does not have.

**Diagnosis:** run `/z-where`. The output shows each plan's `held_paths`, `waiting_on`, and heartbeat age. Wait-edges are rendered as `A ──waits──▶ B`. A senior with stale heartbeat and live held_paths is the culprit.

**Resolution (manual):**

```bash
python3 scripts/active-plan-registry.py release --run-id <peer-run-id> --all
```

This empties the senior's `held_paths`. All juniors waiting on that senior will clear on the next poll and re-claim the freed paths. Use this only when you have confirmed the peer run is genuinely wedged and will not resume.

---

## Scope-extractor (Haiku subagent)

`agents/scope-extractor.md` (frontmatter `model: haiku`). Input: `repo_root`, `base` (plan artifact dir), optional `task_id`. Reads SPEC.md + PLAN.md + TASKS.md (and the task block if `task_id` given), emits JSON `[{path, confidence, reason}]` to stdout.

A mechanical fallback is documented for offline use (parse `**Files:**` lines directly from TASKS.md), but the Haiku subagent is the primary path. The fallback produces only `explicit` confidence entries.

---

## Command integration (Phase 0)

### `/z-implement-all` and `/z-implement-next`

**Phase 0.0** (runs before the existing follow-up-running check):

1. `register` the current run
2. Invoke `scope-extractor` (Haiku) to populate scope
3. Call `active-plan-registry.py overlaps --run-id $RUN`
4. Respond per overlap exit code (see table above)
5. `deregister` in finalize phase (complete) and on halt (aborted)

**Per-task lease lifecycle** (wraps each task dispatch):

```
for each task T:
  1. heartbeat --current-task T --status running
  2. Invoke scope-extractor(task=T); take only explicit-confidence paths as CLAIM
  3. claim --run-id $RUN --paths $CLAIM  ->  {claimed, conceded}
  4. For each conceded {path, holder_run_id} (eldest senior holds it):
       if Z_HARNESS_AUTO_WAIT=1:
         wait-for --on $holder_run_id --paths $path
           exit 0 -> re-claim the freed path (genuine acquisition), continue
           exit 10 -> (interactive) AskUser proceed/abort
                     (Z_HARNESS_NO_ASK) abort task + loud log -- never silently proceed
       else: AskUser proceed / wait / abort  (wait -> same wait-for call)
  5. Dispatch implementer for T (constrained to claimed paths)
  6. Write-set validation: git diff --name-only; for any undeclared path also held
     by a live peer -> emit coordination_warning (review-blocking, advisory)
  7. On clean task success: release --run-id $RUN --paths $CLAIM
     On review-fail retry: KEEP lease, expand with newly-touched paths
     On halt mid-task: rely on deregister/reap (do not release a partial edit)
```

### `/z-plan`, `/z-plan-light`, `/z-debug`, `/z-do`, `/z-audit`, `/z-plan-split`

All run-creating commands get the same register/heartbeat/deregister 3-line block. In `/z-plan`, `scope-extractor` runs after TASKS.md is written (Phase 8) to seed scope for overlap detection.

### Hermes orchestration

`scripts/hermes-execute.py` also calls `active-plan-registry.py session-id` (line 822) to retrieve the session id before each workstream execution. Cross-plan Hermes paths acquire sorted-slug plan-claim locks before touching the registry — the claim lock (`plan-claim`) is the hard mutex; this registry remains advisory.

---

## Migration: `migrate-plan-layout.sh` updates

`scripts/migrate-plan-layout.sh` gained two significant extensions:

1. **Live-run barrier (invariant 8):** before any migration, the script calls `active-plan-registry.py list` and refuses if any record shows `status:running`. This prevents TOCTOU races where an active `/z-implement-next` appends to a source TASKS.md after copy-verify but before `rm`.

2. **Full artifact manifest (`--dry-run --all`):** prints the complete mapping of source → target for all artifact types:
   - `z-harness/plans/<slug>/` and legacy-flat `z-harness/<slug>/` → `<base>/plans/<slug>`
   - `z-harness/archive/<run>/` → `<base>/archive/<run>`
   - `z-harness/metrics.jsonl` → `<base>/metrics.jsonl` (append/merge if target exists)
   - `z-harness/followups/` → `<base>/followups/` (only with `--with-followups`; default skip)

**metrics.jsonl merging** is crash-safe and idempotent: lines already present in the target are detected and skipped (dedup against existing-target-lines set). This prevents duplicates on re-run after a partial failure.

See `docs/human/PLAN-LAYOUT.md` for the full migration guide.

---

## Cross-cutting invariants

1. **Lockless registry is safe ONLY because overlap is advisory.** No code may make overlap a hard gate without first replacing lockless delete with compare-and-delete or a registry lock.
2. **Never invert the existing lock order.** The registry takes NO global lock; it cannot participate in the per-entry→global ordering in `followup_common.py`.
3. **Single-writer-per-record.** Each `<run-id>.json` is written ONLY by the process that owns that run. Subagents RETURN data; the orchestrator performs the write. `claim`, `release`, and `wait-for` only touch the caller's own record. `reap` is the one documented exception (marks peers stale; single-writer invariant otherwise holds).
4. **Base anchor — all processes of a repo MUST agree on the base.** Mismatch → `base_mismatch_detected` hard-fail before any artifact write.
5. **No mutation of the base while a run is live.** Migration refuses if `active-plan-registry.py list` shows any `status:running` record.
6. **Wait/lease gates the waiter's OWN run only; it takes no lock; it never writes a peer's record; every wait has a finite budget + loud timeout; the holder is never preempted.** The lockless registry stays safe because lease contention remains advisory and self-gating.
7. **`claim` persists only the won set.** A tiebreak loser's record MUST NOT contain the conceded path. Post-`wait-for` re-claim is a genuine acquisition.
8. **`wait-for` clears `waiting_on` on EVERY exit path** (via `finally`). No paused zombie is ever left behind, including on SIGINT.
9. **Release is per task, not per merge.** Leases are dropped on each task's clean success, not when the branch merges.
10. **`heartbeat` does NOT recreate absent records.** Missing record → `registry_error(reason:missing_record)` + return 0. No zombie records with empty fields.

---

## Env knobs (quick reference)

All registry env knobs are **env-only**: they are read directly from `os.environ` at use-site in `active-plan-registry.py` or `plan-path.sh`. They are NOT TOML config keys and are NOT emitted by `config.py export-env`. `config.py inspect-all` surfaces them under the "env-only" category for discoverability.

### Base and registry knobs

| Env var | Default | Description |
|---------|---------|-------------|
| `Z_HARNESS_EXTERNAL_DEFAULT` | `1` | Controls whether external tiers 2–4 are active. `0` opts out to in-repo behavior (tier 5 only). |
| `Z_HARNESS_BASE_DIR` | _(unset)_ | Explicit absolute override for artifact base. Bypasses anchor entirely. Must be absolute. |
| `Z_HARNESS_REGISTRY_ENABLED` | `1` | Set to `0` to make `claim`, `release`, `wait-for`, `register`, `heartbeat`, `update-scope`, `overlaps`, `reap`, `deregister` silent no-ops (for CI). `list` and `session-id` still work. |
| `Z_HARNESS_REGISTRY_STALE_SECS` | `1800` | Seconds after which `last_heartbeat` is considered stale. Reaper deletes at 2× margin for dead/remote; marks live local pid as stale only (carve-out). |
| `Z_HARNESS_STRICT_OVERLAP` | _(unset)_ | Set to `1` to make `explicit`×`explicit` exact scope-path overlaps a hard halt (exit 20). Does NOT affect held-path conflict behavior. |

### Wait / lease knobs

| Env var | Default | Description |
|---------|---------|-------------|
| `Z_HARNESS_AUTO_WAIT` | `1` | `1` = auto-park behind a senior held-path conflict using `wait-for` with the auto budget. `0` = restore interactive proceed/wait/abort menu for held conflicts. |
| `Z_HARNESS_AUTO_WAIT_BUDGET_SECS` | `300` | Wall-clock ceiling (seconds) for auto-park mode. On expiry: `wait-for` exits 10 (LOUD timeout), orchestrator aborts task or prompts user. Distinct from `WAIT_TIMEOUT_SECS`. |
| `Z_HARNESS_WAIT_POLL_SECS` | `30` | Seconds between poll iterations inside `wait-for`. Each iteration beats heartbeat, runs reap inline, and rechecks targets. |
| `Z_HARNESS_WAIT_TIMEOUT_SECS` | `1800` | Hard ceiling (seconds) for an explicit interactive wait (user selected "wait" in the overlap menu). Distinct from `AUTO_WAIT_BUDGET_SECS`. |
| `Z_HARNESS_WAIT_REQUIRE_MERGE` | `0` | **Reserved/deferred.** When `1`, a target would be cleared only when its branch is an ancestor of HEAD. Not yet wired. Leave at `0`. |

For full env-knob documentation including the base fallback chain and revert methods, see `docs/human/config.md` (section "Base-dir + registry env knobs").

---

## Discoverability: `/z-where`

Run `/z-where` at any time to see:
- Resolved base (+ tier)
- Repo-id
- Active plans from `active-plan-registry.py list` (slug, command, phase, branch, current_task, heartbeat age, overlap-with-me)
- Each plan's `held_paths` (files currently leased)
- Each plan's `waiting_on` (run_ids this plan is parked behind)
- Wait-edges rendered as `A ──waits──▶ B` for at-a-glance contention topology

This answers "where are my plans?", "what else is running?", and "why is my run paused?" without writing anything. If you see a senior plan with stale heartbeat and non-empty `held_paths`, that is the wedged-but-alive-senior pattern — see the "Wedged-but-alive senior" section above for resolution steps.

---

## Key entry points

- `scripts/active-plan-registry.py:565` — `cmd_session_id` — stable session-id derivation
- `scripts/active-plan-registry.py:584` — `cmd_register` — create run record (exits 3 on failure)
- `scripts/active-plan-registry.py:831` — `cmd_claim` — check-after-claim per-file lease
- `scripts/active-plan-registry.py:1119` — `cmd_wait_for` — senior-peer poll loop
- `scripts/active-plan-registry.py:1533` — `cmd_overlaps` — scope+held-path intersection check
- `scripts/active-plan-registry.py:1774` — `cmd_reap` — conservative dead-record cleanup
- `scripts/active-plan-registry.py:1423` — `_reap_inline` — wait-for's internal reap (pre-resolved active_dir)
- `scripts/active-plan-registry.py:355` — `_is_lease_capable` — schema-v2 + held_paths guard
- `scripts/active-plan-registry.py:376` — `_is_senior` — canonical lexicographic run_id ordering predicate
- `scripts/plan-path.sh:178` — `z_harness_base` — five-tier base resolution with anchor
- `scripts/plan-path.sh:337` — `active_plans_dir` — registry home path helper
- `agents/scope-extractor.md:1` — `scope-extractor` — Haiku scope array emitter

## How it interacts with others

- `plan-claim` — orthogonal hard slug-level mutex; uses `claims_dir()` from plan-path.sh. The lockless registry is advisory; plan-claim is the hard gate. Hermes cross-plan paths acquire plan-claim locks before operating.
- `hermes-orchestration` — calls `session-id` at workstream start; depends on registry for concurrent plan awareness.
- `commands` (z-implement-all, z-implement-next, z-plan, z-where, etc.) — primary consumers of register/overlaps/claim/release/wait-for/deregister.
- `followup-sink` — shares `<base>` via `followups_dir()`; must not participate in per-entry→global lock ordering of `followup_common.py`.
- `plan-layout-migration` — `migrate-plan-layout.sh` gates on `list --json` to refuse when any run is live.

## Edge cases / gotchas

- `Z_HARNESS_BASE_DIR` bypasses the anchor entirely — two sessions with different values silently partition their registries.
- `Z_HARNESS_REGISTRY_ENABLED=0` silences all coordination writes; `list` and `session-id` still work. Do not use in multi-session interactive environments.
- Reaper live-local-pid carve-out: a slow-but-alive local process past 2× stale keeps leases alive. Manual resolution: `python3 scripts/active-plan-registry.py release --run-id <id> --all`.
- v1 records (`schema_version < 2` or missing `held_paths`) are lease-incapable — never waited on.
- `held_conflict` in overlaps JSON is a TOP-LEVEL flat array, NOT nested inside peer entries. Absent (not empty array) when no conflicts exist.
- Two distinct wait budgets: `Z_HARNESS_AUTO_WAIT_BUDGET_SECS` (300s, auto-park) and `Z_HARNESS_WAIT_TIMEOUT_SECS` (1800s, user-explicit wait). Never silently proceed on exit 10.
- `run_id` ordering is LEXICOGRAPHIC, NOT chronological. `started_at` is display-only. `_is_senior()` is the sole authoritative predicate.
- `_reap_inline()` is the poll-loop reaper; `cmd_reap` is the CLI subcommand. Same policy, different call site — `_reap_inline` takes pre-resolved `active_dir`.
- `session-id` on macOS uses `<ppid>-<current_epoch>` fallback; export `Z_HARNESS_SESSION_ID` once at run start to stabilize across repeated calls.
- `Z_HARNESS_WAIT_REQUIRE_MERGE=1` is reserved/deferred — branch-ancestor cleared logic is NOT wired.

## Examples

- List all active plans: `python3 scripts/active-plan-registry.py list --json`
- Manual lease release for a wedged run: `python3 scripts/active-plan-registry.py release --run-id <run-id> --all`
- Dry-run migration preview: `scripts/migrate-plan-layout.sh --dry-run --all`
- Check overlap for current run: `python3 scripts/active-plan-registry.py overlaps --run-id $Z_HARNESS_RUN_ID --json`
- Resolve base tier in use: `bash scripts/plan-path.sh z_harness_base`

---

## See also

- `docs/human/config.md` — base-dir env knobs + full fallback chain + revert methods
- `docs/human/PLAN-LAYOUT.md` — plan directory layout + migration guide
- `docs/handoff-parallel-session-safety.md` — incident record + root-cause analysis + resolution note
- `scripts/active-plan-registry.py` — registry implementation
- `scripts/plan-path.sh` — base resolution + all path helpers
- `scripts/migrate-plan-layout.sh` — migration script (--dry-run, --all, --with-followups)
- `agents/scope-extractor.md` — Haiku scope-extraction subagent
