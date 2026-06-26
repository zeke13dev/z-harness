# TASKS — Hermes Discord `so` session orchestration

Plan: [SPEC.md](../hermes-so-watchdog/SPEC.md) · [PLAN.md](../hermes-so-watchdog/PLAN.md) · [TESTS.md](../hermes-so-watchdog/TESTS.md)

> Superseded 2026-06-26: active implementation uses `scripts/hermes/so_mcp.py`
> and `scripts/so-mcp-server.py`; retired tmux/job-registry/supervisor/watchdog
> tasks are historical only.

No `REMOTE_VERIFY` tags unless an implementation task explicitly dogfoods `qt-bot` on its remote host; the core tests are local/fake.

---

## T001 — Hermes Discord `so` command parser and authorization  [ ]
**Files:** `scripts/hermes/discord_relay.py`, `scripts/hermes/config.py`, `tests/test_hermes_discord_relay.py` (NEW)
**Depends:** none
Extend Hermes Discord support from outbound halt relay to inbound command intake. Parse `so <host> <project> <task...> [using <z-command>]`. Add config for allowed channels/users and project aliases (e.g. `qt-bot`). Return a typed command object with `host`, `project`, `task`, `z_command`, requester/channel/message ids. Reject unauthorized users/channels and malformed commands with Discord-visible errors.
**Tests:** parse `so omp qt-bot fix blah using z-debug`; parse without `using`; reject unknown host/project; reject unauthorized requester; preserve task text exactly.
**Acceptance:** Hermes can understand the user's target Discord message without starting a process.
**DOCS:** hermes-orchestration
**Complexity:** medium

## T002 — Hermes job registry for Discord/tmux sessions  [ ]
**Files:** `scripts/hermes/so_jobs.py` (NEW), `scripts/hermes/config.py`, `tests/test_hermes_so_jobs.py` (NEW)
**Depends:** T001
Add a Hermes-owned job registry storing job id, Discord ids, requester, host, project, repo/worktree, execution host, transport/SSH target, workdir, z-command, task, tmux session, pid, z-harness run id, status, last pane digest, last progress time, and last watchdog event id. Atomic writes. Register job before first tmux send-keys. Provide status transitions and lookup by job id, run id/pid, slug, and Discord message/thread.
**Tests:** create/read/update; atomic rewrite; lookup by run id/pid/job id; malformed job files skipped; duplicate event id dedup field persists; tmux/pid operations resolve through recorded execution host/transport.
**Acceptance:** every `so` launch has durable Hermes state independent of z-harness active-plan records.
**Complexity:** medium

## T003 — Tmux launcher for Hermes `so` jobs  [ ]
**Files:** `scripts/hermes/session.py`, `scripts/hermes/so_jobs.py`, `tests/test_hermes_session.py` (NEW)
**Depends:** T001, T002
Implement tmux-backed launch for accepted `so` jobs. Generate an internal session name like `hermes-so-<job-id>`. Create tmux, launch selected host in the resolved project, send the initial instruction that tells OMP/Claude to run the requested task using the requested z-harness command (e.g. z-debug), and record pid/session metadata. Do not expose tmux names to users except diagnostics.
**Tests:** fake tmux command runner receives `new-session` then `send-keys`; generated session name is safe; initial prompt includes task and z-command; registry write happens before send-keys; launch failure marks job failed.
**Acceptance:** Hermes, not the user, owns tmux setup and prompt injection.
**Complexity:** high

## T004 — Hermes watchdog delivery and Discord thread resumption  [ ]
**Files:** `scripts/hermes/watchdog_webhook.py` (NEW), `scripts/hermes/so_jobs.py`, `tests/test_hermes_watchdog_webhook.py` (NEW)
**Depends:** T002, T007, T008
Add a Hermes receiver/handler for `notify-watchdog.sh` Hermes webhook payloads. Validate schema and HMAC when configured. Dedup by `event_id`. Map payloads to jobs by explicit `job_id`, `run_id`, `pid`, or slug. Prove matched payloads resume the original Discord thread using registry Discord ids. If that cannot be proven for a source, implement the fallback where the active Discord session subscribes to watchdog/job events for its jobs and triggers the same supervisor check path. Unknown payloads post an ops notification but do not mutate jobs.
**Tests:** valid signed payload maps to job and posts into the original fake Discord thread; duplicate event ignored; bad signature rejected; unknown run posts ops-only result; subscription fallback delivers the event to the owning fake Discord session when thread reconstruction is unavailable; missing optional fields tolerated but not used for unsafe guesses.
**Acceptance:** watchdog can tell the correct Hermes Discord session/thread that a supervised OMP session needs attention.
**DOCS:** watchdog
**Complexity:** high

## T005 — Ask-first prompt handling and feedback capture  [ ]
**Files:** `scripts/hermes/supervisor.py` (NEW), `scripts/hermes/so_jobs.py`, `scripts/hermes/discord_relay.py`, `tests/test_hermes_supervisor.py` (NEW)
**Depends:** T003, T004
On watchdog/job events, capture a bounded pane excerpt once and ask the requester in Discord for input. Route replies in the job's Discord thread back to the pending prompt, then send exactly the user's reply to tmux. Record pane digest, normalized prompt features, user's answer, sent text, job context, and observed outcome. Add data structures for future learned patterns, but do not hardcode `/new`, handoff ingestion, `continue`, or any other initial reply.
**Tests:** `/new`, handoff, continuation, cost, destructive, credential, and ambiguous prompts all ask the user and send no keys before reply; a reply in the job thread correlates to the pending prompt and sends exactly that reply to tmux; unrelated thread replies are ignored or treated as new commands; duplicate pane digest does not spam repeated asks.
**Acceptance:** Hermes starts lenient and user-directed: every prompt asks first, Discord replies resume pending prompts, and learning data is captured for later automation.
**Complexity:** high

