# Silent-failure protection

A two-layer liveness mechanism so long z-harness runs no longer dead-wait on a
silently-hung subprocess. A hard-deadline enforcement wrapper handles killable
dispatches; a scheduled one-shot hang-check handles everything else, including
un-killable native `Agent()` calls.

> History: Layer 2 was originally a daemonized background poller
> (`watchdog-sweep.sh` + `watchdog-spawn.sh`). That daemon was **retired** by the
> `statusline-hud` plan (Workstream B) — it never fired outside tests, could not
> notify (notify was off), was host-local, and added flock/daemonization
> complexity. It is replaced by the scheduled one-shot below plus the in-chat
> statusLine HUD (see [statusline.md](statusline.md)) as the positive liveness
> glance. Layer 1 is unchanged.

---

## Two-layer model

### Layer 1 — Enforcement (killable dispatches) — unchanged

`scripts/supervised-run.sh` wraps every killable external dispatch (ssh, rsync,
cargo, codex reviewer CLI, generic Bash) in a hard deadline:

- Prefers the system `timeout(1)` or `gtimeout` binary (`brew install coreutils`
  on macOS); falls back to a guarded pure-bash deadline.
- On deadline: SIGTERM to the child process group, then SIGKILL after a grace
  period, returning exit code **124** (GNU `timeout` convention).
- Emits `dispatch_start` / `dispatch_end` lease events around every wrapped call.
- The exit code feeds the orchestrator's existing retry / halt path — real
  recovery, not just detection.

### Layer 2 — Detection + alert (scheduled one-shot hang-check)

Instead of a long-lived poller, the orchestrator (`/z-implement-all`,
`/z-overnight`) schedules a **one-shot** check at run start, timed to a
prediction of when work *should* be done:

- `scripts/hang-threshold.py` computes a per-class threshold = p90 (or p95) of
  historical `wall_ms` x a margin, from `metrics.jsonl`. Class key uses the fields
  that actually exist per event source (`persona_attempt_outcome` →
  `role`/`complexity_tier`; `<kind>:<subagent_model>` else `<kind>`). Sparse
  classes fall back to `watchdog.stale_secs`. Deterministic — no LLM.
- `scripts/schedule-hang-check.sh` schedules `hang-check.sh` to fire at that
  horizon. On macOS it uses a **self-removing launchd one-shot** (survives the
  spawning shell exiting and the machine sleeping); elsewhere a detached
  `sleep && run` fallback. `--self-test` proves launchd can actually execute the
  job; `--print` dry-runs the plan.
- `scripts/hang-check.sh` fires once: it asks `liveness.sh` whether any
  `*_start` in the run is still unmatched past the threshold and, if so, alerts via
  `notify-watchdog.sh` (notify-once per reason). It always exits 0 — a scheduled
  check must never fail loudly.

---

## Capability boundary (load-bearing)

| Situation | Layer | Outcome |
|---|---|---|
| Killable subprocess stalls (ssh, rsync, cargo, reviewer CLI, Bash) | Enforcement | Hard kill + retry/halt — **real recovery** |
| Native `Agent()` call blocks the Claude runtime main loop | Scheduled hang-check | Detect + notify human — **alert only, no auto-recovery** |

A hung native `Agent()` call blocks Claude Code's main loop from inside the
runtime; there is no orchestrator PID a shell watchdog can signal. For that case
the hang-check **detects and alerts** — it cannot auto-recover. (The complementary
in-chat positive signal is the statusLine HUD.)

---

## Alerts must be turned on (or this is inert)

Like the old daemon, the hang-check is silent until notify is configured:

```bash
python3 scripts/config.py set notify.level notify
python3 scripts/config.py set notify.discord_webhook_url "https://discord.com/api/webhooks/..."
python3 scripts/config.py should-notify --event watchdog_stall   # must print: yes
```

macOS desktop notifications work with no webhook; a headless/remote host needs the
Discord webhook (no desktop). Config lives in `[watchdog]` in `config.toml`
(`watchdog.enabled`, `watchdog.stale_secs`, etc.) — these keys are retained and
reused by the hang-check.
