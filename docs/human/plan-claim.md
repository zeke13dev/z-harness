# plan-claim — Slug-level claim lock

> Last updated: 2026-07-11
> Covers source: scripts/plan-claim.sh, scripts/sink-lock.sh, scripts/plan-path.sh (claims_dir), skills/z-plan/SKILL.md, skills/z-audit-plan/SKILL.md

## Overview

The plan-claim subsystem adds a **hard, slug-level claim lock** to the setup phase of `/z-plan` and `/z-audit-plan`. When a second Claude session attempts to plan or audit a slug already claimed by a live peer it is told about the conflict and offered a choice — rather than silently double-working and clobbering `SPEC/PLAN/TASKS` artifacts.

The claim lock is orthogonal to the **lockless awareness registry** (`scripts/active-plan-registry.py`). The registry is advisory — it surfaces concurrent sessions but never blocks. The claim lock is a hard mutex. They must never be confused:

- **Awareness registry** — lockless, advisory, per-run JSON records in `<base>/active-plans/`. Overlap output is never a hard gate (Invariant 1).
- **Claim lock** — hard per-slug flock in `<base>/active-plans/claims/<slug>.lock`. First acquirer wins; contender is told to wait, abort, or use a new slug.

The Hermes parallelism layer (`scripts/hermes-execute.py`, `scripts/hermes/cross_plan.py`) also acquires claim locks directly when scheduling multiple plans concurrently — always in sorted ascending slug order to guarantee deadlock-freedom (INV-6 in hermes-orchestration). `/z-reconcile` is a third, read-only consumer: it uses the `reap-stale` subcommand to classify lock files during a workspace audit without ever acquiring, releasing, or killing anything.

**Two claiming call sites now coexist (skill-overhaul-phase1, uncommitted).** `scripts/z-preflight.sh` was introduced as a single-call setup ceremony (resolve/session-id/RUN-stamp/**claim**/register/run-brief-init/run_start/kernel-resolve, in that fixed order) that several write-skills now delegate to, but **not every claiming skill has been migrated onto it**:

- **`/z-plan`** delegates claim acquisition to `scripts/z-preflight.sh` (no `--no-claim`). The wrapper exports `CLAIM_HELD` and resolves the stale-takeover branch (acquire rc==2) *silently* — see "Stale-takeover is now silent for preflight-delegated callers" below.
- **`/z-audit-plan`** has **not** been migrated: it still calls `plan-claim.sh acquire`/`heartbeat`/`release` directly and branches on `CLAIM_RC` itself, retaining the original interactive `AskUserQuestion` menu (including a default-ABORT stale-takeover gate). It does not use `CLAIM_HELD` at all.
- **Read-only skills** (`/z-stats`, `/z-explore`, `/z-audit`) call `scripts/z-preflight.sh --no-claim`, which skips claim acquisition entirely (step 4 of the wrapper is never invoked; `CLAIM_HELD` is unconditionally `"0"`). This preserves each of those skills' original no-lock behavior while still giving them the shared resolve/session-id/register/run-brief/kernel ceremony.

This split is a real, current inconsistency in the codebase (not a doc error) — see the gotcha below. Do not assume both write-skills behave identically on contention/takeover.

**Note on source of truth:** the caller-side wiring for `/z-plan` and `/z-audit-plan` lives in `skills/z-plan/SKILL.md` and `skills/z-audit-plan/SKILL.md`, not in the retired per-command markdown tier — the `commands/` directory was retired (skills-atom re-flip, 2026-06-20) and no longer exists in this repo. `scripts/z-preflight.sh` is documented in its own script header; this concept covers `plan-claim.sh`/`sink-lock.sh`/`plan-path.sh` and the two skills' claim-related wiring, not the preflight wrapper's full ceremony.

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

`plan-claim.sh` parses it by splitting on the first and second `::` only, so `command` may itself contain double-colons. Acquire rejects any field that contains a `:` character (exit 2, usage) to preserve the delimiter invariant.

