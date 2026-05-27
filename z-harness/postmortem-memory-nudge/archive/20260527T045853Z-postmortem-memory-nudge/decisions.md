# Phase 2 — Decisions

## D1. Where does the four-state terminal taxonomy get computed?
- **Options:**
  - **A. In `run-memory-review.sh`** — emit a single `memory_review_terminal` event with `state: not_applicable|skipped_broken_context|ran_empty|needs_user` *before* exiting. Orchestrator post-dispatch states (`ran_empty`, `needs_user`) are emitted by the SKILL.md callers.
  - B. Entirely in the SKILL.md callers (orchestrator) — keep helper dumb, parse STATUS, map.
- **Tentative call:** A. The helper already owns skip-condition logic; concentrate state classification there. SKILL.md callers still emit `ran_empty`/`needs_user` for the post-dispatch states the helper can't see.
- **Consult? YES.** Trigger: defines a wire-format / event-shape on a public surface (consumed by `/z-stats`, `/z-improve`, future tooling); hard to rename later.

## D2. Event shape for the terminal state
- **Options:**
  - **A. New `memory_review_terminal` event** with payload `{state, skip_reason?, parent_command, candidates?, accepted?}`. Coexists with existing `phase_end`, `review_agent_failed`, `review_agent_malformed`, `memory_candidates_ready`.
  - B. Repurpose `phase_end` and add a `terminal_state` field.
- **Tentative call:** A. `phase_end` is a generic phase telemetry event used across all phases; overloading it with memory-review-specific semantics breaks `/z-stats` Phase 4b parsing. A dedicated event is clearer and self-documenting.
- **Consult? YES.** Trigger: event-shape on a public surface; affects every downstream consumer of metrics.jsonl.

## D3. Fix the `tags_missing` mis-classification
- **Options:**
  - **A. Reclassify as `skipped_broken_context`** (the correct semantic) and stop emitting `review_agent_failed` for it.
  - B. Leave `review_agent_failed` for backward-compat.
- **Tentative call:** A. The mis-classification is a confirmed bug (helper says "agent failed" when agent was never dispatched). Backward-compat doesn't apply — nothing consumes this event yet in a way that depends on the wrong shape.
- **Consult? NO.** Bug fix with root cause already identified.

## D4. Should `no_plan_dir` and `missing_args` halt or skip?
- **Options:**
  - A. Halt parent command (Phase 9 / Phase 7) — these are programming errors in the caller.
  - **B. Continue silent-skip but emit the terminal event** so they show up in `/z-stats`.
  - C. Promote `no_plan_dir` to halt only when called from `/z-implement-all` (which should always have set it); keep `missing_args` as a defensive skip.
- **Tentative call:** B. The whole point of this plan is observability. Halting the parent command (which has already finished its primary work) for a memory-review env bug would be hostile. The visibility comes from the new event, not from halting.
- **Consult? NO.** Reversible / matches existing soft-skip pattern.

## D5. Should `/z-debug` post-mortem dispatch the review-agent?
- **Options:**
  - **A. YES — add Phase 9b in `skills/z-debug/SKILL.md`** that calls `run-memory-review.sh "$RUN" "debug"` after the Post-mortem section is written, then dispatches review-agent with DEBUG.md added to its input set.
  - B. NO — keep `/z-debug` post-mortem narrative-only, surface via separate `/z-suggest-memory` recommendation push-notify.
