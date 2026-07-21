# handoff-v1 — Machine-readable agent handoff protocol

> Last updated: 2026-07-09
> Schema: `docs/schemas/handoff.schema.json`
> Command: `skills/z-handoff/SKILL.md`
> Automated producer: `scripts/write-handoff.sh`

## Overview

The handoff protocol standardizes session continuity across z-harness agents. Any agent (pi, Claude Code, Codex CLI, or a future agent) can produce a `handoff.json` artifact at a clean break point. Any orchestrator (Hermes, or any other consumer) can read it and resume work autonomously — no manual prompt composition, no lost context.

The handoff is a **lightweight data artifact** — it does not duplicate plan state (HANDOFF.md, INTENT.md, SPEC.md, PLAN.md, TASKS.md, LEDGER.md). It says: "I was here, next step is this, load these files." There are two protocol versions in the wild: `1.0` (base handoff — the 7 original fields) and `1.1` (adds an optional `attend_resume` predicate used by `/z-attend` chain yields). Both validate against the same schema; a stored `1.0` file never gains `attend_resume` after the fact.

## Problem

When an agent session reaches high context pressure or a natural stopping point, the user currently has to manually compose a continuation prompt for a new session. The new session:
- Lacks continuity with the prior session
- Loses context about what was in progress
- Requires the user to re-orient the agent from scratch

## Workflow

```
Agent session    →  /z-handoff  →  writes SESSION_CONTEXT.md, handoff.json  →  exits
Orchestrator     →  detects handoff.json  →  reads it  →  spawns new session
New session      →  loads context_files (SESSION_CONTEXT.md first)  →  receives next_step prompt  →  continues work
Orchestrator     →  deletes handoff.json (consumed)
```

1. Agent context is high, or work reaches a clean break point
2. Agent invokes `/z-handoff` (explicit slash command) or auto-suggests it
3. The command writes `SESSION_CONTEXT.md` — a short live brief of current work, workspace state, decisions, open questions, and landmines — to the plan directory (or workspace fallback) before assembling context files
4. The command writes `handoff.json` to `$Z_HARNESS_PLAN_DIR` (or the workspace root when there is no active plan)
5. Agent exits, printing a copy-paste resume block with the full `next_step`
6. The orchestrator detects `handoff.json`, reads it
7. The orchestrator spawns a new agent session: loads `context_files` in order (starting with `SESSION_CONTEXT.md` if present), passes `next_step` as the initial prompt
8. The orchestrator deletes `handoff.json` (consumed)

`scripts/write-handoff.sh` is the automated producer used by `/z-execute`'s compaction breakpoint (gated by `workflow.hermes_enabled=true`) and by `/z-attend` at every yield boundary. `scripts/write-clear-checkpoint.sh` is a shared checkpoint hook that wraps this same producer — it preserves the `handoff.json` schema and puts workflow-specific checkpoint metadata in a separate `clear_checkpoint_written` event/state file rather than in the schema-constrained handoff token.

## Relationship to existing artifacts

The handoff is NOT a replacement for HANDOFF/INTENT/SPEC/PLAN/TASKS/LEDGER — it is a **continuity bridge** between sessions. The real durable context lives in the plan artifacts. `handoff.json` just points to them, in priority order.

z-harness already maintains these artifacts per plan slug:
- `HANDOFF.md` — curated fresh-session brief (invariants, rejected approaches, decisions archive, verification commands)
- `INTENT.md` — accepted intent/scope/acceptance checklist (INTENT-mode plans)
- `SPEC.md` / `PLAN.md` / `TASKS.md` / `FIX.md` — legacy SDD-mode plan artifacts
- `LEDGER.md` — INTENT-mode BFS ledger
- `workstreams.json` — parallel workstream coordination
- `SESSION_CONTEXT.md` — live, `/z-handoff`-written, mid-session brief (current work / workspace state / decisions / open questions / landmines / immediate next action)
- `SESSION.md` — durable, `context-curator`-curated execution log, folded at `/z-execute` settle points
- Session logs (`events.jsonl`) in `archive/<run>/`

`SESSION_CONTEXT.md` and `SESSION.md` are distinct and must not be confused: `SESSION_CONTEXT.md` is the live conversational brief only `/z-handoff` writes (it captures state that otherwise exists only in the current context window); `SESSION.md` is the mechanical, telemetry-derived log `context-curator` maintains at durable settle points. `context-curator` never edits `SESSION_CONTEXT.md`.