### Session-id persist + restore (Invariant 7)

`active-plan-registry.py session-id` is not stable across separate invocations on macOS (it returns `<ppid>-<now-epoch>` without `/proc`). The session id therefore:

1. Is exported exactly once at run start (`Z_HARNESS_SESSION_ID`).
2. Is persisted to `$Z_HARNESS_PLAN_DIR/archive/$RUN/session-id` immediately after export.
3. On resume (e.g. after a crash), is restored from the persisted file *before* the claim acquire: `if [[ -z "$Z_HARNESS_SESSION_ID" && -f .../session-id ]]; then export Z_HARNESS_SESSION_ID="$(cat .../session-id)"; fi`.

`plan-claim.sh` treats `--session` as required input and **never** calls `session-id` itself. The self-reentry guard's correctness depends on this persist+restore: without it a resumed run would see its own prior claim as a foreign contender. This holds whether the caller acquires directly or via `scripts/z-preflight.sh` (the wrapper follows the exact same persist/restore rule internally — it accepts `--session` and otherwise mints via `active-plan-registry.py session-id`).

### Claim-first ordering (Invariant 2)

In both `/z-plan` and `/z-audit-plan`, claim acquisition is the **first** action after the slug and run-id are resolved — before `run-brief.sh init`, before `register`, before any artifact read/write. The hard lock is authoritative; the awareness-registry read is advisory only. This ordering holds regardless of whether the caller acquires via `scripts/z-preflight.sh` (step 4 of its fixed sequence, before register at step 5) or directly (as `/z-audit-plan` still does).

### CLAIM_HELD flag — preflight-delegated callers only

For skills that delegate to `scripts/z-preflight.sh` (currently `/z-plan`), the wrapper itself sets and exports `CLAIM_HELD` to exactly `1` or `0` as part of its fixed output contract; the calling skill never sets it manually. All of `/z-plan`'s downstream heartbeat guards and release guards evaluate `${CLAIM_HELD:-0}`.

| Outcome (inside `z-preflight.sh`) | CLAIM_HELD |
|---------|-----------|
| acquire rc==0, output is `acquired` or `self-reentry` | `1` — caller holds the lock |
| acquire rc==0, output is `disabled` (`Z_HARNESS_CLAIM_DISABLE=1`) | `0` — no lock |
| acquire rc==2 (stale-takeover — wrapper resolves this silently, see below) | `1` — caller holds the lock |
| acquire rc==1 (live peer) | n/a — `z-preflight.sh` HARD STOPS (exit 10) before returning any exports |
| `--no-claim` passed (read-only skills) | `0` — claim step is skipped entirely |
| acquire rc==3 (corrupt) | n/a — `z-preflight.sh` HARD STOPS (exit 11) before returning any exports |

**`/z-audit-plan` does not use `CLAIM_HELD` at all.** It calls `plan-claim.sh acquire` directly and gates every downstream heartbeat/release call on `${CLAIM_RC:-1} -eq 0` instead (see its `SKILL.md`, e.g. the slug-select heartbeat guard and the Phase-9/halt release guards). A missing `CLAIM_RC` assignment in `/z-audit-plan` has the same failure mode as a missing `CLAIM_HELD` assignment would in `/z-plan`: downstream heartbeats silently skip and the lock leaks.

### Stale-takeover is now silent for preflight-delegated callers

**This is the load-bearing behavior change (skill-overhaul-phase1, LEDGER T106).** Previously, both `/z-plan` and `/z-audit-plan` treated acquire rc==2 (stale-takeover — the caller now holds a lock a dead/expired peer used to hold) as its own interactive `AskUserQuestion` gate with a default-ABORT (release-then-exit) outcome. That design still exists **verbatim in `/z-audit-plan`** (which calls `plan-claim.sh` directly), but it has been **replaced for `/z-plan`** by `scripts/z-preflight.sh`'s non-interactive, fixed policy:

