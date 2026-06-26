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

### Hermes command/MCP backend units

```bash
python3 -m pytest \
  tests/test_hermes_discord_relay.py \
  tests/test_hermes_so_mcp.py \
  tests/test_hermes_so_e2e.py -q
```

Expected coverage:

- `so omp qt-bot fix blah using z-debug` parses into host/project/task/z-command.
- Unauthorized Discord users/channels are rejected.
- Accepted Discord commands call `hermes.mcp_hermes_orchestrator.start_so_session`.
- MCP start creates an internal tmux session with a stable session id.
- SSH aliases run tmux commands on the recorded host/workdir.
- Session metadata is persisted in `so-mcp-sessions.json`.
- `so_send` sends input to the same session; `so_read` captures output on demand and reports `needs_input`.
- Retired tmux/job-registry/supervisor/watchdog tests live under
  `tests/deprecated/` and skip by default.

### End-to-end fake harness

```bash
python3 -m pytest tests/test_hermes_so_e2e.py -q
```

Fake scenario:

1. Fake Discord message: `so omp qt-bot fix blah using z-debug`.
2. Hermes parses and authorizes it.
3. Hermes calls the MCP orchestrator backend.
4. The fake runner receives SSH-backed tmux `new-session` and `send-keys`
   commands for the configured project alias.
5. The initial MCP prompt contains the task and requested z-command.
6. A fake requester reply is sent through `so_send` to the same MCP session id.
7. `so_read` captures the pane on demand and records latest output/status.

The fake e2e must not contact real Discord, real OMP, real tmux, or real
project repos.

`tests/test_hermes_so_e2e.py` is the local/fake harness for this path.

## Manual dogfood — real Discord path

Prereqs:

- Hermes Discord bot is running in a test Discord channel.
- The requester is authorized in Hermes config.
- Project alias exists, e.g. `qt-bot` → repo/remote/workdir.
- `scripts/so-mcp-server.py` is registered where MCP clients need direct tools.
- Use a disposable branch/repo first.

### Launch from Discord

Send:

```text
so omp qt-bot fix a harmless test issue using z-debug
```

Pass criteria:

- Hermes replies with an MCP session id.
- The MCP state file contains that session id under the Hermes state root.
- The launched agent prompt includes the task and `z-debug`.
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
