# TASKS — postmortem-memory-nudge

Target: 10-20 tasks. Actual: 12.

---

## T001 — Extend `run-memory-review.sh` to accept `parent_command: debug`
- **Files:** scripts/run-memory-review.sh
- **Depends on:** —
- **Acceptance:**
  - `parent_command: debug` is a recognized 3rd value alongside `implement-all` and `review-all`.
  - For `debug`: skip `all_tasks_skipped` check; instead check `[[ -r "$BASE/DEBUG.md" ]]` and emit `STATUS: skipped debug_md_missing` if not.
  - Existing `implement-all` and `review-all` behavior unchanged.
- **DOCS:** scripts
- **Complexity:** low

## T002 — Add 5th stdout line (DEBUG.md path) for debug parent + conditional spec_path
- **Files:** scripts/run-memory-review.sh
- **Depends on:** T001
- **Acceptance:**
  - For `parent_command: debug` and `STATUS: ready`, line 5 is the absolute path to DEBUG.md.
  - For all parents, line 3 emits an empty line if `$BASE/SPEC.md` does not exist (was previously unconditional path).
  - Lines 1-4 remain backward-compatible for `implement-all`/`review-all`.
- **DOCS:** scripts
- **Complexity:** medium

## T003 — Emit single `memory_review_terminal` event from helper, replace inconsistent emissions
- **Files:** scripts/run-memory-review.sh
- **Depends on:** T001
- **Acceptance:**
  - Every skip path emits exactly one `memory_review_terminal` event with payload `{state, skip_reason, parent_command, candidates: 0, accepted: 0, slug}`.
  - STATUS → terminal-state mapping from SPEC §`run-memory-review.sh` is implemented (`empty_diff`/`all_tasks_skipped`/`debug_md_missing` → `not_applicable`; `tags_missing`/`no_plan_dir`/`missing_args` → `skipped_broken_context`).
  - The previous `phase_end` + `review_agent_failed` emissions for these states are removed.
  - On `STATUS: ready`, the helper emits NO terminal event (orchestrator owns it after dispatch).
- **DOCS:** scripts
- **Complexity:** medium

## T004 — Update `agents/review-agent.md` input contract for `parent_command: debug`
- **Files:** agents/review-agent.md
- **Depends on:** —
- **Acceptance:**
  - `parent_command` enum extended with `debug`.
  - Optional `debug_md_path` field documented (absolute path; absent for `implement-all`/`review-all`).
  - Input contract explicitly states: "When `parent_command: debug`, `debug_md_path` is primary; `spec_path` is supplementary. Otherwise spec_path is primary and debug_md_path is unset."
  - Empty `spec_path` documented as "no SPEC available — treat the run as self-contained."
  - Candidate-generation guidance adds: "For `parent_command: debug`, filter for generalizable invariants and root-cause patterns; single-run patches are NOT memories."
- **DOCS:** review-agent, agents
- **Complexity:** low

## T005 — Orchestrator wiring: Phase 9 of `/z-implement-all` emits single terminal event after gate
- **Files:** skills/z-implement-all/SKILL.md
- **Depends on:** T003
- **Acceptance:**
  - Phase 9 parses helper stdout with `mapfile -t LINES`.
  - On `STATUS: ready`, after review-agent dispatch and AskUserQuestion gate (if any), Phase 9 emits exactly one `memory_review_terminal` event with `state: ran_empty` (agent returned `[]`) or `state: needs_user` (with final `candidates`/`accepted` counts).
  - Existing `memory_candidates_ready` push-notify retained as mid-phase signal (distinct from terminal event).
  - No duplicate event emissions on the skip path (helper already emitted).
- **DOCS:** commands
- **Complexity:** medium

## T006 — Orchestrator wiring: Phase 7 of `/z-review-all` mirrors T005
- **Files:** skills/z-review-all/SKILL.md
- **Depends on:** T003
- **Acceptance:**
  - Phase 7 changes mirror T005 (same single-event-per-invocation contract).
  - `parent_command: review-all` unchanged.
- **DOCS:** commands
- **Complexity:** low

