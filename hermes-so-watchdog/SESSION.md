# SESSION — Hermes Discord `so` session orchestration

## Status

Ready for execution in a clean session.

Plan artifacts:

- `hermes-so-watchdog/SPEC.md`
- `hermes-so-watchdog/PLAN.md`
- `hermes-so-watchdog/TASKS.md`
- `hermes-so-watchdog/TESTS.md`
- `hermes-so-watchdog/handoff.json`

## User story

A user opens a Hermes session in Discord and sends:

```text
so omp qt-bot fix blah using z-debug
```

Hermes creates a tmux-backed OMP/Claude job, registers it, sends the initial instruction, consumes watchdog events, asks the requester for input by default, records feedback, and detects stale/dead sessions. The user should not type or remember tmux session names.

## Non-negotiable constraints

- `so` lives in the Hermes gateway / Discord layer. It is not a z-harness CLI or local binary.
- Hermes generates internal tmux names such as `hermes-so-<job-id>`; no user-provided `so-session` interface.
- No blind fixed `sleep N && tmux capture-pane ...` orchestration loops. Captures are event-driven: launch confirmation, watchdog alert, explicit status/log request, or bounded stale check.
- Initial behavior is ask-first. Hermes sends no session input until the requester replies.
- Do not hardcode `/new`, handoff ingestion, `continue`, or other seed replies.
- Learning automation is deferred to explicit pattern mining/review/promotion after the ask-first loop and fake e2e work.
- For supervised `so` jobs, watchdog routing needs `job_id`; Hermes exports `HERMES_SO_JOB_ID=<job_id>` into the launched session.
- `next_step` is optional webhook metadata.
- Hermes job records must include execution host/transport/workdir fields; tmux and pid operations happen on the recorded host.
- Automated tests use fake Discord and fake tmux/OMP only.

## Current plan shape

Implementation tasks are in `hermes-so-watchdog/TASKS.md`.

Recommended execution waves:

1. `T001`, `T007`, `T008` can start first.
2. `T002` after `T001`.
3. `T003` after `T001` + `T002`; `T004` after `T002` + `T007` + `T008`.
4. `T005` after `T003` + `T004`.
5. `T006` after `T003` + `T005`.
6. `T009` after `T001` through `T008`.
7. `T010` after `T005` + `T009`.
8. `T011` last.

## Task summaries

### T001 — Hermes Discord `so` command parser and authorization

Files: `scripts/hermes/discord_relay.py`, `scripts/hermes/config.py`, `tests/test_hermes_discord_relay.py`.

Parse `so <host> <project> <task...> [using <z-command>]`; authorize requester/channel; resolve project aliases; preserve task text. No process launch in this task.

### T002 — Hermes job registry for Discord/tmux sessions

Files: `scripts/hermes/so_jobs.py`, `scripts/hermes/config.py`, `tests/test_hermes_so_jobs.py`.

Durable Hermes-owned job records with Discord ids, requester, host/project, repo/worktree, execution host/transport/SSH target/workdir, z-command, task, tmux session, pid, z-harness run id, status, pane digest, progress timestamp, and watchdog event id. Atomic writes. Lookup by job id, run id/pid, slug, Discord message/thread.

### T003 — Tmux launcher for Hermes `so` jobs

Files: `scripts/hermes/session.py`, `scripts/hermes/so_jobs.py`, `tests/test_hermes_session.py`.

Create generated tmux session, launch host in resolved project, send initial instruction containing task and requested z-command, register before first send-keys, mark failures.

### T004 — Hermes watchdog delivery and Discord thread resumption

Files: `scripts/hermes/watchdog_webhook.py`, `scripts/hermes/so_jobs.py`, `tests/test_hermes_watchdog_webhook.py`.

Accept signed `notify-watchdog.sh` payload, validate HMAC when configured, dedup by `event_id`, map by `job_id` / `run_id` / `pid` / slug, and prove original Discord thread resumption. If thread resumption cannot be proven, implement Discord-session subscription fallback.

### T005 — Ask-first prompt handling and feedback capture

Files: `scripts/hermes/supervisor.py`, `scripts/hermes/so_jobs.py`, `scripts/hermes/discord_relay.py`, `tests/test_hermes_supervisor.py`.

On watchdog/job event, capture bounded pane excerpt once, ask requester in Discord, route reply in job thread back to pending prompt, send exactly that reply to tmux, and record pane digest/prompt features/user answer/sent text/job context/outcome. No hardcoded initial replies.

### T006 — Stale/dead session checkups

Files: `scripts/hermes/supervisor.py`, `scripts/hermes/so_jobs.py`, `tests/test_hermes_supervisor.py`.