> acquire rc==2 (stale-takeover succeeded — the caller now holds the lock) → `CLAIM_HELD=1`, proceed. No `AskUserQuestion`. A single `NOTE:` line is written to **stderr only** (`z-preflight.sh: NOTE: stale-takeover on slug <slug>: <holder-json>`).

The rationale documented in `z-preflight.sh`'s header and echoed in `skills/z-plan/SKILL.md`: the OS-level takeover has *already happened* by the time the caller can react (the daemon is dead, the flock has already changed hands) — refusing to use the freshly-acquired lock would just mean releasing it right back for no benefit, since nothing else can claim it in the interim. `z-preflight.sh` is a strictly non-interactive script (it never reads stdin or calls `AskUserQuestion` — see its own header contract) and therefore cannot ask; it makes this one fixed choice instead. `/z-plan`'s `SKILL.md` documents this explicitly: *"stale-takeover is resolved inside the wrapper, not asked here... This supersedes the pre-wrapper design where stale-takeover was its own interactive gate."*

**Live-peer contention (acquire rc==1) is still a hard stop, not a silent proceed**, for preflight-delegated callers: `z-preflight.sh` exits 10 (with the holder JSON echoed to stderr) rather than proceeding, and the calling skill still owns presenting a menu (proceed-anyway / abort / use-new-slug) around that exit code — it is a hard stop at the wrapper level, but the *skill* still resolves it interactively (or via `Z_HARNESS_CLAIM_OVERRIDE=1` when unattended). Only the stale-takeover branch dropped its interactive gate; live-peer contention and corrupt-lock did not.

---

## Key entry points

- `scripts/plan-claim.sh:222` — `cmd_acquire` — Acquire slug claim lock; exit 0=acquired/self-reentry/disabled, 1=live-peer, 2=stale-takeover, 3=corrupt
- `scripts/plan-claim.sh:307` — `cmd_heartbeat` — Refresh TTL and detect lost claim; exit 0=ok/transient-error, 9=confirmed-lost
- `scripts/plan-claim.sh:375` — `cmd_release` — Release lock best-effort using `--expected-holder` guard; always exit 0
- `scripts/plan-claim.sh:402` — `cmd_status` — Read-only holder JSON; exit 0=printed, 3=corrupt
- `scripts/plan-claim.sh:421` — `cmd_reap_stale` — Read-only stale check (delegates to `sink-lock.sh check-stale`); NEVER acquires/releases/kills; exit 0=held, 1=free, 2=stale, 3=corrupt
- `scripts/plan-path.sh:346` — `claims_dir` — Returns `<z_harness_base>/active-plans/claims`
- `scripts/sink-lock.sh` — `sink-lock.sh` — Low-level flock+daemon+TTL primitive; plan-claim.sh delegates all flock mechanics to it

(`scripts/z-preflight.sh` step 4, `~scripts/z-preflight.sh:196-230`, is the new call site that resolves the stale-takeover branch silently for delegated callers — see "How it works" above. It is not itself an entry point of this concept; it is documented by its own script header and owned by the broader setup-ceremony surface, not by plan-claim.)

---

## Scripts

### `scripts/plan-claim.sh`

Thin, non-interactive wrapper over `sink-lock.sh`. Computes the canonical lock path, manages holder identity and TTL, emits structured events, and maps `sink-lock` exit codes to a stable contract. This contract is unchanged by the `z-preflight.sh` migration — `z-preflight.sh` is a caller of `plan-claim.sh`, not a fork of it; the exit codes and printed holder JSON described below are identical regardless of which caller invokes `acquire`.

**Non-interactive contract:** this script reads/writes/emits-events only. It never calls `AskUserQuestion`, never reads stdin. All decision-making (proceed/abort/use-new-slug) is the caller's — whether that caller is a skill acquiring directly (`/z-audit-plan`) or `scripts/z-preflight.sh` acquiring on a skill's behalf (`/z-plan`). Exit codes and printed holder JSON are the only interface.

