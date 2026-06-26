# TESTS — Hermes Discord `so` session orchestration

## Automated gates by area

### z-harness watchdog substrate

```bash
python3 -m pytest tests/test_hang_check.py tests/test_schedule_hang_check.py tests/test_hang_threshold.py -q
bash scripts/test_notify_watchdog.sh
```

Expected coverage:

- Scheduled hang check tests are green.
- `notify-watchdog.sh` Hermes webhook payload carries fields Hermes needs: `event`, `event_id`, `job_id` for supervised `so` sessions, `run_id` when known, `slug` when known, `pid` when known, `severity`, and `reason`; `next_step` is optional.
- Watchdog remains fail-open and does not leak webhook URLs/secrets.

Known pre-plan failure to fix first:

```bash
python3 -m pytest tests/test_hang_check.py tests/test_schedule_hang_check.py tests/test_hang_threshold.py -q
```

Observed result before this plan: 17 passed, 1 failed.

Failure:

- `tests/test_schedule_hang_check.py::TestSchedule::test_label_sanitized_into_plist`
- Script rejects invalid `--run "weird/run id"` with exit 2; test expected sanitization and success.

Plan decision: keep strict run-id validation and update the test.

### Hermes command/registry/supervisor units

```bash
python3 -m pytest \
  tests/test_hermes_discord_relay.py \
  tests/test_hermes_so_jobs.py \
  tests/test_hermes_session.py \
  tests/test_hermes_watchdog_webhook.py \
  tests/test_hermes_supervisor.py -q
```

Expected coverage:

- `so omp qt-bot fix blah using z-debug` parses into host/project/task/z-command.
- Unauthorized Discord users/channels are rejected.
- Job records are written before tmux send-keys.
- Fake tmux command runner sees generated session name, not user-provided `so-session`.
- Watchdog event maps to the correct job, resumes the original Discord thread, and dedups repeat events; subscription fallback is covered when thread reconstruction is unavailable.
- Prompt handler asks the requester for `/new`, handoff, continuation, ambiguous, destructive, cost, and credential prompts.
- No tmux input is sent before the requester replies.
- Discord replies in the job thread resume the pending prompt; unrelated thread replies do not.
- Missing tmux/dead pid/unchanged pane digest produce stale/dead checkups.
- Explicit attach, abort, and restart checkup actions update tmux/job state; restart is never automatic.

### End-to-end fake harness

```bash
python3 -m pytest tests/test_hermes_so_e2e.py -q
```

Fake scenario:

1. Fake Discord message: `so omp qt-bot fix blah using z-debug`.
2. Hermes parses and authorizes it.
3. Hermes writes a job record.
4. Hermes fake-tmux creates `hermes-so-<job-id>` and sends the initial OMP prompt.
5. Fake watchdog webhook says the run is stalled.
6. Hermes routes the event back into the original fake Discord thread, or through the owning fake Discord session's watchdog subscription fallback.
7. Hermes captures one bounded pane excerpt.
8. Hermes asks the requester for input in that same thread/session.
9. Fake requester reply is routed from the Discord thread to tmux and recorded as feedback.
10. Explicit stale/dead checkup actions are exercised for attach, abort, and restart.

The fake e2e must not contact real Discord, real OMP, real tmux, or real project repos.

`tests/test_hermes_so_e2e.py` is the local/fake harness for this path.

## Manual dogfood — real Discord path

Prereqs:

- Hermes Discord bot is running in a test Discord channel.
- The requester is authorized in Hermes config.
- Project alias exists, e.g. `qt-bot` → repo/remote/workdir.
- `notify.hermes_webhook_url` points at the Hermes webhook receiver.
- Watchdog thread resumption has been tested. If it fails in the target Discord deployment, enable/use the Discord-session subscription fallback instead of detached webhook alerts.
- Use a disposable branch/repo first.

### Launch from Discord

Send:

```text
so omp qt-bot fix a harmless test issue using z-debug
```

Pass criteria:

- Hermes replies with a job id and generated tmux session name only as diagnostic detail.
- Hermes creates the tmux session.
- Hermes records the job.
- OMP receives a prompt that includes the task and tells it to use `z-debug`.
- User does not type a tmux command.

### Ask-first prompt test

Force or wait for any prompt, including prompts that seem obvious such as:

- `/new` required to start a clean session.
- Handoff/context ingestion prompt.
- Plain continuation prompt after tool output.

Pass criteria:

- Watchdog or explicit check causes Hermes to inspect the pane once.
- Hermes asks the requester in Discord.
- Hermes sends no input before the requester replies.
- Job log records pane digest, prompt features, user reply, and outcome for future pattern mining.

### Ask-user prompt test

Force or wait for a prompt involving cost, destructive action, permissions, credentials, or an unclear decision.

Pass criteria:

- Hermes mentions the requester in Discord.
- Hermes includes a bounded pane excerpt and options.
- Hermes sends no tmux input before the user replies.

### Stale/dead checkup test

Kill the tmux session or fake a dead pid for the job.

Pass criteria:

- Hermes marks job `dead` or `stale`.
- Hermes posts a checkup with restart/attach/abort options.
- Hermes does not auto-restart by default.

## Final acceptance

The plan is complete only when both are true:

1. Fake automated e2e proves message → tmux → registry → watchdog → ask-first reply routing → feedback capture behavior.
2. A maintainer has run the Discord dogfood flow, or the final report explicitly states which real dependency was unavailable and cites the fake e2e as the completed substitute.
