# Silent-failure protection

> Last updated: 2026-07-09
> Covers source: scripts/supervised-run.sh, scripts/hang-threshold.py, scripts/schedule-hang-check.sh, scripts/hang-check.sh, scripts/liveness.sh, scripts/notify-watchdog.sh, scripts/check-timeout.sh, scripts/config.py, scripts/active-plan-registry.py, scripts/hermes/watchdog_webhook.py, agents/reviewer.md, agents/remote-runner.md, skills/z-execute/SKILL.md, skills/z-overnight/SKILL.md

## Overview

Watchdog protection has two layers. Layer 1 is a hard-deadline enforcement wrapper (`scripts/supervised-run.sh`) that any script can call to run a killable subprocess (reviewer CLIs, ssh/rsync/cargo, generic Bash) under a process-group timeout; on deadline it kills the child and returns exit code `124`. Layer 2 is a scheduled, one-shot hang detector: `/z-execute` and `/z-overnight` each call `schedule-hang-check.sh` once at run start (gated on `watchdog.enabled` + the active-plan registry being on), which arms a self-removing launchd job (macOS) or a detached `sleep` fallback to run `hang-check.sh` at a metrics-derived horizon. The old long-lived daemon poller (`watchdog-sweep.sh`/`watchdog-spawn.sh`) is retired and those two scripts no longer exist in the tree — do not point anyone at them.

Native `Agent()` stalls cannot be killed from shell, so the two layers exist for different failure modes: Layer 1 recovers (kills + returns control) but only for subprocesses; Layer 2 can only detect-and-notify, and it covers the case a subprocess wrapper can't — a stuck native agent turn. As of this refresh, telemetry confirms Layer 1 is exercised regularly in real (non-test) runs — 124+ recorded `dispatch_start`/`dispatch_end` pairs across local run history, including real `watchdog_timeout` kills outside of test fixtures. Layer 2 has **no confirmed real-world firing**: zero `watchdog_stall` events exist anywhere in local run history, and `schedule-hang-check.sh` itself does not emit a "scheduled" telemetry event, so there is no way to even confirm the one-shot job gets armed in production versus silently failing to schedule. This matches the substance of the 2026-06-21 "ships-but-inert" forensics for Layer 2, but the previously-cited root cause (`notify.level=off` blocking alerts) is now stale: `notify.level` defaults to `approval_only` and `watchdog_stall`/`watchdog_timeout` have been in the `approval_only` fire-set since commit `e6c54a0` (2026-06-19), which predates the forensics note. The honest current status is: Layer 2's notification path is wired and config-enabled by default, but nothing in the codebase proves it has ever actually fired outside of tests.

## Key entry points

- `skills/z-execute/SKILL.md:138` — hang-check scheduling step ("1b") — schedules one-shot hang-check after registry registration when watchdog is enabled and registry is on.
- `skills/z-overnight/SKILL.md:251` — hang-check scheduling step ("11") — same one-shot model for overnight runs.
- `scripts/supervised-run.sh:1` — hard-deadline wrapper — process-group timeout enforcement and dispatch lease events.
- `scripts/hang-threshold.py:1` — metrics threshold calculator — p90/p95 x margin with sparse-class fallback.
- `scripts/schedule-hang-check.sh:1` — scheduler — launchd one-shot or detached fallback; does not emit a scheduling telemetry event.
- `scripts/hang-check.sh:1` — one-shot detector — liveness scan plus notify-once marker; only emits `watchdog_stall` when a stall is actually found.
- `scripts/liveness.sh:1` — post-hoc inspector — unmatched `*_start` vs matching end events.
- `scripts/notify-watchdog.sh:1` — notification channel — Discord/macOS best-effort alert, config-gated.
- `scripts/hermes/watchdog_webhook.py:1` — orphaned file — only self-referenced; not imported anywhere. Superseded by `scripts/hermes/mcp-hermes-orchestrator.py` for Discord `so`.
- `scripts/check-timeout.sh:40` — `timeout_backend()` — shared `timeout|gtimeout|bash_fallback` resolution; header comments still reference the retired `watchdog-sweep.sh` as a caller (stale comment, not a live path).
- `scripts/config.py:243` — `watchdog` defaults block — `enabled` (default `true`), `stale_secs`, `timeout_secs.*`, `intervention_level`, `kill_grace_secs`.
- `scripts/active-plan-registry.py:281` — `_sigterm_watchdog()` — legacy pid-file cleanup during deregister; best-effort and non-fatal.
- `agents/reviewer.md:48` — reviewer supervised-run call — wraps the external reviewer provider invocation.
- `agents/remote-runner.md:71` — remote-runner supervised operations — rsync/cargo/ssh wrappers plus `remote_orphan_possible` warning on deadline.

## How it interacts with others

- `docs/human/statusline.md` (statusline-hud) — a separate, opt-in, positive-liveness signal (`scripts/zh-statusline.py` + `scripts/install-statusline.sh`) that shows live "subagent working" state in the Claude Code status line. It is implemented and shippable (contrary to older notes calling it unimplemented), but it is a different mechanism from this concept's alert-only Layer 2 — it doesn't emit or consume `watchdog_stall`/`watchdog_timeout` events.
- `docs/human/active-plan-registry.md` — the registry gates whether Layer 2 scheduling runs at all (`Z_HARNESS_REGISTRY_ENABLED`) and owns the legacy pid-cleanup path in `_sigterm_watchdog()`.
- `docs/human/config.md` — `watchdog.*` and `notify.level` are both resolved through `scripts/config.py`; `watchdog.timeout_secs.*` is config-file-only (not env-exported) so a typo'd env var is silently ignored rather than erroring.
- `agents/reviewer.md`, `agents/remote-runner.md` — both wrap their external-process calls in `supervised-run.sh` (Layer 1) and are the two confirmed-live consumers of the hard-deadline path.
- `skills/z-setup/SKILL.md` — documents the macOS `timeout(1)` absence and the `supervised-run.sh` bash-fallback + `timeout_degraded` event, but is not itself a new caller of the watchdog scripts.

## Edge cases / gotchas

- Alerts are inert unless `notify.level` allows `watchdog_stall`/`watchdog_timeout`; this is true by default now (`approval_only` fire-set includes both), but was not always the case — verify `notify.level` in your effective config before assuming alerts will surface.
- The old daemon scripts (`watchdog-sweep.sh`, `watchdog-spawn.sh`) are gone from the tree; do not document or reference them as live paths, and treat any lingering comments mentioning them (e.g. in `check-timeout.sh`) as stale.
- `scripts/schedule-hang-check.sh` never logs a "job scheduled" event, so absence of `watchdog_stall` telemetry cannot distinguish "scheduling never happened" from "scheduling happened and nothing was ever stale" — this is a real observability gap, not just a config problem.
- `liveness.sh` ignores broad lifecycle brackets and focuses on subagent/action starts with matching ends, so it won't flag a merely-long-running phase as a stall.
- `hang-threshold.py` class keys depend on event fields that actually exist (`persona_attempt_outcome` role/tier, `subagent_model`, or kind); sparse classes fall back to `watchdog.stale_secs`.
- Remote command timeouts may leave a remote `systemd-run` unit alive; `remote-runner` emits `remote_orphan_possible` guidance rather than attempting remote cleanup itself.
- `scripts/hermes/watchdog_webhook.py` is dead code from the retired Discord `so` webhook path — do not treat it as a live integration point.

## Memories

_Note: no memories recorded for this concept yet._