#### Subcommands

| Subcommand | Required args | Description |
|------------|---------------|-------------|
| `acquire` | `--slug S --run-id R --session SID --command C [--ttl N]` | Acquire the slug claim lock |
| `heartbeat` | `--slug S --run-id R --session SID --command C [--ttl N]` | Refresh TTL; detect lost claim |
| `release` | `--slug S --run-id R --session SID --command C [--ttl N]` | Release the lock (best-effort) |
| `status` | `--slug S [--ttl N]` | Print holder JSON (read-only, no events) |
| `reap-stale` | `--slug S [--ttl N]` | Read-only stale classification (no events; never mutates the lock) |

#### Exit codes — `acquire`

| Code | Meaning | We hold the lock? |
|------|---------|-------------------|
| 0 | Acquired, self-reentry, or `Z_HARNESS_CLAIM_DISABLE=1` | Yes (or disabled) |
| 1 | Live-peer contention (holder JSON printed to stdout) | No |
| 2 | Stale-takeover succeeded — **we now hold the lock** | Yes |
| 3 | Corrupt lock or invalid-holder/invalid-args | No |

**Exit-2 is the normal post-crash recovery path**, not a rare edge case — see "Post-crash daemon leak" below. For a `/z-plan` run (preflight-delegated), exit-2 now resolves *silently* to proceeding; for `/z-audit-plan` (direct call), it still triggers an interactive default-ABORT gate.

#### Exit codes — `heartbeat`

| Code | Meaning |
|------|---------|
| 0 | Refreshed, disabled, or transient read error (`heartbeat_error`) |
| 9 | Confirmed lost claim (holder present-and-different, or lock free) |

Exit 9 fires **only** on a confirmed ownership change. A transient read/corrupt error during the heartbeat read is **not** exit 9 — it emits a `heartbeat_error` event and returns exit 0 (non-fatal). This distinction prevents a noisy filesystem from falsely triggering a "you've been taken over" warning.

#### Exit codes — `release`

Always exits 0 (best-effort). Uses `--expected-holder` so a non-matching holder (peer re-take) is a true no-op — the peer's lock is not disturbed.

#### Exit codes — `status`

| Code | Meaning |
|------|---------|
| 0 | Printed `{"state":"held",...}` or `{"state":"free"}` |
| 3 | Corrupt lock content |

**The holder JSON printed by `status` and by `acquire` (on exit 1/2) is best-effort and TOCTOU.** It is re-read *after* `sink-lock` already returned an exit code, so the holder may have changed or been freed in the interval. The gate keys on the exit code, not on the JSON — the JSON is display-only.

#### Exit codes — `reap-stale`

Read-only; delegates to `sink-lock.sh check-stale`. Prints exactly one lowercase word to stdout:

| Code | Word printed | Meaning |
|------|--------------|---------|
| 0 | `held` | Lock is live and held by a live process |
| 1 | `free` | No lock file or empty |
| 2 | `stale` | Lock held by a dead PID or expired heartbeat |
| 3 | `corrupt` | Non-empty but unparseable JSON |

`reap-stale` NEVER acquires, releases, or kills anything — it is a pure classification read used by `/z-reconcile` (see below) to decide whether a lock file is safe to manually remove. It is not part of the `/z-plan` / `/z-audit-plan` claim-first flow.

### `scripts/sink-lock.sh`

Low-level flock + heartbeat + stale-takeover primitive. `plan-claim.sh` delegates all flock mechanics to it. The `read-holder` subcommand is used internally by `plan-claim.sh` to read the current holder without re-implementing `.hb.lock` serialization:

```
scripts/sink-lock.sh read-holder <lock-path> [--ttl-seconds=N]
```

