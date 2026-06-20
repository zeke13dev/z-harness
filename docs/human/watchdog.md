# Silent-failure watchdog

A two-layer liveness mechanism so long z-harness runs no longer dead-wait on a silently-hung subprocess. Rather than relying on a single global timeout, the system combines a hard-deadline enforcement wrapper for killable dispatches with an out-of-band stall-detection loop for everything else, including un-killable native `Agent()` calls.

---

## Two-layer model

### Layer 1 — Enforcement (killable dispatches)

`scripts/supervised-run.sh` wraps every killable external dispatch (ssh, rsync, cargo, codex reviewer CLI, generic Bash) in a hard deadline:

- Prefers the system `timeout(1)` or `gtimeout` binary.
- Falls back to a guarded pure-bash deadline when no timeout binary is found (zero-dep; see macOS note below).
- On deadline: sends SIGTERM to the child process group, then SIGKILL after a grace period, and returns exit code **124** (matching GNU `timeout`'s convention).
- Emits `dispatch_start` and `dispatch_end` lease events to `events.jsonl` around every wrapped call.
- The exit code feeds the orchestrator's existing non-zero / retry / halt path — real recovery, not just detection.

### Layer 2 — Detection + alert (everything, including `Agent()` stalls)

`scripts/watchdog-sweep.sh` runs as a daemonized background poller spawned at run start:

- Reads `events.jsonl` for `dispatch_start` events with no matching `dispatch_end` past their deadline.
- Calls `liveness.sh` to detect unmatched subagent `*_start` events past the stale threshold — this covers hung native `Agent()` calls that have no PID a shell watchdog can signal.
- On a confirmed stall: emits a `watchdog_stall` event and alerts the human **out-of-band** via `notify-watchdog.sh` (Discord webhook and/or macOS desktop notification). Detection latency depends on config: a killable dispatch stall is detected within roughly its per-type timeout plus one sweep interval (e.g. ~6 min for a reviewer at the 300 s default, ~11 min for ssh/bash, ~31 min for cargo). An un-killable native `Agent()` stall is detected within `sweep_interval_secs` + `stale_secs` (≈6 min at defaults). Either way, this replaces the previous open-ended silent dead-wait with a **bounded, configurable alert**. Lower `watchdog.stale_secs` / `watchdog.sweep_interval_secs` / the per-type `watchdog.timeout_secs.<type>` values for faster detection.

---

## Capability boundary (load-bearing)

This distinction is critical:

| Situation | Layer | Outcome |
|---|---|---|
| Killable subprocess stalls (ssh, rsync, cargo, reviewer CLI, Bash) | Enforcement | Hard kill + retry/halt — **real recovery** |
| Native `Agent()` call blocks the Claude runtime main loop | Detection + alert | Detect + notify human — **alert only, no auto-recovery** |

A hung native `Agent()` call blocks Claude Code's main loop from inside the runtime. There is no orchestrator PID a shell watchdog can signal. For that case, the watchdog **detects and alerts the human** — it cannot auto-recover. The alert payload includes an actionable `kill <pid>` line when the PID is known.

---

## `events.jsonl` as the lease

The shared `events.jsonl` file is the watchdog lease mechanism — no extra registry or lock files. It is:

- **Append-only**: `log-event.sh` uses `flock` for write-safe appends.
- **Zero write-contention**: safe under Hermes parallelism.
- **Self-describing**: a `dispatch_start` past its `deadline_ts` with no matching `dispatch_end` (matched by `dispatch_id`) is a stall by definition.

A `dispatch_start` event that loses its matching `dispatch_end` (e.g. the process was killed before the emit) is still detected as a stall.

---

## Configuration knobs

All watchdog config lives in the `[watchdog]` section of `config.toml`. Edit via `/z-setup wizard --scope watchdog` or directly.

| Key | Default | Description |
|---|---|---|
| `watchdog.enabled` | `true` | Master switch for the sweep layer (enforcement always active) |
| `watchdog.sweep_interval_secs` | `60` | How often the sweep loop polls |
| `watchdog.intervention_level` | `notify` | `observe` = emit event only; `notify` = emit + out-of-band alert |
| `watchdog.kill_grace_secs` | `10` | SIGTERM → SIGKILL grace period in the bash fallback |
| `watchdog.max_lifetime_secs` | `86400` | Orphan-leak backstop: sweep self-exits after this many seconds |
| `watchdog.stale_secs` | `300` | Stale threshold for liveness-detected subagent stalls |
| `watchdog.timeout_secs.bash` | `600` | Per-type deadline defaults (seconds) |
| `watchdog.timeout_secs.ssh` | `600` | |
| `watchdog.timeout_secs.rsync` | `660` | |
| `watchdog.timeout_secs.cargo` | `1800` | |
| `watchdog.timeout_secs.reviewer` | `300` | |

**Note:** `watchdog.timeout_secs.*` per-type values are **config-file-only** — they are not exported as env vars. Read via `config.py get watchdog.timeout_secs.<type>`. A typo'd env var (e.g. `Z_HARNESS_WATCHDOG_TIMEOUT_SECS`) is silently ignored.

`watchdog.enabled` is re-read from config on every sweep iteration — it acts as a live kill-switch without restarting the sweep.

---

## Notification gating

Watchdog events respect the `notify.level` config:

- `watchdog_stall` and `watchdog_timeout` fire under `approval_only` (the default) **and** `all`.
- They are suppressed under `off`.

The alert fires at most once per stall identity (notify-once dedup):
- **Dispatch stalls**: deduped by `dispatch_id`.
- **Liveness stalls**: deduped by the subagent identity (`<base>-<tid>`).

Alert channels (best-effort, all available channels):
1. **Discord webhook** — if `notify.discord_webhook_url` is set; works while the orchestrator is blocked.
2. **macOS desktop notification** — via `osascript`; zero-config local fallback.

---

## macOS: install coreutils for robust timeouts

On macOS, the system does not ship a `timeout(1)` binary. The enforcement layer falls back to a pure-bash deadline implementation, which is zero-dependency and works correctly, but the native `timeout`/`gtimeout` binary is preferred for robustness and predictable signal semantics.

**Recommendation:**

```sh
brew install coreutils
```

This installs `gtimeout` (GNU coreutils), which `supervised-run.sh` detects automatically via `check-timeout.sh`. No configuration needed after install.

When running on the bash fallback, the harness emits a one-time `timeout_degraded` event per run (`{backend:"bash_fallback", recommend:"brew install coreutils"}`) to flag the degraded state in telemetry.

---

## Events emitted

| Event | Emitted by | Payload |
|---|---|---|
| `dispatch_start` | `supervised-run.sh` | `{dispatch_id, type, pid, timeout_s, deadline_ts}` |
| `dispatch_end` | `supervised-run.sh` | `{dispatch_id, exit_code, wall_ms}` |
| `watchdog_timeout` | `supervised-run.sh` | `{dispatch_id, type, timeout_s, killed:true}` |
| `watchdog_stall` | `watchdog-sweep.sh` | `{run, dispatch_id\|phase, reason, pid\|null, age_s}` |
| `watchdog_scan_inconclusive` | `watchdog-sweep.sh` | `{run, reason}` — emitted when a read times out |
| `timeout_degraded` | `supervised-run.sh` | `{run, backend:"bash_fallback", recommend:"brew install coreutils"}` |

---

## Where the sweep is wired

In v1, the sweep is spawned at run start by:

- `commands/z-implement-all.md` (gated by `watchdog.enabled` + `Z_HARNESS_REGISTRY_ENABLED`)
- `commands/z-overnight.md` (same gate)

Other commands inherit the enforcement-layer benefits via `reviewer.md` and `remote-runner.md` without needing the sweep directly.

---

## v1 non-goals

- **No auto-recovery of hung `Agent()` calls** — impossible from shell; notify-only.
- **No discretionary SIGKILL by the sweep** — only the enforcement wrapper kills, on its deterministic deadline.
- **No remote-side cleanup of orphaned `systemd-run` units** — the alert includes a cleanup hint; a follow-up may automate it.
- **Not wired into every command** — only long-running commands in v1.
- **No cron/launchd watchdog** — backgrounded poller only.
