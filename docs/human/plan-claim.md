# plan-claim — Slug-level claim lock

> Last updated: 2026-06-08
> Covers source: scripts/plan-claim.sh, scripts/sink-lock.sh, scripts/plan-path.sh (claims_dir), commands/z-plan.md, commands/z-audit-plan.md

## Overview

The plan-claim subsystem adds a **hard, slug-level claim lock** to the setup phase of `/z-plan` and `/z-audit-plan`. When a second Claude session attempts to plan or audit a slug already claimed by a live peer it is told about the conflict and offered a choice — rather than silently double-working and clobbering `SPEC/PLAN/TASKS` artifacts.

The claim lock is orthogonal to the **lockless awareness registry** (`scripts/active-plan-registry.py`). The registry is advisory — it surfaces concurrent sessions but never blocks. The claim lock is a hard mutex. They must never be confused:

- **Awareness registry** — lockless, advisory, per-run JSON records in `<base>/active-plans/`. Overlap output is never a hard gate (Invariant 1).
- **Claim lock** — hard per-slug flock in `<base>/active-plans/claims/<slug>.lock`. First acquirer wins; contender is told to wait, abort, or use a new slug.

---

## How it works

### Lock path

`scripts/plan-path.sh:claims_dir()` returns `<base>/active-plans/claims`. The lock file is `<claims_dir>/<slug>.lock`. The directory is created on first use (`mkdir -p`).

Because all worktrees of one repo share the same external base (enforced by the base-anchor mechanism), worktree-isolated sessions correctly contend on the same claim file.

### Holder identity (Invariant 6)

The holder string encoded into the lock is:

```
<session_id>::<run_id>::<command>
```

For example: `12345-1717800000::1717800001-my-feature::/z-plan`.

`plan-claim.sh` parses it by splitting on the first and second `::` only, so `command` may itself contain double-colons. Acquire rejects any field that contains a `:` character (exit 2, usage) to preserve the delimiter invariant. In practice none of the fields ever contain colons; this is defense-in-depth.

### Session-id persist + restore (Invariant 7)

`active-plan-registry.py session-id` is not stable across separate invocations on macOS (it returns `<ppid>-<now-epoch>` without `/proc`). The session id therefore:

1. Is exported exactly once at run start (`Z_HARNESS_SESSION_ID`).
2. Is persisted to `$Z_HARNESS_PLAN_DIR/archive/$RUN/session-id` immediately after export.
3. On resume (e.g. after a crash), is restored from the persisted file *before* the claim acquire: `if [[ -z "$Z_HARNESS_SESSION_ID" && -f .../session-id ]]; then export Z_HARNESS_SESSION_ID="$(cat .../session-id)"; fi`.

`plan-claim.sh` treats `--session` as required input and **never** calls `session-id` itself. The self-reentry guard's correctness depends on this persist+restore: without it a resumed run would see its own prior claim as a foreign contender. Even if the restore somehow fails, correctness is preserved by the deterministic exit-1/exit-2 takeover gate.

### Claim-first ordering (Invariant 2)

In both `/z-plan` and `/z-audit-plan`, `plan-claim.sh acquire` is the **first** action after the slug and run-id are resolved — before `run-brief.sh init`, before `register`, before any artifact read/write. The hard lock is authoritative; the awareness-registry read is advisory only.

---

## Scripts

### `scripts/plan-claim.sh`

Thin, non-interactive wrapper over `sink-lock.sh`. Computes the canonical lock path, manages holder identity and TTL, emits structured events, and maps `sink-lock` exit codes to a stable contract.

**Non-interactive contract:** this script reads/writes/emits-events only. It never calls `AskUserQuestion`, never reads stdin. All decision-making (proceed/abort/use-new-slug) is the caller's. Exit codes and printed holder JSON are the only interface.

#### Subcommands

| Subcommand | Required args | Description |
|------------|---------------|-------------|
| `acquire` | `--slug S --run-id R --session SID --command C [--ttl N]` | Acquire the slug claim lock |
| `heartbeat` | `--slug S --run-id R --session SID --command C [--ttl N]` | Refresh TTL; detect lost claim |
| `release` | `--slug S --run-id R --session SID --command C [--ttl N]` | Release the lock (best-effort) |
| `status` | `--slug S [--ttl N]` | Print holder JSON (read-only, no events) |

#### Exit codes — `acquire`

| Code | Meaning | We hold the lock? |
|------|---------|-------------------|
| 0 | Acquired, self-reentry, or `Z_HARNESS_CLAIM_DISABLE=1` | Yes (or disabled) |
| 1 | Live-peer contention (holder JSON printed to stdout) | No |
| 2 | Stale-takeover succeeded — **we now hold the lock** | Yes |
| 3 | Corrupt lock or invalid-holder/invalid-args | No |

