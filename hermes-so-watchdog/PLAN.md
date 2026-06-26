# PLAN — Hermes Discord `so` session orchestration

## Goals

1. Let a Discord user launch work with `so omp qt-bot fix blah using z-debug`.
2. Have Hermes create and register the tmux-backed OMP/Claude session.
3. Route watchdog alerts back into Hermes as job events.
4. Start by asking the user for all session inputs, then learn repeatable patterns from feedback over time.
5. Detect stale/dead sessions and post checkups.

## Key decisions

- **`so` lives in the Hermes gateway / Discord layer.** It is not a z-harness CLI. The primary interface is the Discord message; z-harness only supplies watchdog/liveness signals that Hermes consumes.
- **Tmux is retained as transport.** OMP/Claude are interactive TUIs; Hermes owns tmux session creation and send-keys/capture. The fix is to make captures event-driven and bounded, not to remove tmux.
- **Watchdog notifies Hermes, not just humans.** `notify-watchdog.sh`'s Hermes webhook payload becomes an input to Hermes's supervisor loop.
- **Thread resumption is a first-class risk.** The preferred path is watchdog → Hermes webhook → Hermes resumes the original Discord thread from the job registry. If webhook delivery cannot reliably resume the thread, the Discord session must subscribe to watchdog/job events directly and perform its own checkups, rather than relying on an orphaned external alert.
- **Ask-user first; learning automation is a later phase.** Hermes initially asks the requester for every input and records prompt/answer/outcome data. Pattern mining, review, and promotion are explicitly deferred to a separate task after the ask-first loop works.
- **Hermes job registry is separate from z-harness active-plan registry.** Hermes tracks Discord/tmux/pid/job state; z-harness tracks z-* run state.

## Phased implementation

### Phase A — Hermes Discord command gateway

Extend Hermes Discord support from question relay to command intake. Parse `so <host> <project> <task...> [using <z-command>]`, resolve project aliases, authorize the requester/channel, and acknowledge with a generated job id. This phase does not need real OMP; tests use fake Discord messages and fake project alias config.

### Phase B — Hermes tmux job registry and launcher

Add a Hermes-owned job registry. For each accepted `so` command, create a tmux session with a generated name, launch the selected host in the resolved project, and send the initial instruction. Register job state before the first send-keys. Add status/checkup helpers that read the registry and verify tmux/pid liveness.

### Phase C — Watchdog webhook ingestion

Add a Hermes webhook receiver or polling adapter that accepts the signed `notify-watchdog.sh` Hermes payload. Validate HMAC when configured, dedup by `event_id`, map to job by run id / pid / slug / explicit job id, and prove Hermes can resume the original Discord thread from the job registry. If thread resumption cannot be proven for a payload/source, fall back to a Discord-session-owned subscription model where the active Discord session subscribes to watchdog/job events and triggers supervisor checks itself. Unknown events go to an ops channel without mutating a job.

### Phase D — Ask-first prompt handling and feedback capture

On watchdog/job events, capture a bounded pane excerpt once and ask the requester in Discord for the next input. Store pane digest, normalized prompt features, user's answer, job context, and outcome. This phase captures learning data only; it does not mine or promote automation.

### Phase E — Stale/dead session supervision

Add bounded stale checks triggered by watchdog alerts, explicit `status`, and scheduled checkups. Detect missing tmux sessions, dead pids, unchanged pane digests after a watchdog event, and stale z-harness records. Post checkups with restart/attach/abort options; no automatic restart unless a later policy explicitly allows it.

### Phase F — z-harness watchdog payload support

Adjust or document `notify-watchdog.sh` and related tests so Hermes receives all required routing fields: `event`, `event_id`, `job_id` for supervised `so` sessions, `run_id` when known, `slug` when known, `pid` when known, `severity`, and `reason`. `next_step` is optional. Keep failure best-effort. Add tests for Hermes webhook payload construction and dedup-safe ids.

### Phase G — End-to-end fake harness and manual dogfood

Build a fake Discord + fake tmux/OMP test path: message in, job registered, fake pane prompt, watchdog event, Hermes asks, user reply is sent to tmux, and feedback is recorded. Document a real Discord dogfood flow against a disposable repo/project alias.

### Phase H — Pattern mining/review/promotion (deferred automation)

After the ask-first loop is proven, mine recorded prompt/answer/outcome data for repeated successful patterns. Surface candidates for human review, promote approved patterns explicitly, and keep every promoted reply rule auditable and reversible. This phase is required before Hermes sends any learned automatic reply.

### Phase I — Docs and exports

Update Hermes orchestration and watchdog docs to describe Discord `so`, tmux ownership, watchdog event flow, ask-first input handling, feedback capture, deferred learning/promotion, stale/dead checkups, and manual testing. Refresh two-tier docs and generated exports through existing workflows.

## Ordering / dependencies

- A → B: commands must parse before jobs launch.
- B → C/E: webhook/checkup needs a registry to target.
- C → D: prompt handling is triggered only after C proves either webhook thread resumption or Discord-session watchdog subscription.
- F can run in parallel with A/B because it touches z-harness notification tests.
- G depends on A–F.
- H depends on D and G; no automation promotion happens before H.
- I last.

## Risk controls

- Ship with automation disabled because no learned patterns exist yet.
- HMAC validate Hermes webhook payloads before mutating jobs.
- Test Discord thread resumption explicitly; if it is unreliable, switch to the subscription model before implementing prompt handling.
- Capture only bounded pane excerpts; never dump entire sessions into Discord.
- Promote automation only in Phase H from observed user feedback plus explicit review; no seed reply rules.
- Keep watchdog delivery fail-open so z-harness runs are not broken by Hermes downtime.