## T006 — Stale/dead session checkups  [ ]
**Files:** `scripts/hermes/supervisor.py`, `scripts/hermes/so_jobs.py`, `tests/test_hermes_supervisor.py`
**Depends:** T003, T005
Detect missing tmux sessions, dead pids, unchanged pane digest after watchdog alert, and stale job heartbeat/progress. Transition job to `stale` or `dead` and post Discord checkup with attach/restart/abort options. Implement handlers for explicit attach, abort, and restart selections; do not auto-restart by default.
**Tests:** missing tmux marks dead; dead pid marks dead; unchanged digest after threshold posts checkup once; live changing pane remains running; attach returns connection/command guidance for the recorded execution host; abort terminates tmux and marks the job aborted; explicit restart creates a new tmux session and updates registry state; restart is never executed automatically.
**Acceptance:** Hermes notices sessions that need checkup without blind polling loops.
**Complexity:** medium

## T007 — z-harness watchdog payload fields for Hermes routing  [ ]
**Files:** `scripts/notify-watchdog.sh`, `scripts/hang-check.sh`, `scripts/test_notify_watchdog.sh`, `tests/test_hang_check.py`
**Depends:** none
Ensure Hermes webhook payloads carry `event`, `event_id`, `job_id` for supervised `so` sessions, `run_id` when known, `slug` when known, `pid` when known, `severity`, and `reason`; `next_step` is optional. Preserve best-effort/fail-open behavior. Add tests that the Hermes payload is valid JSON, has a unique event id, includes routing fields, and never logs secrets/webhook URLs.
**Tests:** `bash scripts/test_notify_watchdog.sh`; `python3 -m pytest tests/test_hang_check.py -q`.
**Acceptance:** z-harness watchdog alerts are actionable inputs to Hermes.
**DOCS:** watchdog
**Complexity:** medium

## T008 — Fix existing schedule-hang-check test/script contract  [ ]
**Files:** `scripts/schedule-hang-check.sh`, `tests/test_schedule_hang_check.py`
**Depends:** none
Resolve the current mismatch where `test_label_sanitized_into_plist` expects invalid run ids to sanitize and succeed, while the script rejects invalid `--run` with exit 2. Keep strict run-id validation; update the test to cover label behavior without invalid run ids.
**Tests:** `python3 -m pytest tests/test_schedule_hang_check.py -q`.
**Acceptance:** watchdog scheduling tests are green before Hermes depends on the notifier path.
**Complexity:** low

## T009 — Fake Discord/tmux/OMP end-to-end harness  [ ]
**Files:** `tests/test_hermes_so_e2e.py` (NEW), `hermes-so-watchdog/TESTS.md`
**Depends:** T001, T002, T003, T004, T005, T006, T007, T008
Build an end-to-end test with fake Discord message intake, fake tmux runner, fake OMP pane output, fake watchdog webhook, and supervisor ask/reply flow. Cover feedback recording, Discord thread reply routing, watchdog thread resumption/subscription fallback, stale/dead paths, and explicit attach/abort/restart checkup actions.
**Tests:** `python3 -m pytest tests/test_hermes_so_e2e.py tests/test_hermes_supervisor.py tests/test_hermes_watchdog_webhook.py -q`.
**Acceptance:** maintainers can test the whole story without real Discord/OMP, then manually dogfood with a real Discord command.
**Complexity:** high

## T010 — Pattern mining, review, and promotion  [ ]
**Files:** `scripts/hermes/supervisor.py`, `scripts/hermes/so_jobs.py`, `tests/test_hermes_supervisor.py`
**Depends:** T005, T009
Mine recorded prompt/answer/outcome data for repeated successful patterns. Produce candidate reply rules for human review, support explicit promotion/demotion, and require promoted rules to be auditable and reversible. This is the first task allowed to introduce learned automatic replies; it must not seed hardcoded `/new`, handoff, or `continue` rules.
**Tests:** repeated matching feedback produces a candidate but sends no automatic reply before promotion; promoted candidate can answer a matching prompt; demoted/revoked candidate stops answering; negative examples do not match; every learned reply records candidate id and source evidence.
**Acceptance:** learning is planned as a separate reviewed promotion path, not implied by raw feedback capture.
**Complexity:** high

## T011 — Docs and generated exports  [ ]

**Files:** `docs/human/hermes-orchestration.md`, `docs/human/watchdog.md`, `docs/human/commands.md`, `docs/llm/hermes-orchestration.json`, `docs/llm/watchdog.json`, `docs/llm/INDEX.json`, generated export trees from existing exporters
**Depends:** T001, T003, T004, T005, T006, T007, T009, T010
Document the Discord `so` command, job registry, tmux ownership, watchdog webhook flow, ask-first prompt handling, feedback capture, pattern mining/review/promotion, stale/dead checkups, and manual test procedure. Refresh two-tier docs and generated exports via existing workflows; do not hand-edit generated exports.
**Tests:** repo doc validation/export audit commands used for z-harness release checks.
**Acceptance:** docs describe the intended Hermes behavior and no longer frame blind `sleep && capture-pane` as normal supervision.
**Complexity:** medium

---

### Dependency summary

- Discord intake: T001 → T002 → T003.
- Watchdog loop: T002 + T007/T008 → T004 → T005 → T006.
- End-to-end proof: T001–T008 → T009.
- Learning: T005 + T009 → T010.
- Docs/exports last: T011.