**Exit-2 is the normal post-crash recovery path**, not a rare edge case — see "Post-crash daemon leak" below.

#### Exit codes — `heartbeat`

| Code | Meaning |
|------|---------|
| 0 | Refreshed, disabled, or transient read error (`heartbeat_error`) |
| 9 | Confirmed lost claim (holder present-and-different, or lock free) |

Exit 9 fires **only** on a confirmed ownership change. A transient read/corrupt error during the heartbeat read is **not** exit 9 — it emits a `heartbeat_error` event and returns exit 0 (non-fatal; retried at the next heartbeat point). This distinction prevents a noisy filesystem from falsely triggering a "you've been taken over" warning.

#### Exit codes — `release`

Always exits 0 (best-effort). Uses `--expected-holder` so a non-matching holder (peer re-take) is a true no-op — the peer's lock is not disturbed.

#### Exit codes — `status`

| Code | Meaning |
|------|---------|
| 0 | Printed `{"state":"held",...}` or `{"state":"free"}` |
| 3 | Corrupt lock content |

**The holder JSON printed by `status` and by `acquire` (on exit 1/2) is best-effort and TOCTOU.** It is re-read *after* `sink-lock` already returned an exit code, so the holder may have changed or been freed in the interval. The gate keys on the exit code, not on the JSON — the JSON is display-only.

### `scripts/sink-lock.sh`

Low-level flock + heartbeat + stale-takeover primitive. `plan-claim.sh` delegates all flock mechanics to it. The `read-holder` subcommand is used internally by `plan-claim.sh` to read the current holder without re-implementing `.hb.lock` serialization:

```
scripts/sink-lock.sh read-holder <lock-path> [--ttl-seconds=N]
```

Prints `{"state":"held", holder, pid, started_at, last_heartbeat, heartbeat_age_s, stale:bool}` or `{"state":"free"}`. `plan-claim.sh` always passes its own TTL via `--ttl-seconds` so the `stale` flag is consistent with the TTL `acquire` uses.

---

## Caller behavior (contention/takeover policy)

Both `/z-plan` and `/z-audit-plan` branch on `CLAIM_RC`:

