# handoff-protocol

> Last updated: 2026-06-19
> Covers source: docs/human/handoff-v1.md, docs/schemas/handoff.schema.json, commands/z-handoff.md, scripts/write-handoff.sh

## Overview

The handoff protocol is a lightweight machine-readable session-continuity mechanism for z-harness agents. When a session reaches a context boundary, a phase boundary, or any other clean stopping point, an agent writes a `handoff.json` artifact to the plan directory. Any consuming orchestrator — Hermes, `/z-attend`, or a future consumer — reads that artifact to know which files to load, what the next action is, and (in protocol 1.1) whether the workspace state still matches the yield-time predicate.

The handoff is intentionally thin. It does not duplicate plan state (SPEC.md, PLAN.md, TASKS.md, LEDGER.md). It points at those files via `context_files` and carries a one-sentence `next_step` continuation prompt. The orchestrator owns all spawn, model-selection, and session-setup decisions; `handoff.json` is pure data.

There are two producers. The `/z-handoff` slash command is the agent-facing explicit producer: it auto-detects context, assembles the JSON, and writes it. The `scripts/write-handoff.sh` script is the automated producer called at compaction breakpoints in `/z-execute` (gated by `hermes_enabled=true`) and at yield boundaries in `/z-attend` (unconditional). The two consumers are Hermes (protocol 1.0, compaction path) and `/z-attend resume` (protocol 1.1, validated resume path).

## Key entry points

- `docs/schemas/handoff.schema.json:1` — `handoff schema` — JSON Schema draft 2020-12 defining the full contract; `protocol_version` is an enum `["1.0","1.1"]` (not a const) so both protocol variants validate against the same schema
- `commands/z-handoff.md:1` — `/z-handoff` — agent-facing command; 5-phase procedure (context detect, assemble/validate, atomic write to plan dir, telemetry, exit); supports `$ARGUMENTS` override of `next_step`
- `scripts/write-handoff.sh:1` — `write-handoff.sh` — automated producer; reads `Z_HARNESS_PLAN_DIR`, `Z_HARNESS_SLUG`, `Z_HARNESS_AGENT`; protocol version determined by `Z_HARNESS_ATTEND_RESUME`: `"0"` (absent) → `1.0`; `"1"` → `1.1` with 5 required attend env vars
- `docs/human/handoff-v1.md:1` — protocol narrative — defines status enum, context_files role enum, consumer contract, and examples

## How it interacts with others

- `attend` — `/z-attend` is the primary 1.1 consumer; Phase 0R reads `handoff.json`'s `attend_resume` predicate before re-entering the chain; Phase 2 Step 2.9 calls `write-handoff.sh` with `Z_HARNESS_ATTEND_RESUME=1` at yield boundaries (plan and implement-all steps)
- `session-handoff` — shares `write-handoff.sh` as the automated writer; the compaction breakpoint in `/z-execute` calls `write-handoff.sh` (protocol 1.0) only when `hermes_enabled=true`; session-handoff owns the SESSION.md/curator side; handoff-protocol owns the `handoff.json` artifact side
- `hermes-orchestration` — Hermes is the protocol 1.0 consumer for the compaction path; it spawns a new agent session from `handoff.json` after Hermes-managed task completion
- `commands` — `/z-handoff` is a slash command; `/z-attend` embeds the yield and resume logic

## Edge cases / gotchas

- Protocol 1.0 vs 1.1 is determined at write time by the presence of `Z_HARNESS_ATTEND_RESUME=1`. An attend yield that omits any of the 5 attend env vars causes `write-handoff.sh` to exit non-zero and the yield to fail loudly — the schema requires `minLength:1` for every `attend_resume` sub-field.
- `handoff.json` is written to `$Z_HARNESS_PLAN_DIR`, not the workspace/repo root. When there is no active plan (`slug` is null), `/z-handoff` falls back to `$WORKSPACE_ROOT`/`$PWD`. Orchestrators reading from the wrong path will silently miss the file.
- At the `/z-execute` compaction breakpoint, `write-handoff.sh` is called only when `workflow.hermes_enabled=true`. When that knob is false (the default), no `handoff.json` is written at compaction time. `/z-attend` always writes it, regardless of `hermes_enabled`.
- Pre-existing `handoff.json` is overwritten on every write. The consumer (orchestrator) is responsible for consuming (and deleting) the file after reading. An unconsumed token overwritten by a later yield loses the prior session's state.
- The `agent` field is provenance only. Consumers MUST NOT branch behavior on it. The protocol is agent-agnostic — pi, Claude Code, Codex CLI, and Gemini all produce the same schema.
- `next_step` is capped at 2000 characters by the schema. `write-handoff.sh` truncates with `...` if the composed prompt exceeds this limit.
- `/z-attend` resume validates R1 HEAD SHA as a hard halt. The agent cannot re-enter the chain on a different git base without explicit user acceptance — unlike the soft warn-and-ask behavior for done-set and dirty-tree drift.

## Examples

Protocol 1.0 — context pressure mid-plan (written by `/z-handoff` or Hermes path of `write-handoff.sh`):

```json
{
  "protocol_version": "1.0",
  "timestamp": "2026-06-08T14:30:00Z",
  "agent": "claude",
  "slug": "add-auth-middleware",
  "status": "context_pressure",
  "next_step": "Resume /z-execute for add-auth-middleware. 4/12 tasks done. Start at T005. Read TASKS.md for acceptance criteria and SESSION.md for context.",
  "context_files": [
    {"path": "/.../.local/state/z-harness/.../plans/add-auth-middleware/SPEC.md", "role": "spec"},
    {"path": "/.../.local/state/z-harness/.../plans/add-auth-middleware/TASKS.md", "role": "tasks"},
    {"path": "/.../.local/state/z-harness/.../plans/add-auth-middleware/SESSION.md", "role": "session_log"}
  ]
}
```

Protocol 1.1 — attend yield with resume predicate (written by `write-handoff.sh` from `/z-attend` Phase 2.9):

```json
{
  "protocol_version": "1.1",
  "timestamp": "2026-06-19T10:00:00Z",
  "agent": "claude",
  "slug": "add-auth-middleware",
  "status": "clean_break",
  "next_step": "Resume /z-execute for add-auth-middleware. 8/12 tasks done. Start at T009. Read TASKS.md and SESSION.md.",
  "context_files": [...],
  "attend_resume": {
    "expected_head_sha": "a1b2c3d4",
    "expected_phase": "implement-all",
    "done_set_hash": "sha256:...",
    "dirty_state_fingerprint": "sha256:...",
    "session_id": "session-abc"
  }
}
```