The handoff protocol sits alongside these as a lightweight continuity artifact — read by orchestrators, not by humans.

## JSON Schema

The full schema is defined in `docs/schemas/handoff.schema.json` (JSON Schema draft 2020-12, `additionalProperties: false`).

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `protocol_version` | string enum `["1.0", "1.1"]` | yes | Schema version. `1.1` adds `attend_resume`; `1.0` never has it. |
| `timestamp` | string | yes | ISO-8601 UTC timestamp of when the handoff was written. |
| `agent` | string | yes | Which agent produced this handoff. For provenance only — consumers MUST NOT branch behavior on this field. Examples: `"pi"`, `"claude"`, `"codex"`. |
| `slug` | string \| null | no | The plan slug if the agent was working inside a z-harness plan. `null` for ad-hoc work. When present, the orchestrator can locate plan artifacts directly without parsing `context_files` paths. |
| `status` | enum | yes | Why the handoff was written. See Status enum below. |
| `next_step` | string | yes | Human-readable continuation prompt (max 2000 chars). The orchestrator passes this to the next agent session. Should be specific enough that a fresh agent can begin work without re-orientation; must tell the agent to read `SESSION_CONTEXT.md` first when it exists. |
| `context_files` | array | yes | Files the orchestrator should load into the next session. Ordered by priority. Min 1 entry. |
| `attend_resume` | object | no (1.1 only) | Resume predicate populated only when the handoff is written from a `/z-attend` chain yield. See Protocol 1.1 below. |

### Status enum

| Value | Meaning |
|-------|---------|
| `context_pressure` | Agent context window is near capacity and must clear. The work is incomplete — resume from `next_step`. |
| `clean_break` | Natural stopping point in the work (phase boundary, batch complete, end of a task group). The work is incomplete — resume from `next_step`. |
| `complete` | All planned work is done. The `next_step` may be empty or describe follow-up (e.g., "run /z-review-all"). |
| `blocked` | Agent cannot proceed without external input (user decision, dependency not yet available, upstream change needed). |

`write-handoff.sh` always sets `status` to `clean_break` regardless of actual context state — only the `/z-handoff` slash command can set `context_pressure`, `complete`, or `blocked` (via `Z_HARNESS_HANDOFF_STATUS`).

### context_files entries

Each entry is `{path: string, role: string}`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Absolute or workspace-relative path to the context file. The orchestrator resolves relative paths against the workspace root. |
| `role` | enum | yes | `"handoff"`, `"intent"`, `"spec"`, `"plan"`, `"tasks"`, `"ledger"`, `"workstreams"`, `"session_log"`, `"invariants"`, `"rejected_approaches"`, `"decisions_archive"`, `"verification_commands"`, `"diff"`, `"other"`. The `invariants` / `rejected_approaches` / `decisions_archive` / `verification_commands` roles are HANDOFF.md **category pointers** — they intentionally point at the same `HANDOFF.md` path as the `handoff` role entry, one entry per content category inside that file. A consumer that naively reads every `context_files` entry will read `HANDOFF.md` up to 5 times; dedupe by path if that matters. |

## Protocol 1.1 — attend_resume

When `/z-attend` yields at a chain step, `write-handoff.sh` is invoked with `Z_HARNESS_ATTEND_RESUME=1` and 5 additional env vars. This bumps `protocol_version` to `"1.1"` and adds a nested `attend_resume` object (all 5 sub-fields `minLength: 1`, required):

| Sub-field | Captured from | Resume behavior on mismatch |
|-----------|----------------|------------------------------|
| `expected_head_sha` | git HEAD at yield | HALT (re-plan vs accept-new-base) |
| `expected_phase` | chain step to re-enter at | HALT (state and token disagree) |
| `done_set_hash` | `scripts/session-helpers.sh` done-set hash of TASKS.md | WARN + ask {continue / abort} |
| `dirty_state_fingerprint` | digest of `git status --porcelain` | WARN + ask {continue / abort} |
| `session_id` | yield-time session id | WARN HARD (unchanged id ⇒ user likely did not `/clear`) + offer abort-to-clear-first |

If any of the 5 attend env vars is empty when `Z_HARNESS_ATTEND_RESUME=1`, `write-handoff.sh` fails loudly (`exit 1`, naming the missing var(s)) rather than writing a schema-invalid `1.1` handoff. Non-attend callers (manual `/z-handoff`, `write-clear-checkpoint.sh`) always emit `1.0` with no `attend_resume` key.