- **Tentative call:** A. /z-debug post-mortems contain the densest memory signal in the whole harness (root cause, why we didn't catch it, action items). Not dispatching the review-agent there is leaving signal on the floor.
- **Consult? YES.** Trigger: cross-module change (review-agent + run-memory-review.sh + skills/z-debug/SKILL.md); affects parent_command enum (new value `debug`); algorithmic choice (do we feed DEBUG.md sections separately or as a single artifact?).

## D6. Should `run-memory-review.sh` learn `debug` parent_command, or do we make a sibling helper?
- **Options:**
  - **A. Extend `run-memory-review.sh`** with `parent_command: debug` — skip-conditions adjust (no TASKS.md `[x]` check; instead require DEBUG.md `status: shipped`).
  - B. Create `run-debug-memory-review.sh` as a separate helper.
- **Tentative call:** A. DRY. The skip-condition logic, diff prep, and artifact-path emission are identical; only one skip-rule differs.
- **Consult? NO.** Following existing convention (single helper handles two parents; trivially extensible to three).

## D7. Where does the review-agent prompt change to accept DEBUG.md as input?
- **Options:**
  - **A. Add an optional `debug_md_path` field** in the agent's input contract ([agents/review-agent.md](agents/review-agent.md)). Agent reads it as additional context when present.
  - B. Replace `spec_path` with `debug_md_path` when parent_command == debug.
- **Tentative call:** A. Optional additive field. Doesn't break the existing implement-all / review-all callers and gives the agent a structured signal that this run is a debug post-mortem.
- **Consult? YES.** Trigger: changes a subagent input contract (public surface).

## D8. Smoke-test `/z-improve` → `/z-suggest-memory` end-to-end
- **Options:**
  - **A. Manual smoke-test instruction** in a final task — run `/z-improve` on the postmortem-memory-nudge slug after the implementation finishes, confirm `suggest_memory_called` event lands.
  - B. Automated test (would require harness-level test infrastructure that doesn't exist yet).
- **Tentative call:** A. The wiring is already correct (line 163-209); we just need confirmation it fires.
- **Consult? NO.** Mechanical verification step.

## D9. qt-bot remote check
- **Options:**
  - **A. New task uses `qt-bot-remote` skill** to SSH to zeke-pc and check `ls ~/dev/qt-bot/docs/llm/INDEX.json && ls ~/dev/qt-bot/docs/llm/TAGS.txt`. If absent, recommend `/z-init-docs` on remote (manual user action — we don't init the remote from a planning run).
  - B. Bake the check into `run-memory-review.sh` as a remote-aware probe.
- **Tentative call:** A. Single-run verification task, not a per-run runtime probe. B would massively expand the helper's scope.
- **Consult? NO.** Mechanical SSH probe.

## D10. Should the new `memory_review_terminal` event be surfaced in `/z-stats` Phase 4b?
- **Options:**
  - **A. YES — add a section that groups runs by terminal state** and shows the count distribution (e.g. "Last 10 runs: 4 needs_user / 2 ran_empty / 3 not_applicable / 1 skipped_broken_context").
  - B. NO — leave `/z-stats` unchanged; users grep metrics.jsonl directly.
- **Tentative call:** A. This is the *whole point* of the plan — make Phase 9's behavior visible. Burying it behind manual jq queries undoes the work.
- **Consult? NO.** Following established `/z-stats` Phase 4b extension pattern.

## D11. Default behavior when memory_review_terminal == `skipped_broken_context`
- **Options:**
  - **A. Push-notify the user once per run with the specific reason** — they're more likely to act on a visible breakage than a silent one.
  - B. Silent but logged (status quo for most skip states).
  - C. Same as A but only for `no_plan_dir`/`missing_args` (env bugs); silent for `tags_missing` (recoverable via `/z-init-docs`).
- **Tentative call:** A. Codex framing demands visibility. Push-notify is cheap; user can mute later if it's annoying.
- **Consult? YES.** Trigger: notification-policy decision affecting every Phase 9 run; reversibility moderate (changing later may train users to ignore notifications, repeating the original failure mode).

## D12. Auto-apply the four-state vocabulary retroactively to existing logged events?
- **Options:**
  - A. YES — write a migration script that maps old `phase_end{skip_reason}` and `review_agent_failed{reason:tags_missing}` events to synthetic `memory_review_terminal` events.
  - **B. NO — emit going forward only; `/z-stats` Phase 4b reads both old and new event shapes.**
- **Tentative call:** B. The historical metrics.jsonl is small (most events are recent), and a synthetic-event migration introduces a different shape of confusion ("did this event come from a real run or a migration script?"). `/z-stats` can handle both old and new with a few extra lines.
- **Consult? NO.** Reversible; cheap to revisit.

---

## Consult-flagged decisions (5/5 within hard cap)
- D1 — where to compute terminal state
- D2 — event shape
- D5 — wire `/z-debug` to review-agent
- D7 — agent input contract change (`debug_md_path`)
- D11 — push-notify on broken context

## Obvious decisions (no consult)
- D3, D4, D6, D8, D9, D10, D12
