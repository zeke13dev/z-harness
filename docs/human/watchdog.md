# Silent-failure protection

> Last updated: 2026-06-26
> Covers source: scripts/supervised-run.sh, scripts/hang-threshold.py, scripts/schedule-hang-check.sh, scripts/hang-check.sh, scripts/liveness.sh, scripts/notify-watchdog.sh, scripts/check-timeout.sh, scripts/config.py, scripts/active-plan-registry.py, scripts/hermes/watchdog_webhook.py, agents/reviewer.md, agents/remote-runner.md, skills/z-execute/SKILL.md, skills/z-overnight/SKILL.md

## Overview

Watchdog protection has two layers:

1. **Hard-deadline enforcement for killable subprocesses.** `scripts/supervised-run.sh` wraps reviewer CLIs, ssh/rsync/cargo, and generic Bash with deterministic timeouts. On deadline it kills the child process group and returns `124`.
2. **Scheduled one-shot hang detection for runtime-native stalls.** `/z-execute` and `/z-overnight` schedule `hang-check.sh` once at run start when `watchdog.enabled` and registry are enabled. The old long-lived daemon poller (`watchdog-sweep.sh`/`watchdog-spawn.sh`) is retired.

Native `Agent()` stalls cannot be killed from shell. The scheduled hang-check can only detect and notify; the enforcement wrapper is the only layer that can recover by killing a subprocess.

## Layer 1 — supervised-run

`supervised-run.sh --run R --type T --timeout N -- cmd ...` emits `dispatch_start` / `dispatch_end` lease events around the child. `--timeout 0` resolves `watchdog.timeout_secs.<type>` from config, falling back to 600. It prefers `timeout`/`gtimeout`, then falls back to a Bash process-group deadline. Diagnostics go to stderr so child stdout can be captured byte-for-byte.

## Layer 2 — scheduled hang-check

`hang-threshold.py` reads metrics and computes per-class thresholds from p90 (default) wall time times a margin, excluding test noise. Sparse classes fall back to `watchdog.stale_secs`.

`schedule-hang-check.sh` schedules one `hang-check.sh` invocation for the future horizon. On macOS it writes a self-removing launchd one-shot; elsewhere it uses a detached sleep fallback. `hang-check.sh` calls `liveness.sh` for unmatched stale `*_start` events and notifies once through `notify-watchdog.sh`.

When Hermes supervises a Discord `so` job, `HERMES_SO_JOB_ID` is propagated
into `notify-watchdog.sh` as `job_id`. Hermes webhook payloads include
`event`, unique `event_id`, `run_id` when known, `slug` when known, `pid` when
known, `severity`, and `reason`; `next_step` is optional metadata. The Hermes
channel is fail-open and HMAC-signed when a secret is configured. Payloads are
inputs to Hermes routing, not detached user instructions.

## Key entry points

<!-- AUTO-START: entry-points -->
- `skills/z-execute/SKILL.md:130` — z-execute scheduling hook — schedules one-shot hang-check after registry registration when watchdog is enabled.
- `skills/z-overnight/SKILL.md:251` — z-overnight scheduling hook — same one-shot model for overnight runs.
- `scripts/supervised-run.sh:1` — hard-deadline wrapper — process-group timeout enforcement and dispatch lease events.
- `scripts/hang-threshold.py:1` — metrics threshold calculator — p90/p95 × margin with sparse fallback.
- `scripts/schedule-hang-check.sh:1` — scheduler — launchd one-shot or detached fallback.
- `scripts/hang-check.sh:1` — one-shot detector — liveness scan plus notify-once marker.
- `scripts/liveness.sh:1` — post-hoc inspector — unmatched `*_start` vs matching end events.
- `scripts/notify-watchdog.sh:1` — notification channel — Discord/macOS best-effort alert.
- `scripts/hermes/watchdog_webhook.py:1` — Hermes receiver — validates signed payloads, dedups events, and routes to the owning Discord thread or subscription fallback.
- `scripts/check-timeout.sh:37` — timeout backend helper — shared `timeout|gtimeout|bash_fallback` resolution.
- `scripts/config.py:191` — watchdog defaults — enabled/stale/timeout/grace config.
- `scripts/active-plan-registry.py:281` — legacy watchdog pid cleanup — best-effort SIGTERM/SIGKILL for recorded pid files.
- `agents/reviewer.md:47` — reviewer supervised-run call — wraps external reviewer provider.
- `agents/remote-runner.md:68` — remote-runner supervised operations — rsync/cargo/ssh wrappers and orphan warning path.
<!-- AUTO-END: entry-points -->

## Invariants

- Killable subprocesses can be killed and routed to retry/halt; native Agent stalls can only be detected and alerted.
- `dispatch_id` pairs dispatch start/end events; matching must not rely only on type or pid.
- `supervised-run.sh` preserves child stdout and writes its own diagnostics to stderr.
- Exit code `124` means the wrapper enforced a deadline.
- Watchdog telemetry and notification are fail-open; failure must not prevent the wrapped command or scheduled check from completing.
- Scheduled hang-check exits 0 even on detection/evaluation issues; it must not fail loudly.
- Notify-once markers prevent repeated alerts for the same run/reason.
- `watchdog.timeout_secs.*` is config-file-only and read via `config.py get`, not env-exported.
- Hermes-supervised `so` watchdog payloads require `job_id`; fallback `run_id`/pid/slug lookup is for legacy or degraded sources only.

## Gotchas

- Alerts are inert unless notification config allows `watchdog_stall` / `watchdog_timeout`.
- The old daemon scripts are gone; do not document `watchdog-sweep.sh` or `watchdog-spawn.sh` as live paths.
- `liveness.sh` ignores broad lifecycle brackets and focuses on subagent/action starts with matching ends.
- `hang-threshold.py` class keys depend on event fields that actually exist (`persona_attempt_outcome` role/tier, `subagent_model`, or kind).
- Remote command timeouts may leave a remote systemd-run unit alive; `remote-runner` emits `remote_orphan_possible` guidance.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/watchdog.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
