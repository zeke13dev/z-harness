# active-plan-registry — Cross-session awareness registry

> Last updated: 2026-06-02
> Covers source: scripts/active-plan-registry.py, scripts/plan-path.sh, scripts/migrate-plan-layout.sh, agents/scope-extractor.md, commands/z-implement-all.md, commands/z-implement-next.md, commands/z-plan.md, docs/human/active-plan-registry.md, docs/handoff-parallel-session-safety.md

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

### Repo-id

`z_harness_repo_id()` produces a stable, short safe-basename for the per-repo directory:
- Format: `<repo-basename>-<8hex>` (e.g. `z-harness-1a2b3c4d`)
- The 8-hex suffix is derived from `sha256(realpath(git-common-dir))[0:8]`
- Keying on `git-common-dir` means all worktrees of one repo produce the same id

### Registry layout

The registry lives under the external base, not under the git checkout:

```
<base>/                          ← z_harness_base()
├── active-plans/                ← active_plans_dir()
│   ├── <run-id>.json            ← one file per live run
│   └── ...
├── plans/
│   └── <slug>/
│       ├── SPEC.md, PLAN.md, TASKS.md, ...
│       └── archive/<run-id>/
├── followups/                   ← followups_dir()
└── metrics.jsonl
```

Each `<run-id>.json` record (schema_version 1) contains:

```json
{
  "schema_version": 1,
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
  ]
}
```

`worktree_path` equals `repo_root` for the main checkout; for a linked git worktree it holds that worktree's absolute path. The `repo_id` (and therefore the shared registry directory) is the same for all worktrees of one repo.

---

## Registry subcommands

`scripts/active-plan-registry.py` provides the following subcommands (all operate on `active_plans_dir()`):

| Subcommand | Purpose |
|------------|---------|
| `session-id` | Prints a stable session id token. Returns `$Z_HARNESS_SESSION_ID` if already set; otherwise derives `<ppid>-<start_epoch>` from the parent shell. Callers should `export Z_HARNESS_SESSION_ID="$(session-id)"` once at run start. |
| `register --run-id ID --slug S --command C --phase P [--session SID]` | Creates/overwrites `<active>/ID.json` atomically. Validates ID is a safe basename. Idempotent. Emits `plan_registered`. Exit 3 on failure (LOUD). |
| `heartbeat --run-id ID [--phase P] [--current-task T] [--status running\|paused]` | Updates `last_heartbeat`, `phase`, `current_task` in own record. If the record is absent (already reaped/deregistered), emits `registry_error(reason:missing_record)` and returns 0 (no-op; does NOT recreate). NON-FATAL. |
| `update-scope --run-id ID --scope-json FILE` | Merges a scope array `[{path, confidence, reason}]` into the record. NON-FATAL; self-logs `registry_error` on failure. |
| `overlaps --run-id ID [--strict] [--scope-json FILE]` | Computes path intersection against every other live record's scope. Exit codes: `0` none, `10` advisory, `20` blocking (strict mode + explicit×explicit exact match). |
| `list [--json]` | Scans `<active>/*.json`, skips torn/partial files silently. |
| `reap` | Deletes records where (a) host=localhost AND pid is dead, OR (b) `last_heartbeat` older than 2× stale threshold. Marks remote/unknown-host records as `status:"stale"` at 1× threshold (no delete). |
| `deregister --run-id ID [--status complete\|aborted]` | Removes `<active>/ID.json`. Emits `plan_deregistered`. NON-FATAL. |

### Scope-extractor integration

At Phase 0 of `/z-implement-all`, `/z-implement-next`, and `/z-plan`, a Haiku subagent (`agents/scope-extractor.md`) reads SPEC.md + PLAN.md + TASKS.md (and optionally a specific task block) and emits a JSON scope array `[{path, confidence, reason}]`. The orchestrator writes the result via `update-scope`.

Confidence levels: `explicit` (path literally named in a Files: line) > `inferred` (strongly implied) > `broad` (directory/glob) > `unknown` (work named but files not).

Overlap comparison uses `path` (normalized repo-relative) only. Confidence ordering determines advisory vs. blocking tier.

### Overlap response protocol

| Overlap type | Default behavior | With `Z_HARNESS_STRICT_OVERLAP=1` |
|-------------|-----------------|----------------------------------|
| `explicit` × `explicit` exact path match | AskUserQuestion: proceed/wait/abort | Hard halt (exit 20 treated as blocking) |
| `inferred` or `broad` overlap | Warning + offer-wait | Same (advisory) |
| `unknown` confidence | Log + proceed | Same |
| Same session | Ignored | Ignored |
| Stale peer | Shown as stale | Shown as stale |

---

## Scope-extractor (Haiku subagent)

`agents/scope-extractor.md` (frontmatter `model: haiku`). Input: `repo_root`, `$BASE` (plan artifact dir), optional `task_id`. Reads SPEC.md + PLAN.md + TASKS.md (and the task block if `task_id` given), emits JSON `[{path, confidence, reason}]` to stdout.

A mechanical fallback is documented for offline use (parse `**Files:**` lines directly from TASKS.md), but the Haiku subagent is the primary path.

---

## Command integration (Phase 0)

### `/z-implement-all` and `/z-implement-next`

New Phase 0.0 (runs before the existing follow-up-running check):