## Consumer contract (Hermes / orchestrator)

The orchestrator is the **driver** — the handoff is data. The orchestrator decides:
- Whether to spawn a new session
- Which model to use
- How to load `context_files` (in-order Read, @-include, or hybrid)
- Whether to merge `next_step` into a larger system prompt

Minimum consumer behavior:
1. Detect `handoff.json` in `$Z_HARNESS_PLAN_DIR` (or the workspace root when `slug` is null)
2. Validate against the schema
3. Read `context_files` in order, loading each into the new session's context (`SESSION_CONTEXT.md` first when present)
4. Pass `next_step` as the initial task to the new agent session
5. Delete `handoff.json` after successful consumption (so it is not re-consumed)
6. When `protocol_version` is `1.1`, cross-check `attend_resume` per the table above before resuming

When `slug` is present and non-null, the orchestrator may also set `Z_HARNESS_SLUG` and `Z_HARNESS_PLAN_DIR` in the new session's environment to enable z-harness command continuity.

## Examples

### Context pressure mid-plan

```json
{
  "protocol_version": "1.0",
  "timestamp": "2026-06-08T14:30:00Z",
  "agent": "pi",
  "slug": "handoff-protocol",
  "status": "context_pressure",
  "next_step": "Continue implementing the handoff protocol. Read SESSION_CONTEXT.md for live state, then TASKS.md for acceptance criteria.",
  "context_files": [
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/SESSION_CONTEXT.md", "role": "session_log"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/HANDOFF.md", "role": "handoff"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/TASKS.md", "role": "tasks"},
    {"path": "<repo>/docs/schemas/handoff.schema.json", "role": "other"},
    {"path": "<repo>/docs/human/handoff-v1.md", "role": "other"}
  ]
}
```

### Attend-chain yield (protocol 1.1)

```json
{
  "protocol_version": "1.1",
  "timestamp": "2026-06-08T16:00:00Z",
  "agent": "claude",
  "slug": "add-auth-middleware",
  "status": "clean_break",
  "next_step": "Resume /z-attend for add-auth-middleware at the implement-all step.",
  "context_files": [
    {"path": "<state>/z-harness/example-repo-00000000/plans/add-auth-middleware/TASKS.md", "role": "tasks"}
  ],
  "attend_resume": {
    "expected_head_sha": "a1b2c3d4",
    "expected_phase": "implement-all",
    "done_set_hash": "d41d8cd9",
    "dirty_state_fingerprint": "e3b0c442",
    "session_id": "sess-0001"
  }
}
```

### Ad-hoc work (no plan)

```json
{
  "protocol_version": "1.0",
  "timestamp": "2026-06-08T15:00:00Z",
  "agent": "pi",
  "slug": null,
  "status": "clean_break",
  "next_step": "Continue refactoring src/auth/handlers.py — extract the token validation logic from login() into a separate validate_token() function. Current diff is in /tmp/auth-refactor.patch.",
  "context_files": [
    {"path": "/tmp/auth-refactor.patch", "role": "diff"},
    {"path": "<project>/src/auth/handlers.py", "role": "other"}
  ]
}
```

### Complete

```json
{
  "protocol_version": "1.0",
  "timestamp": "2026-06-08T17:00:00Z",
  "agent": "pi",
  "slug": "fix-login-timeout",
  "status": "complete",
  "next_step": "",
  "context_files": [
    {"path": "<state>/z-harness/example-repo-00000000/plans/fix-login-timeout/FIX.md", "role": "plan"}
  ]
}
```

## Future (not v1)

- Auto-trigger when context crosses a configurable token threshold
- Orchestrator-side context window estimation to pre-emptively spawn new sessions before pressure

## Out of scope (v1)

- Any change to z-harness scripts or infrastructure beyond the protocol/command/producer surface described here
- Auto-detection of context pressure (agent-side responsibility; protocol just defines the artifact)
- Migration of existing SESSION.md or route-decision.md artifacts into handoff.json

## Pre-existing handoff.json

If `handoff.json` already exists at the target path when `/z-handoff` (or `write-handoff.sh`) runs, it is **overwritten**. The orchestrator is responsible for consuming (and deleting) `handoff.json` after reading it. If an unconsumed `handoff.json` is overwritten, context from the prior session is lost — which is expected, as the new handoff represents the current session state.