Prints `{"state":"held", holder, pid, started_at, last_heartbeat, heartbeat_age_s, stale:bool}` or `{"state":"free"}`. `plan-claim.sh` always passes its own TTL via `--ttl-seconds` so the `stale` flag is consistent with the TTL `acquire` uses.

**Signal-safety hardening (skill-overhaul-phase1, T118).** The background holder daemon's two lock-content critical sections (`write_lock_json_under_hblock` on startup, `zero_lock_under_hblock` in the SIGTERM/SIGHUP handler) now block `SIGTERM`/`SIGHUP` via `signal.pthread_sigmask(SIG_BLOCK, ...)` for the duration of the critical section, unblocking again in a `finally`. This closes a real self-deadlock race found under load stress: if a signal arrived *inside* `write_lock_json_under_hblock` while its own `.hb.lock` fd was still open, the handler's second `flock(LOCK_EX)` on the same file would block forever behind its own process's first fd — wedging the lock file for every future caller (heartbeat/release/check-stale all flock the same sentinel). This is purely an internal daemon-robustness fix; it does not change `plan-claim.sh`'s caller-facing exit-code or holder-JSON contract. See `docs/llm/lock-signal-safety.json` for the general pattern (applicable beyond this one file).

---

## Caller behavior (contention/takeover policy)

**`/z-plan` (delegates to `scripts/z-preflight.sh`, no `--no-claim`):**

| Acquire RC | z-preflight.sh behavior | Skill-level follow-up |
|----|-------------|----------------------------------|
| 0 | `CLAIM_HELD=1` (or `0` if `disabled`), proceed | Proceed |
| 1 (live peer) | HARD STOP — `z-preflight.sh` exits 10, holder JSON on stderr | Skill catches the non-zero preflight exit and presents its own menu: proceed anyway / abort / use-new-slug (interactive), or abort unless `Z_HARNESS_CLAIM_OVERRIDE=1` (unattended) |
| 2 (stale-takeover) | **Silent** — `CLAIM_HELD=1`, `NOTE:` to stderr only, proceed. No `AskUserQuestion`. | None — the wrapper already decided; the skill just sees `CLAIM_HELD=1` and continues |
| 3 (corrupt) | HARD STOP — `z-preflight.sh` exits 11 | Skill catches the non-zero preflight exit; abort (default) / proceed uncoordinated (unattended: abort unless `Z_HARNESS_CLAIM_OVERRIDE=1`) |

**`/z-audit-plan` (calls `plan-claim.sh` directly — not yet migrated):**

