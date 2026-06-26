# SPEC — Hermes Discord `so` session orchestration

## Overview

Target user story:

> A user opens a Hermes session in Discord and says something like `so omp qt-bot fix blah using z-debug`. Hermes creates the tmux session, registers the job, and supervises it. Watchdog tells Hermes when OMP needs input. At first Hermes asks the user for every input and records the user's answer. Over time, Hermes learns repeatable patterns from that feedback and may suggest future automation, but it does not start with hardcoded replies. Hermes also watches for stale or dead sessions that need checkup.

This plan is **not** about adding a local `so` binary or z-harness CLI alias. `so` lives in the Hermes gateway / Discord layer as command language plus job lifecycle. z-harness changes are limited to watchdog/liveness payloads that make Hermes supervision actionable without blind `sleep && tmux capture-pane` polling.

## User-facing problem

1. The user wants to drive long OMP/Claude sessions from Discord in plain language, not operate tmux directly.
2. Hermes currently has a Discord question relay for halted workstreams, but not a Discord command gateway that starts and supervises `so ...` jobs.
3. Watchdog can notify via `notify.hermes_webhook_url`, but Hermes does not yet consume those notifications as job state and decide whether to auto-respond, ask the user, or mark a session stale/dead.
4. Tmux capture is necessary for interactive TUI control, but blind periodic capture (`sleep 60 && tmux capture-pane ...`) should not be the orchestration loop.

## Ownership boundary

### Hermes owns

- Discord command intake: parse messages such as `so omp qt-bot fix blah using z-debug`.
- Job registry: map Discord thread/message ↔ tmux session ↔ process pid ↔ z-harness run id ↔ project/worktree ↔ execution host.
- Tmux lifecycle: create, attach/capture on demand, send keys, terminate, clean up on the recorded execution host.
- Initial supervisor policy: ask the requester for every prompt, route replies back to pending jobs, and record feedback. Automatic replies belong only to a later promoted learned-pattern path with an explicit review gate.
- Consumption of watchdog webhooks from z-harness.

### z-harness owns

- Watchdog event production and notification delivery (`hang-check.sh`, `notify-watchdog.sh`, `liveness.sh`).
- Emitting enough lifecycle/progress events for OMP/z-debug/z-* sessions so watchdog alerts carry actionable `run_id`, `slug`, `pid`, `next_step`, and reason.
- Tests for the shell watchdog path and notification payload shape.
- Documentation of the Hermes webhook contract.

## Goals

1. **Discord-first `so` command:** user can launch a supervised job with one Discord message.
2. **No user tmux names:** Hermes generates tmux session names and shows a friendly job id/status in Discord.
3. **Structured job registry:** Hermes registers every job before sending the first prompt into tmux.
4. **Watchdog-to-Hermes loop:** watchdog notifications become Hermes job events, not just human alerts.
5. **Ask-first input handling:** Hermes asks the user for session input by default, records the prompt/answer/outcome, and learns candidate patterns over time from feedback. Automation is introduced only after observed, approved patterns exist.
6. **Stale/dead supervision:** Hermes detects dead tmux/process state, stale prompts, and sessions with no progress and asks for or performs checkup.
7. **Test by using it:** provide a fake Discord/fake OMP harness and a manual dogfood flow from Discord.

## Non-goals

- Do not make Hermes resolve arbitrary product decisions without user approval.
- Do not remove tmux. Interactive OMP/Claude TUI control still needs tmux or equivalent PTY ownership.
- Do not make watchdog kill native TUI sessions. It detects and notifies; Hermes may choose a safe recovery action.
- Do not make `capture-pane` forbidden. It is allowed when triggered by an event, status check, or user command; it is not allowed as blind token-consuming polling.
- Do not replace existing z-harness `/z-debug`; the user phrase `using z-debug` means Hermes prompts OMP to run the appropriate z-harness command inside the supervised session.

## Command contract

Initial grammar, intentionally small:

```text
so <host> <project> <task...> [using <z-command>]
```

Examples:

```text
so omp qt-bot fix the missing fills using z-debug
so claude z-harness inspect watchdog failures using z-debug
```

Parsed fields:

```json
{
  "host": "omp",
  "project": "qt-bot",
  "task": "fix the missing fills",
  "z_command": "z-debug"
}
```

Hermes resolves `project` through configured project aliases. For remote projects such as `qt-bot`, Hermes uses the existing project/host rule set for where the session must run.

## Job registry contract

Hermes persists a job record, e.g. `~/.hermes/so-jobs/<job_id>.json` or the repo's configured Hermes state root:

```json
{
  "schema_version": 1,
  "job_id": "so-20260626-abc123",
  "discord_channel_id": "...",
  "discord_message_id": "...",
  "discord_thread_id": "...",
  "requester_user_id": "...",
  "host": "omp",
  "project": "qt-bot",
  "repo_root": "/abs/or/remote/ref",
  "execution_host": "local|zeke-pc",
  "transport": "local|ssh",
  "ssh_target": "zeke-pc",
  "workdir": "/abs/workdir/on/execution_host",
  "z_command": "z-debug",
  "task": "fix the missing fills",
  "tmux_session": "hermes-so-20260626-abc123",
  "pid": 12345,
  "z_harness_run_id": "...",
  "status": "starting|running|waiting_input|asking_user|stale|dead|done|failed",
  "last_pane_digest": "sha256:...",
  "last_progress_at": "ISO",
  "last_watchdog_event_id": "..."
}
```