1. `session-id` (export `Z_HARNESS_SESSION_ID`)
2. `register` the current run
3. Invoke `scope-extractor` (Haiku) to populate scope
4. Call `active-plan-registry.py overlaps --run-id $RUN`
5. Respond per overlap exit code (see table above)
6. Heartbeat at each task-dispatch boundary (`--current-task`)
7. `deregister` in finalize phase (complete) and on halt (aborted)

### `/z-plan`, `/z-plan-light`, `/z-debug`, `/z-do`, `/z-audit`, `/z-plan-split`

All run-creating commands get the same register/heartbeat/deregister 3-line block. `scope-extractor` runs after TASKS.md is written (for `/z-plan`) to seed scope for overlap detection.

---

## Migration: `migrate-plan-layout.sh` updates

`scripts/migrate-plan-layout.sh` gained two significant extensions:

1. **Live-run barrier (invariant 8):** before any migration, the script calls `active-plan-registry.py list` and refuses if any record shows `status:running`. This prevents TOCTOU races where an active `/z-implement-next` appends to a source TASKS.md after copy-verify but before `rm`.

2. **Full artifact manifest (`--dry-run --all`):** prints the complete mapping of source → target for all artifact types:
   - `z-harness/plans/<slug>/` and legacy-flat `z-harness/<slug>/` → `<base>/plans/<slug>`
   - `z-harness/archive/<run>/` → `<base>/archive/<run>`
   - `z-harness/metrics.jsonl` → `<base>/metrics.jsonl` (append/merge if target exists)
   - `z-harness/followups/` → `<base>/followups/` (only with `--with-followups`; default skip)

See `docs/human/PLAN-LAYOUT.md` for the full migration guide.

---

## Worktree-per-session safety

The registry and external base are both designed to be worktree-safe without any extra configuration:

- **Shared registry across worktrees.** The registry directory is `<z_harness_base()>/active-plans/`. Because `z_harness_repo_id()` keys on `sha256(realpath(git-common-dir))`, all linked worktrees of the same repo resolve to the same `repo_id` and therefore the same `<base>/active-plans/` directory. Each worktree's run records its own `worktree_path`, so the list output correctly attributes which worktree each run is in.

- **Base dir survives `git worktree remove`.** The resolved base for tiers 2–4 lives outside any worktree tree. Removing a worktree with `git worktree remove` does not touch `<base>/active-plans/`, the plans, metrics, or followups. In-flight heartbeats for a removed worktree will fail (the process is gone), but the registry entry is reaped normally by the local-dead-pid check.

- **Anchor in `git-common-dir`.** The anchor file (`<git-common-dir>/.z-harness-base`) lives in the repo's shared `.git/` directory, not in any worktree. It is set once and shared automatically — no setup needed when adding a new worktree.

- **No registry/base change needed for worktrees.** All worktree-safety guarantees flow from the `git-common-dir`-keyed design. See `docs/handoff-parallel-session-safety.md` (section "Worktree-per-session convention") for the recommended lifecycle.

---

## Cross-cutting invariants

1. **Lockless registry is safe ONLY because overlap is advisory.** No code may make overlap a hard gate without first replacing lockless delete with compare-and-delete or a registry lock.
2. **Never invert the existing lock order.** The registry takes NO global lock; it cannot participate in the per-entry→global ordering in `followup_common.py`.
3. **Single-writer-per-record.** Each `<run-id>.json` is written ONLY by the process that owns that run. Subagents RETURN data; the orchestrator performs the write.
4. **Base anchor — all processes of a repo MUST agree on the base.** Mismatch → `base_mismatch_detected` hard-fail before any artifact write.
5. **No mutation of the base while a run is live.** Migration refuses if `active-plan-registry.py list` shows any `status:running` record.

---

## Env knobs (quick reference)

| Env var | Default | Description |
|---------|---------|-------------|
| `Z_HARNESS_EXTERNAL_DEFAULT` | `1` | Controls whether external tiers 2–4 are active. `0` opts out to in-repo behavior (tier 5 only). |
| `Z_HARNESS_BASE_DIR` | _(unset)_ | Explicit absolute override for artifact base. Bypasses anchor entirely. |
| `Z_HARNESS_REGISTRY_ENABLED` | `1` | Set to `0` to make all registry subcommands silent no-ops (for CI). `list` and `session-id` still work. |
| `Z_HARNESS_REGISTRY_STALE_SECS` | `1800` | Seconds after which `last_heartbeat` is considered stale. Reaper deletes at 2× margin. |
| `Z_HARNESS_STRICT_OVERLAP` | _(unset)_ | Set to `1` to make `explicit`×`explicit` exact path overlaps a hard halt (exit 20). |

For full env-knob documentation including the fallback chain and revert methods, see `docs/human/config.md` (section "Base-dir + registry env knobs").

---

## Discoverability: `/z-where`

Run `/z-where` at any time to see:
- Resolved base (+ tier)
- Repo-id
- Active plans from `active-plan-registry.py list` (slug, command, phase, branch, current_task, age, overlap-with-me)

This answers the "where are my plans?" and "what else is running?" questions without writing anything.

---

## See also

- `docs/human/config.md` — base-dir env knobs + full fallback chain + revert methods
- `docs/human/PLAN-LAYOUT.md` — plan directory layout + migration guide
- `docs/handoff-parallel-session-safety.md` — incident record + root-cause analysis + worktree-per-session convention
- `scripts/active-plan-registry.py` — registry implementation
- `scripts/plan-path.sh` — base resolution + all path helpers
- `scripts/migrate-plan-layout.sh` — migration script (--dry-run, --all, --with-followups)
- `agents/scope-extractor.md` — Haiku scope-extraction subagent