| RC | Interactive | Unattended (`Z_HARNESS_NO_ASK`) |
|----|-------------|----------------------------------|
| 0 | Proceed | Proceed |
| 1 (live peer) | AskUser: proceed anyway / abort (no use-new-slug — audit's slug is fixed to the plan being audited) | Abort unless `Z_HARNESS_CLAIM_OVERRIDE=1` |
| 2 (stale-takeover) | AskUser: proceed / abort (default abort — peer's partial SPEC/PLAN may exist); **release first on abort** | Abort (release) unless `Z_HARNESS_CLAIM_OVERRIDE=1` |
| 3 (corrupt) | AskUser: abort (default) / proceed uncoordinated (explicitly labeled); manual-cleanup hint | Abort unless `Z_HARNESS_CLAIM_OVERRIDE=1` (uncoordinated) |

At exit-2 abort (whichever caller path), release must be called first (we hold the lock we just took over). At exit-0/1/3 abort, no release is needed (we never acquired).

---

## Heartbeat cadence

`plan-claim.sh heartbeat` is called:

1. At every phase boundary (phase_end/phase-start telemetry points already in the skills).
2. **Before every `AskUserQuestion`** — this is the **load-bearing call**: it extends the TTL to survive the upcoming user-wait. The after-gate heartbeat (`user_wait_end`) is optional when the next phase heartbeat is imminent.

In `/z-audit-plan`, there is also an early heartbeat before the slug-select `AskUserQuestion` that can fire before the main claim gate resolves (guarded by `CLAIM_RC==0` at that point — `/z-audit-plan` uses `CLAIM_RC` directly for this guard, not `CLAIM_HELD`, since it never delegates to `z-preflight.sh`).

If heartbeat exits 9 (confirmed lost claim): warn the user prominently that the slug was taken over; offer abort vs continue-uncoordinated. Never silently continue writing.

---

## Release discipline

Release is called:

- **Normal completion (Phase 9):** `release` is called adjacent to and **before** `deregister` — the lock frees first, minimizing the window where the registry shows the run gone but the lock is still held. Both are best-effort (`|| true`).
- **Every halt-finalize path** that occurs after a successful claim: `release` is wired into every exit point in both commands that occurs after a successful `acquire`. A missed path orphans the lock until TTL.

Do **not** call `release` if the claim was never acquired (abort at the claim gate, or exit 3).

---

## Post-crash daemon leak

**`exit-2` is the normal post-crash recovery path.** The `sink-lock` holder daemon is `setsid`-detached and **survives an orchestrator SIGKILL** — it keeps the flock until its heartbeat ages past TTL, after which the next same-slug `acquire` performs a stale-takeover (exit 2).

Consequence: after a hard-kill, the detached daemon **leaks** until the next same-slug acquire's TTL-takeover kills it, or until reboot. This is acceptable — one blocked Python process. For `/z-audit-plan`, the unattended exit-2 default-aborts unless `Z_HARNESS_CLAIM_OVERRIDE=1`, so unattended same-slug crash-recovery is safely conservative (a partial SPEC/PLAN may exist). For `/z-plan`, the preflight wrapper's silent-proceed policy means an unattended `/z-plan` run **will** take over the stale lock and continue rather than abort — see "Stale-takeover is now silent for preflight-delegated callers" above.

---

## Manual unlock

If a plan is abandoned abnormally (hard-kill + no resume), the claim can be manually cleared. Prefer `/z-reconcile`, which drives this exact workflow through `plan-claim.sh reap-stale` and only proposes removal for locks it has confirmed are dead:

```bash
# Find the claims directory
bash scripts/plan-path.sh claims_dir

# Classify a specific slug's lock (read-only, no mutation)
bash scripts/plan-claim.sh reap-stale --slug <slug>

# If reap-stale reports "stale" or "free" AND the daemon PID is confirmed dead,
# remove the lock files for that slug:
rm <claims_dir>/<slug>.lock <claims_dir>/<slug>.lock.hb.lock
```

This is safe once you have confirmed no other session holds the slug (e.g. via `plan-claim.sh status --slug <slug>` or `reap-stale`). Never `rm` a lock file directly without first calling `reap-stale` — a lock whose daemon PID is alive must never be removed, regardless of what `reap-stale` reports.

---

## Env knobs

| Env var | Default | Scope | Description |
|---------|---------|-------|--------------|
| `Z_HARNESS_CLAIM_TTL_SECS` | `2700` | Env-only | TTL (seconds) for claim liveness. A heartbeat not refreshed within this window triggers a stale-takeover on the next `acquire`. Read by `plan-claim.sh` directly; not a TOML config key; not emitted by `export-env`. |
| `Z_HARNESS_CLAIM_OVERRIDE` | _(unset)_ | Env-only | Set to `1` to allow an unattended (`Z_HARNESS_NO_ASK`) run to proceed through contention (exit 1), stale-takeover (exit 2, `/z-audit-plan` path only — `/z-plan`'s preflight-delegated path already proceeds on exit 2 regardless), or corrupt lock (exit 3) without aborting. Default-safe: absent or `0` = unattended contention always aborts. |
| `Z_HARNESS_CLAIM_DISABLE` | _(unset)_ | Env-only | Set to `1` to skip all claim locking entirely. Every subcommand (`acquire`, `heartbeat`, `release`) becomes an immediate exit-0 no-op. Use as an escape hatch (CI, testing). When disabled, `release` is a safe no-op and the release path is not gated on event presence — it always exits 0 regardless of whether an acquire event was emitted. |

**Env-only — not TOML keys.** These three knobs are read inline by `plan-claim.sh` from the environment. They are NOT in `scripts/config.py`'s `DEFAULTS` or `VALIDATORS`, and `export-env` does NOT emit them.

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

`status` and `reap-stale` emit no events (pure reads). Event emission is otherwise non-fatal — claim correctness never depends on telemetry. Failures in `log-event.sh` are swallowed.

---

## Edge cases / gotchas

- **`/z-plan` and `/z-audit-plan` currently diverge on stale-takeover UX** — `/z-plan` (via `scripts/z-preflight.sh`) resolves it silently and proceeds; `/z-audit-plan` (direct `plan-claim.sh` call) still shows an interactive default-ABORT `AskUserQuestion`. This is a real, current inconsistency (skill-overhaul-phase1, uncommitted), not a doc error — do not assume the two write-skills behave the same way on this branch.
- **`CLAIM_HELD` vs `CLAIM_RC`** — `CLAIM_HELD` is only meaningful for skills delegating to `scripts/z-preflight.sh` (currently `/z-plan`); it is set automatically by the wrapper. `/z-audit-plan` never sets or reads `CLAIM_HELD` — it gates everything on `CLAIM_RC` directly. Do not port `${CLAIM_HELD:-0}` guard code into `/z-audit-plan` without also porting the `CLAIM_RC` assignment it depends on, or vice versa.
- **CLAIM_HELD flag missing (preflight-delegated callers)** — all downstream heartbeat and release guards evaluate `${CLAIM_HELD:-0}` silently to false; the lock leaks and heartbeats never fire. This flag is exported automatically by `z-preflight.sh`'s fixed output contract — a caller reading its output must `eval` the full export block, not cherry-pick lines.
- **Slug with `/` or `..`** — rejected at acquire (and at `status`/`reap-stale`, which also validate the slug) with exit 2/usage. Slugs are kebab-safe by construction; this is defense-in-depth.
- **Empty/missing base** — `plan-path.sh:claims_dir()` inherits the FATAL empty-base guard from `z_harness_base()`; the error is surfaced before any lock path is composed.
- **Event-logging failure** — non-fatal; claim correctness does not depend on telemetry.
- **Transient read error during heartbeat** — emits `heartbeat_error`, exits 0 (non-fatal). This is **not** exit 9. Only a confirmed ownership change (different holder present, or lock free) triggers exit 9.
- **`Z_HARNESS_CLAIM_DISABLE=1` with release** — release is a safe no-op; it does not gate on an acquire event being present. The release path always exits 0. This holds identically for both the direct-call and preflight-delegated paths (`z-preflight.sh` skips claim step 4 entirely if `--no-claim`, but `Z_HARNESS_CLAIM_DISABLE=1` is a `plan-claim.sh`-level knob independent of `--no-claim`).
- **plan-claim.sh `--ttl-seconds` mismatch** — `plan-claim.sh` must pass its own TTL to `sink-lock read-holder`. Omitting it causes `read-holder` to use its own default (7200s), producing a `stale:false` report for a lock that `acquire` (using 2700s basis) would actually take over.
- **Hermes cross-plan lock ordering** — `scripts/hermes/cross_plan.py` acquires claim locks in sorted ascending slug order. Any new cross-plan caller must follow the same convention to preserve deadlock-freedom.
- **`reap-stale` is read-only by design** — it must never be used as a substitute for `acquire`/`release`. `/z-reconcile` never removes a lock file itself without confirming the daemon PID is dead, even when `reap-stale` reports `stale`.
- **The per-command markdown tier no longer exists** — the caller-side wiring for `/z-plan` and `/z-audit-plan` lives entirely in `skills/z-plan/SKILL.md` and `skills/z-audit-plan/SKILL.md`. Any reference to the old `commands/` location for `z-plan.md` or `z-audit-plan.md` is stale (retired 2026-06-20, skills-atom re-flip).
- **`--no-claim` read-only skills** — `/z-stats`, `/z-explore`, and `/z-audit` invoke `scripts/z-preflight.sh --no-claim`, which skips step 4 (claim acquire) entirely. `plan-claim.sh acquire` is never invoked for these skills; `CLAIM_HELD` is unconditionally `"0"`. Contention/corrupt-lock exit codes (10/11) cannot occur under `--no-claim` since claiming never runs.
- **sink-lock.sh daemon signal-safety** — the daemon's two lock-content critical sections block `SIGTERM`/`SIGHUP` for their duration (pthread_sigmask) to prevent a self-deadlock re-entrant-flock race found under load stress. This is an internal robustness fix only; it does not change any exit code, event, or holder-JSON field documented here. See `docs/llm/lock-signal-safety.json`.

---

## How it interacts with others

- **`skills/z-plan/SKILL.md`** — delegates claim acquisition to `scripts/z-preflight.sh` (no `--no-claim`); reads `CLAIM_HELD` from the wrapper's export block. Calls `plan-claim.sh heartbeat` directly at every phase boundary and before every `AskUserQuestion`, and `plan-claim.sh release` at every halt path and at Phase 9 (release/heartbeat calls remain direct — only `acquire` is now wrapped). Offers `use-new-slug` on live-peer contention (surfaced via the wrapper's exit 10). Stale-takeover (exit 2) is resolved silently by the wrapper — no `AskUserQuestion` for that branch anymore.
- **`skills/z-audit-plan/SKILL.md`** — calls `plan-claim.sh acquire`/`heartbeat`/`release` directly (not yet migrated to `scripts/z-preflight.sh`); gates on `CLAIM_RC`, not `CLAIM_HELD`. Retains the original interactive contention/stale-takeover/corrupt menu (default-ABORT on stale-takeover); no `use-new-slug` option (slug is fixed to the plan being audited); early heartbeat before slug-select gate.
- **`scripts/z-preflight.sh`** — new one-call setup-ceremony wrapper (resolve → session-id → RUN-stamp → **claim** → register → run-brief-init → run_start → kernel-resolve). Owns the non-interactive claim-branching policy for its delegated callers: silent-proceed on stale-takeover (exit 2), hard-stop (exit 10/11) on contention/corrupt for the calling skill to interactively resolve, and `--no-claim` to skip claiming entirely for read-only skills. It is a caller of `plan-claim.sh`, not a replacement for it — `plan-claim.sh`'s own exit-code contract is unchanged.
- **`skills/z-reconcile/SKILL.md`** — read-only consumer. Uses `plan-claim.sh reap-stale --slug <slug>` (via `scripts/plan-path.sh claims_dir` for the lock path) to classify each existing lock file as `held`/`free`/`stale`/`corrupt`/`unknown` as part of a workspace audit. Never acquires, releases, heartbeats, or kills a daemon; a lock is only proposed for manual removal after confirming the daemon PID is dead.
- **`scripts/sink-lock.sh`** — provides the underlying flock + daemon + TTL mechanics. `plan-claim.sh` is a thin policy wrapper. Its holder daemon now also embeds the signal-safety discipline documented in `docs/llm/lock-signal-safety.json`.
- **`scripts/plan-path.sh`** — provides `claims_dir()` (the lock directory path resolver).
- **`scripts/active-plan-registry.py`** — **orthogonal**. The registry stays lockless and advisory. The claim lock and the registry write to different files under the same external base. Neither reads nor modifies the other.
- **`scripts/hermes-execute.py` / `scripts/hermes/cross_plan.py`** — Hermes parallelism layer acquires and releases claim locks directly (sorted ascending slug order) for cross-plan concurrency scheduling.