## T007 — Push-notify policy on `skipped_broken_context` with session dedup
- **Files:** skills/z-implement-all/SKILL.md, skills/z-review-all/SKILL.md, skills/z-debug/SKILL.md
- **Depends on:** T003
- **Acceptance:**
  - At the top of each top-level command (`/z-implement-all`, `/z-review-all`, `/z-debug` Phase 10): `rm -f "$BASE/.notify-dedup-session"`.
  - After the helper or orchestrator emits a `memory_review_terminal` with `state: skipped_broken_context`: grep `$BASE/.notify-dedup-session` for `<slug>:<skip_reason>`. If absent, push-notify with reason text + append the line. If present, silent.
  - Honor `Z_HARNESS_NOTIFY=off` (no notify regardless).
  - No notify on `not_applicable` or `ran_empty`.
- **DOCS:** commands
- **Complexity:** medium

## T008 — `/z-debug` Phase 10 memory-review step (on `status: shipped` branch only)
- **Files:** skills/z-debug/SKILL.md, commands/z-debug.md
- **Depends on:** T001, T002, T003, T004, T007
- **Acceptance:**
  - Phase 10's `status: shipped` finalize branch invokes `bash scripts/run-memory-review.sh "$RUN" "debug"`.
  - Parses stdout with `mapfile`; on `STATUS: ready` dispatches review-agent with `parent_command: debug`, `debug_md_path` from line 5, `spec_path` from line 3 (may be empty), `cumulative_diff_path` from line 2, `tags_path` from line 4.
  - AskUserQuestion loop with source `incident:debug-<slug>-<RUN>`, hard cap 3 candidates.
  - Phase 10's `status: abandoned` branch does NOT invoke the helper (no telemetry).
  - One `memory_review_terminal` event per Phase 10 invocation.
- **DOCS:** commands, z-debug
- **Complexity:** medium

## T009 — `/z-stats` Phase 4b reads `memory_review_terminal` + back-compat for old events
- **Files:** skills/z-stats/SKILL.md
- **Depends on:** T003, T005, T006, T008
- **Acceptance:**
  - Phase 4b reads `memory_review_terminal` events from `z-harness/metrics.jsonl`.
  - "Last 10 runs" defined by unique `run` field. jq snippet from SPEC §`z-stats` is used.
  - Aggregation groups by terminal state, sub-counts by `skip_reason` and `parent_command`.
  - Back-compat: maps old `phase_end{name:memory_review,skip_reason}` and `review_agent_failed{reason:tags_missing}` events into the 4-state view with null-safe defaults.
  - Output section titled "Memory review terminal states (last 10 runs)" appears after existing Phase 4 content.
  - Read-only — no writes.
- **DOCS:** commands
- **Complexity:** medium

## T010 — qt-bot remote docs/llm/ deployment probe
- **Files:** (none in repo — runtime probe only; results captured in PLAN run notes)
- **Depends on:** —
- **Acceptance:**
  - Use `qt-bot-remote` skill to SSH to `zeke-pc` and check existence of `~/dev/qt-bot/docs/llm/INDEX.json` AND `~/dev/qt-bot/docs/llm/TAGS.txt`.
  - If both present: report deployment OK; memory-review will function on qt-bot runs.
  - If either missing: report which, and recommend `/z-init-docs` be run on remote.
  - Result note appended to `z-harness/postmortem-memory-nudge/archive/<RUN>/qt-bot-probe.md`.
- **Complexity:** medium

## T011 — `/z-improve` end-to-end smoke test
- **Files:** (none — verification only)
- **Depends on:** T001-T009 shipped
- **Acceptance:**
  - Run `/z-improve postmortem-memory-nudge` on this slug after the implementation tasks ship.
  - Confirm a `suggest_memory_called` event lands in `z-harness/postmortem-memory-nudge/archive/<improve-RUN>/events.jsonl`.
  - Event has non-empty `concept` field (concept_hints derivation works).
  - User may Cancel the actual memory-write — only the dispatch needs to fire.
  - Result note appended to archive.
- **Complexity:** low

## T012 — Update SKILL.md/commands docs trail for refactored events
- **Files:** docs/llm/review-agent.json, docs/human/review-agent.md, docs/llm/scripts.json, docs/human/scripts.md, docs/llm/commands.json, docs/human/commands.md
- **Depends on:** T001-T009 shipped
- **Acceptance:**
  - The four affected concepts have updated `memories[]` (only if a candidate surfaces) or `gotchas`/`invariants` reflecting the new event shape.
  - This task is the natural target for `/z-maintain-docs` after implementation; can be deferred and executed by `/z-maintain-docs` later. Marked here so it's tracked.
- **DOCS:** review-agent, scripts, commands
- **Complexity:** medium