The registry is Hermes-owned. z-harness active-plan registry remains separate and continues to track z-harness runs.

`execution_host` and `transport` are authoritative for tmux, pid, capture, send-keys, attach, restart, and abort operations. A local pid or tmux session name is never interpreted on a different host.

## Watchdog webhook contract

`notify-watchdog.sh` already sends a platform-neutral payload to `notify.hermes_webhook_url`. Extend or document it so Hermes can route alerts to jobs:

Required fields:

- `event`: `watchdog_stall` or `watchdog_timeout`
- `event_id`: unique id for dedup
- `job_id`: Hermes job id for supervised `so` sessions
- `run_id`: z-harness run id when known
- `slug`: plan/debug slug when known
- `pid`: process id when known
- `severity`: `warning|error`
- `reason`: human-readable message

Optional fields:

- `next_step`: suggested action, if producer has one

Hermes maps webhook payloads to jobs by `job_id`, `run_id`, `pid`, or slug, then resumes the original Discord thread from the stored `discord_channel_id` / `discord_thread_id` / `discord_message_id`. Unknown events are posted to an ops channel but do not mutate a job record.

For Hermes-supervised sessions, `job_id` is mandatory. Hermes exports `HERMES_SO_JOB_ID=<job_id>` into the launched tmux session; z-harness watchdog notification code must propagate it into the Hermes webhook payload. If a legacy run lacks `job_id`, Hermes may try `run_id`, `pid`, or slug as fallback, but those are not sufficient for the supervised `so` contract.

### Watchdog thread resumption / subscription fallback

The implementation must prove that a watchdog event can resume the correct Discord thread. The job registry is the source of truth for Discord routing: channel id, thread id if present, message id, and requester id. If a watchdog payload cannot reliably resume that thread, Hermes must not post detached alerts and hope the user connects them manually. Instead, the active Discord session subscribes to watchdog/job events for its jobs and invokes the same supervisor check path locally.

Acceptance for either model:

- Webhook model: payload → job lookup → original Discord thread message with requester mention.
- Subscription model: Discord session registers interest in job/run ids and receives watchdog/job events without relying on thread reconstruction from an external webhook.

## Supervisor policy

Hermes should classify a waiting session into one of these categories:

1. **Ask-user default:** every waiting prompt initially routes to the requester in Discord with a bounded pane excerpt and suggested reply field. Hermes sends no input until the user answers.
2. **Learning record:** after the user replies, Hermes stores the pane digest, normalized prompt features, user answer, job context, and outcome. Repeated successful answers become candidate patterns for a later mining/review task.
3. **Candidate automation deferred:** learned patterns may eventually suggest an automatic reply, but only after enough matching feedback and an explicit promotion step in a separate future phase. The initial implementation must not hardcode `/new`, handoff ingestion, or `continue` as replies.
4. **Stale/dead:** tmux session missing, pid dead, pane unchanged across configured checks after watchdog alert, or z-harness record stale.
   - Action: post checkup; offer restart/attach/abort; only auto-restart if a task-specific policy explicitly allows it.

Prompt classification must be conservative. If there is no promoted learned pattern, ask the user.

## Invariants

1. **No blind token polling.** Hermes must not run fixed `sleep N && tmux capture-pane ...` loops as its primary progress mechanism. Captures are event-driven: launch confirmation, watchdog alert, user `status/logs`, or bounded stale check.
2. **Every job is registered before first prompt.** If registry write fails, Hermes refuses to launch and tells Discord.
3. **Every user answer is logged.** Store pane digest, prompt features, user reply, sent text, and observed outcome.
4. **Ask when unsure, and initially always ask.** If no promoted learned pattern exists, mention the requester instead of guessing.
5. **Webhook dedup is mandatory.** Same `event_id` or same `(job_id, event, reason)` within a dedup window must not spam Discord or send duplicate inputs.
6. **z-harness remains fail-open.** If Hermes webhook delivery fails, watchdog still exits 0 and other channels still work.
7. **Tests use fake Discord and fake tmux/OMP.** Automated tests must not hit real Discord, real OMP, or real project repos.

## Acceptance criteria

- A fake Discord message `so omp qt-bot fix blah using z-debug` creates one Hermes job record and one tmux session command with a generated name.
- The initial prompt sent to OMP contains the user's task and `z-debug` instruction.
- A fake watchdog event for that job either resumes the original Discord thread or is delivered through the Discord session subscription fallback, then causes Hermes to capture the pane once and ask the requester for input.
- User replies are recorded with prompt features, answer, and outcome for future learning.
- No initial prompt, including `/new`, handoff-ingest, or `continue`, is answered automatically without a learned/promoted pattern.
- Dead tmux session / dead pid transitions job to `dead` and posts a checkup.
- z-harness watchdog tests prove `notify-watchdog.sh` payloads contain fields Hermes needs.
- Manual dogfood from Discord is documented and runnable.