| RC | Interactive | Unattended (`Z_HARNESS_NO_ASK`) |
|----|-------------|----------------------------------|
| 0 | Proceed | Proceed |
| 1 (live peer) | AskUser: proceed anyway / abort / use-new-slug (z-plan only) | Abort unless `Z_HARNESS_CLAIM_OVERRIDE=1` |
| 2 (stale-takeover) | AskUser: proceed / abort (default abort — peer's partial SPEC/PLAN may exist); **release first on abort** | Abort (release) unless `Z_HARNESS_CLAIM_OVERRIDE=1` |
| 3 (corrupt) | AskUser: abort (default) / proceed uncoordinated (explicitly labeled); manual-cleanup hint | Abort unless `Z_HARNESS_CLAIM_OVERRIDE=1` (uncoordinated) |

At exit-2 abort, release must be called first (we hold the lock we just took over). At exit-0/1/3 abort, no release is needed (we never acquired).

---

## Heartbeat cadence

`plan-claim.sh heartbeat` is called:

1. At every phase boundary (phase_end/phase-start telemetry points already in the commands).
2. **Before every `AskUserQuestion`** — this is the **load-bearing call**: it extends the TTL to survive the upcoming user-wait. The after-gate heartbeat (`user_wait_end`) is optional when the next phase heartbeat is imminent.

If heartbeat exits 9 (confirmed lost claim): warn the user prominently that the slug was taken over; offer abort vs continue-uncoordinated. Never silently continue writing.

---

## Release discipline

Release is called:

- **Normal completion (Phase 9):** `release` is called adjacent to and **before** `deregister` — the lock frees first, minimizing the window where the registry shows the run gone but the lock is still held. Both are best-effort (`|| true`).
- **Every halt-finalize path** that occurs after a successful claim: `release` is wired into every exit point in both commands that occurs after a successful `acquire`. A missed path orphans the lock until TTL.

Do **not** call `release` if the claim was never acquired (abort at the claim gate, or exit 3).

---

## Post-crash daemon leak

**`exit-2` is the normal post-crash recovery path.** The `sink-lock` holder daemon is `setsid`-detached and **survives an orchestrator SIGKILL** — it keeps the flock until its heartbeat ages past TTL, after which the next same-slug `acquire` performs a stale-takeover (exit 2). Because `cmd_acquire` also returns 2 whenever non-empty leftover content exists and the daemon wins the free flock, SIGKILL (which skips the daemon's content-zeroing SIGTERM handler) causes this path.

Consequence: after a hard-kill, the detached daemon **leaks** until the next same-slug acquire's TTL-takeover kills it, or until reboot. This is acceptable — one blocked Python process. The unattended exit-2 default-aborts unless `Z_HARNESS_CLAIM_OVERRIDE=1`, so unattended same-slug crash-recovery is safely conservative (a partial SPEC/PLAN may exist).

---

## Manual unlock

If a plan is abandoned abnormally (hard-kill + no resume), the claim can be manually cleared:

```bash
# Find the claims directory
bash scripts/plan-path.sh claims_dir

# Remove the lock files for a specific slug
rm <claims_dir>/<slug>.lock <claims_dir>/<slug>.lock.hb.lock
```

This is safe once you have confirmed no other session holds the slug (e.g. via `plan-claim.sh status --slug <slug>`).

---

## Env knobs

| Env var | Default | Scope | Description |
|---------|---------|-------|-------------|
| `Z_HARNESS_CLAIM_TTL_SECS` | `2700` | Env-only | TTL (seconds) for claim liveness. A heartbeat not refreshed within this window triggers a stale-takeover on the next `acquire`. Read by `plan-claim.sh` directly; not a TOML config key; not emitted by `export-env`. |
| `Z_HARNESS_CLAIM_OVERRIDE` | _(unset)_ | Env-only | Set to `1` to allow an unattended (`Z_HARNESS_NO_ASK`) run to proceed through contention (exit 1), stale-takeover (exit 2), or corrupt lock (exit 3) without aborting. Default-safe: absent or `0` = unattended contention always aborts. |
| `Z_HARNESS_CLAIM_DISABLE` | _(unset)_ | Env-only | Set to `1` to skip all claim locking entirely. Every subcommand (`acquire`, `heartbeat`, `release`) becomes an immediate exit-0 no-op. Use as an escape hatch (CI, testing). When disabled, `release` is a safe no-op and the release path is not gated on event presence — it always exits 0 regardless of whether an acquire event was emitted. |

**Env-only — not TOML keys.** These three knobs are read inline by `plan-claim.sh` from the environment. They are NOT in `scripts/config.py`'s `DEFAULTS` or `VALIDATORS`, and `export-env` does NOT emit them. `inspect-all` does not surface them unless the command is updated to include them explicitly.

---

## Events emitted

| Event kind | When |
|------------|------|
| `plan_claim_acquired` | Acquire exit 0 (fresh acquire) |
| `plan_claim_self_reentry` | Acquire exit 0 (same session, different run) |
| `plan_claim_contended` | Acquire exit 1 (live peer) |
| `plan_claim_stale_takeover` | Acquire exit 2 (stale takeover) |
| `plan_claim_released` | Release called |
| `plan_claim_lost` | Heartbeat exit 9 (ownership change confirmed) |
| `heartbeat_error` | Heartbeat exit 0 due to transient read failure (non-fatal) |
| `registry_error` | Acquire exit 3 (corrupt lock) |

Event emission is non-fatal — claim correctness never depends on telemetry. Failures in `log-event.sh` are swallowed.

---

## Edge cases

- **Slug with `/` or `..`** — rejected at acquire with exit 2/usage. Slugs are kebab-safe by construction; this is defense-in-depth.
- **Empty/missing base** — `plan-path.sh:claims_dir()` inherits the FATAL empty-base guard from `z_harness_base()`; the error is surfaced before any lock path is composed.
- **Event-logging failure** — non-fatal; claim correctness does not depend on telemetry.
- **Transient read error during heartbeat** — emits `heartbeat_error`, exits 0 (non-fatal). This is **not** exit 9. Only a confirmed ownership change (different holder present, or lock free) triggers exit 9.
- **`Z_HARNESS_CLAIM_DISABLE=1` with release** — release is a safe no-op; it does not gate on an acquire event being present. The release path always exits 0.

---

## How it interacts with others

- **`commands/z-plan.md`, `commands/z-audit-plan.md`** — call `acquire` at setup (claim-first, before register), `heartbeat` at every phase boundary and before every AskUserQuestion, `release` at every halt path and at Phase 9.
- **`skills/z-plan/SKILL.md`, `skills/z-audit-plan/SKILL.md`** — mirror the above (Invariant 5 — content parity).
- **`scripts/sink-lock.sh`** — provides the underlying flock + daemon + TTL mechanics. `plan-claim.sh` is a thin policy wrapper.
- **`scripts/plan-path.sh`** — provides `claims_dir()` (the lock directory path resolver).
- **`scripts/active-plan-registry.py`** — **orthogonal**. The registry stays lockless and advisory. The claim lock and the registry write to different files under the same external base. Neither reads nor modifies the other.
