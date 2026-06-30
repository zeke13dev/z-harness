# handoff-v1 — Machine-readable agent handoff protocol

> Last updated: 2026-06-08
> Schema: `docs/schemas/handoff.schema.json`
> Command: `skills/z-handoff/SKILL.md`

## Overview

The handoff protocol standardizes session continuity across z-harness agents. Any agent (pi, Claude Code, or future agents) can produce a `handoff.json` artifact at a clean break point. Any orchestrator (Hermes, or any consumer) can read it and resume work autonomously — no manual prompt composition, no lost context.

The handoff is a **lightweight data artifact** — it does not duplicate plan state (SPEC.md, PLAN.md, TASKS.md). It says: "I was here, next step is this, load these files."

## Problem

When an agent session reaches high context pressure or a natural stopping point, the user currently has to manually compose a continuation prompt for a new session. The new session:
- Lacks continuity with the prior session
- Loses context about what was in progress
- Requires the user to re-orient the agent from scratch

## Workflow

```
Agent session    →  /handoff  →  writes handoff.json  →  exits
Orchestrator     →  detects handoff.json  →  reads it  →  spawns new session
New session      →  loads context_files  →  receives next_step prompt  →  continues work
Orchestrator     →  deletes handoff.json (consumed)
```

1. Agent context is high, or work reaches a clean break point
2. Agent invokes `/handoff` (explicit slash command) or auto-suggests it
3. Agent writes `handoff.json` to the workspace root
4. Agent exits
5. The orchestrator detects `handoff.json`, reads it
6. The orchestrator spawns a new agent session: loads `context_files` in order, passes `next_step` as the initial prompt
7. The orchestrator deletes `handoff.json` (consumed)

## Relationship to existing artifacts

The handoff is NOT a replacement for SPEC/PLAN/TASKS — it is a **continuity bridge** between sessions. The real context lives in the plan artifacts. `handoff.json` just points to them.

z-harness already maintains these artifacts per plan slug:
- `SPEC.md` — scope and requirements
- `PLAN.md` — architecture and design decisions
- `TASKS.md` — task breakdown with completion state
- `workstreams.json` — parallel workstream coordination
- Session logs in `archive/<run>/`

The handoff protocol sits alongside these as a lightweight continuity artifact — read by orchestrators, not by humans.

## JSON Schema

The full schema is defined in `docs/schemas/handoff.schema.json` (JSON Schema draft 2020-12).

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `protocol_version` | string | yes | Schema version. Current: `"1.0"`. |
| `timestamp` | string | yes | ISO-8601 UTC timestamp of when the handoff was written. |
| `agent` | string | yes | Which agent produced this handoff. For provenance only — consumers MUST NOT branch behavior on this field. Examples: `"pi"`, `"claude"`. |
| `slug` | string \| null | no | The plan slug if the agent was working inside a z-harness plan. `null` for ad-hoc work. When present, the orchestrator can locate plan artifacts directly without parsing `context_files` paths. |
| `status` | enum | yes | Why the handoff was written. See Status enum below. |
| `next_step` | string | yes | Human-readable continuation prompt (1–2000 chars). The orchestrator passes this to the next agent session. Should be specific enough that a fresh agent can begin work without re-orientation. |
| `context_files` | array | yes | Files the orchestrator should load into the next session. Ordered by priority. Min 1 entry. |

### Status enum

| Value | Meaning |
|-------|---------|
| `context_pressure` | Agent context window is near capacity and must clear. The work is incomplete — resume from `next_step`. |
| `clean_break` | Natural stopping point in the work (phase boundary, batch complete, end of a task group). The work is incomplete — resume from `next_step`. |
| `complete` | All planned work is done. The `next_step` may be empty or describe follow-up (e.g., "run /z-review-all"). |
| `blocked` | Agent cannot proceed without external input (user decision, dependency not yet available, upstream change needed). |

### context_files entries

Each entry is `{path: string, role: string}`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Absolute or workspace-relative path to the context file. The orchestrator resolves relative paths against the workspace root. |
| `role` | enum | yes | Semantic role. `"spec"`, `"plan"`, `"tasks"`, `"workstreams"`, `"session_log"`, `"diff"`, `"other"`. |

## Consumer contract (Hermes / orchestrator)

The orchestrator is the **driver** — the handoff is data. The orchestrator decides:
- Whether to spawn a new session
- Which model to use
- How to load `context_files` (in-order Read, @-include, or hybrid)
- Whether to merge `next_step` into a larger system prompt

Minimum consumer behavior:
1. Detect `handoff.json` in the workspace root
2. Validate against the schema
3. Read `context_files` in order, loading each into the new session's context
4. Pass `next_step` as the initial task to the new agent session
5. Delete `handoff.json` after successful consumption (so it is not re-consumed)

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
  "next_step": "Continue implementing the handoff protocol. We completed the schema and human doc. Next: write skills/z-handoff/SKILL.md — the /handoff command spec for agents.",
  "context_files": [
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/FIX.md", "role": "plan"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/archive/20260609T014456Z-handoff-protocol/events.jsonl", "role": "session_log"},
    {"path": "<repo>/docs/schemas/handoff.schema.json", "role": "other"},
    {"path": "<repo>/docs/human/handoff-v1.md", "role": "other"}
  ]
}
```

### Clean break at batch boundary

```json
{
  "protocol_version": "1.0",
  "timestamp": "2026-06-08T16:00:00Z",
  "agent": "claude",
  "slug": "add-auth-middleware",
  "status": "clean_break",
  "next_step": "Resume /z-execute for add-auth-middleware. T001–T008 are done. Start at T009 (add rate-limiting to auth middleware). Acceptance criteria in TASKS.md.",
  "context_files": [
    {"path": "<state>/z-harness/example-repo-00000000/plans/add-auth-middleware/SPEC.md", "role": "spec"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/add-auth-middleware/PLAN.md", "role": "plan"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/add-auth-middleware/TASKS.md", "role": "tasks"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/add-auth-middleware/SESSION.md", "role": "session_log"}
  ]
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
- Multi-workstream handoff coordination (one handoff per workstream in workstreams.json)
- Orchestrator-side context window estimation to pre-emptively spawn new sessions before pressure

## Out of scope (v1)

- Any change to z-harness scripts or infrastructure — this is a protocol definition and command spec only
- Auto-detection of context pressure (agent-side responsibility; protocol just defines the artifact)
- Hermes implementation changes (consumer-side; protocol defines the contract)
- Migration of existing SESSION.md or route-decision.md artifacts into handoff.json

## Pre-existing handoff.json

If `handoff.json` already exists in the workspace root when `/handoff` runs, it is **overwritten**. The orchestrator is responsible for consuming (and deleting) `handoff.json` after reading it. If an unconsumed `handoff.json` is overwritten, context from the prior session is lost — which is expected, as the new handoff represents the current session state.