Detect missing tmux, dead pid, unchanged pane digest after watchdog alert, stale heartbeat/progress. Mark `stale`/`dead`; post attach/restart/abort options. Implement explicit handlers. No auto-restart.

### T007 — z-harness watchdog payload fields for Hermes routing

Files: `scripts/notify-watchdog.sh`, `scripts/hang-check.sh`, `scripts/test_notify_watchdog.sh`, `tests/test_hang_check.py`.

Ensure Hermes webhook payload includes `event`, `event_id`, `job_id` for supervised `so`, `run_id` when known, `slug` when known, `pid` when known, `severity`, `reason`; `next_step` optional. Keep fail-open and secret-safe.

### T008 — Fix existing schedule-hang-check test/script contract

Files: `scripts/schedule-hang-check.sh`, `tests/test_schedule_hang_check.py`.

Known pre-plan failure: `test_label_sanitized_into_plist` expects invalid `--run "weird/run id"` to sanitize and succeed, while script rejects invalid run ids with exit 2. Keep strict run-id validation; update the test.

### T009 — Fake Discord/tmux/OMP end-to-end harness

Files: `tests/test_hermes_so_e2e.py`, `hermes-so-watchdog/TESTS.md`.

Fake message → parse/authorize → job record → fake tmux launch → fake watchdog webhook → thread/subscription routing → bounded pane capture → ask requester → fake reply to tmux → feedback recorded. Cover stale/dead attach/abort/restart paths.

### T010 — Pattern mining, review, and promotion

Files: `scripts/hermes/supervisor.py`, `scripts/hermes/so_jobs.py`, `tests/test_hermes_supervisor.py`.

Mine repeated successful prompt/answer/outcome data into candidate reply rules; require human review/promotion; support demotion/revocation; record candidate id/source evidence. This is the first task allowed to send learned automatic replies.

### T011 — Docs and generated exports

Files: `docs/human/hermes-orchestration.md`, `docs/human/watchdog.md`, `docs/human/commands.md`, `docs/llm/hermes-orchestration.json`, `docs/llm/watchdog.json`, `docs/llm/INDEX.json`, generated export trees.

Update docs after implementation. Do not hand-edit generated exports; use existing export/doc workflows.

## Verification plan

Run targeted gates as tasks land:

```bash
python3 -m pytest tests/test_hang_check.py tests/test_schedule_hang_check.py tests/test_hang_threshold.py -q
bash scripts/test_notify_watchdog.sh
python3 -m pytest \
  tests/test_hermes_discord_relay.py \
  tests/test_hermes_so_jobs.py \
  tests/test_hermes_session.py \
  tests/test_hermes_watchdog_webhook.py \
  tests/test_hermes_supervisor.py -q
python3 -m pytest tests/test_hermes_so_e2e.py -q
```

Final acceptance requires either real Discord dogfood in a disposable channel/repo/project alias, or an explicit final note that the real dependency was unavailable and the fake e2e is the completed substitute.

## Known pre-plan failure

Command:

```bash
python3 -m pytest tests/test_hang_check.py tests/test_schedule_hang_check.py tests/test_hang_threshold.py -q
```

Observed before this plan: 17 passed, 1 failed.

Failure:

- `tests/test_schedule_hang_check.py::TestSchedule::test_label_sanitized_into_plist`
- Script rejects invalid `--run "weird/run id"` with exit 2; test expected sanitization and success.

Decision: keep strict run-id validation and update the test in T008.

## Prior review fixes already folded into artifacts

- Added `job_id` correlation and `HERMES_SO_JOB_ID` requirement.
- Added execution-host ownership fields for remote `qt-bot`/SSH cases.
- Clarified ask-first policy; no startup allowlist/auto-actions.
- Moved `next_step` to optional webhook fields.
- Added Discord thread resumption/subscription fallback requirement.
- Fixed T004 dependencies on T007/T008.
- Added Discord reply routing coverage to T005.
- Added attach/abort/restart action coverage to T006.
- Added T010 pattern mining/review/promotion.
- Fixed T009 artifact path to `hermes-so-watchdog/TESTS.md`.
- Fixed T007 test path to `scripts/test_notify_watchdog.sh`.
- Fixed TESTS final acceptance from auto/ask wording to ask-first reply routing.

## Start here in a clean session

1. Read `hermes-so-watchdog/SPEC.md`, `PLAN.md`, `TASKS.md`, `TESTS.md`, and `handoff.json`.
2. Implement `T001`, `T007`, and `T008` first if running in parallel; otherwise start with `T001`.
3. Preserve the constraints above exactly; especially ask-first behavior and no blind tmux polling.
4. Verify each task with its targeted tests before moving dependent work forward.
