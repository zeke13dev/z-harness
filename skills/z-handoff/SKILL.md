---
name: z-handoff
disable-model-invocation: true
description: Write a handoff.json artifact for session continuity. Captures the current working context (plan slug, active files, next step) into a machine-readable JSON contract that any watcher (Oh My Pi, Hermes, MCP, or a future orchestrator) can consume to resume work in a fresh agent session. Universal — works for pi, Claude Code, Codex CLI, and any future z-harness agent.
argument-hint: "[continuation prompt — optional override for next_step]"
runtime: c1
driver_features_required: []
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/handoff`** — the session continuity protocol. Write `handoff.json` to the workspace so a watcher (Oh My Pi, Hermes, MCP, or a future orchestrator) can resume work in a fresh agent session.

Continuation prompt (from `$ARGUMENTS`, optional):

$ARGUMENTS

If `$ARGUMENTS` is non-empty, it overrides the auto-detected `next_step`. If empty, you will auto-detect the next step from the current context.

## Design principles

- **Universal**: no agent-specific branching. This command works identically for pi, Claude Code, and any future agent.
- **Lightweight**: `handoff.json` points to context files — it does NOT duplicate plan state (SPEC, PLAN, TASKS).
- **Watcher-driven**: the handoff is pure data. The watcher decides how to spawn the next session and which model to use.


## Shared command-side checkpoint hook

For explicit `/clear` + resume checkpoints, workflow skills should prefer `scripts/write-clear-checkpoint.sh` over open-coded local ack files. The shared hook wraps this handoff producer, preserves the existing `handoff.json` schema, and puts workflow resume metadata in the `clear_checkpoint_written` event plus an optional checkpoint state file.

Common seam setup:

```bash
export Z_HARNESS_CHECKPOINT_STATUS="${Z_HARNESS_CHECKPOINT_STATUS:-clean_break}"
export Z_HARNESS_CHECKPOINT_NEXT_STEP="Resume <command>; continue at <phase>."
export Z_HARNESS_CHECKPOINT_RESUME_COMMAND="<command>"
export Z_HARNESS_CHECKPOINT_PHASE_NAME="<human phase name>"
export Z_HARNESS_CHECKPOINT_PHASE_ID="<stable-phase-id>"
export Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT="$Z_HARNESS_PLAN_DIR/archive/$RUN/<artifact>.md"
export Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD="<HEAD/hash/input fingerprint>"
export Z_HARNESS_CHECKPOINT_PRODUCER="<workflow-name>"
export Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON='{"phase":"<phase>"}'
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/write-clear-checkpoint.sh"
```

If the script prints `STATUS: clear_checkpoint`, stop before the high-context phase and let the watcher/operator clear and resume. If it prints `STATUS: clear_checkpoint_fast_forward`, the stored phase state is fresh and the workflow continues past the checkpoint seam. If stored state is stale, the default `Z_HARNESS_CHECKPOINT_STALE_MODE=reject` fails closed; callers may opt into `refresh` only when re-writing the checkpoint is safe.

## Phase 0 — Resolve run context

If working inside a plan, resolve the current run identifier and archive directory:

```bash
# Resolve run id and archive directory from z-harness plan context
if [ -n "${Z_HARNESS_PLAN_DIR:-}" ]; then
  CURRENT_ARCHIVE_DIR="${Z_HARNESS_PLAN_DIR}/archive/${RUN:-adhoc}"
  RUN_ID="${RUN:-$(date -u +%Y%m%dT%H%M%SZ)-handoff}"
else
  CURRENT_ARCHIVE_DIR=""
  RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-handoff"
fi
```

These variables are used in Phase 1b (session log path) and Phase 4 (telemetry).

---

## Phase 1 — Detect current context

Determine what the agent is currently working on.

### 1a — Resolve plan context

If the agent is working inside a z-harness plan, `Z_HARNESS_SLUG` and `Z_HARNESS_PLAN_DIR` will be set in the environment. Check:

```bash
echo "SLUG=${Z_HARNESS_SLUG:-none}"
echo "PLAN_DIR=${Z_HARNESS_PLAN_DIR:-none}"
```

If `Z_HARNESS_SLUG` is set, use it as the `slug` field. If not set, `slug` is `null`.

### 1b — Write live session context

Plan artifacts say what should happen. A mid-session agent also has live state that otherwise exists only in the context window. Write that state to `$Z_HARNESS_PLAN_DIR/SESSION_CONTEXT.md` (or the workspace fallback when no plan is active) before assembling `context_files`.

Keep it short and concrete. Include only state needed to resume:

- **Current work**: the exact task/subtask/symbol/file the agent was touching when `/z-handoff` was invoked.
- **Workspace state**: uncommitted change summary and changed files; include a patch file separately if needed, not inline.
- **Decisions made this session**: decisions not already captured in HANDOFF/INTENT/SPEC/PLAN/TASKS/FIX/LEDGER artifacts.
- **Open questions/blockers**: unresolved user, design, dependency, or review questions.
- **Landmines discovered**: failed commands, bad assumptions, broken tests, merge/rebase hazards, or files that looked tempting but were wrong.
- **Immediate next action**: the first concrete command/edit/read the next agent should perform.

Use this shape — the script prepends frontmatter and `# Session context` automatically, so pass only the section content:

```markdown
## Current work
- ...

## Workspace state
- ...

## Decisions this session
- ...

## Open questions
- ...

## Landmines
- ...

## Immediate next action
- ...
```

If invoking `scripts/write-handoff.sh`, pass this section content through `Z_HARNESS_HANDOFF_SESSION_CONTEXT`; the script wraps it with frontmatter, writes `SESSION_CONTEXT.md` atomically, and includes it in `context_files`.

### 1c — Identify context files

Gather the files that the next session will need. Use this priority order:
1. **Live session context**: `$Z_HARNESS_PLAN_DIR/SESSION_CONTEXT.md` — include if written.
2. **Primary plan artifacts** (if in a plan): `$Z_HARNESS_PLAN_DIR/HANDOFF.md`, `$Z_HARNESS_PLAN_DIR/INTENT.md`, `$Z_HARNESS_PLAN_DIR/SPEC.md`, `$Z_HARNESS_PLAN_DIR/PLAN.md`, `$Z_HARNESS_PLAN_DIR/TASKS.md`, `$Z_HARNESS_PLAN_DIR/FIX.md`, `$Z_HARNESS_PLAN_DIR/LEDGER.md` — include whichever exist. This keeps intent-mode handoffs carrying the accepted intent/scope/acceptance checklist and ledger while preserving legacy SPEC/PLAN/TASKS/FIX context.
3. **Workstreams** (if in a plan): `$Z_HARNESS_PLAN_DIR/workstreams.json` — include if it exists.
4. **Session log**: the current run's `events.jsonl` at `${CURRENT_ARCHIVE_DIR}/events.jsonl` or `$Z_HARNESS_PLAN_DIR/archive/<current_run>/events.jsonl` — include if the path is known.
5. **Active diff**: if the workspace has uncommitted changes, run `git diff > /tmp/handoff-diff-<timestamp>.patch` and include the patch path. Do NOT include the diff inline in `next_step`.
6. **Any other files** the user explicitly mentions as context.
7. **Fallback** — if no context files are found from any of the above, include at least one file from the workspace root (e.g., `README.md`, `.gitignore`) with role `"other"` so the `context_files` array is never empty.

After detection, assign the discovered files to a variable:

```bash
# CONTEXT_FILES is a JSON array of {path, role} objects assembled from detection above
CONTEXT_FILES='[{"path":"...","role":"..."}]'
```

For each file, determine its `role`:

| File pattern | Role |
|-------------|------|
| `**/HANDOFF.md` | `"handoff"` |
| `**/INTENT.md` | `"intent"` |
| `**/SPEC.md` | `"spec"` |
| `**/PLAN.md` | `"plan"` |
| `**/TASKS.md` | `"tasks"` |
| `**/FIX.md` | `"plan"` |
| `**/LEDGER.md` | `"ledger"` |
| `**/workstreams.json` | `"workstreams"` |
| `**/events.jsonl`, `**/SESSION.md`, `**/SESSION_CONTEXT.md` | `"session_log"` |
| `*.patch`, `*.diff` | `"diff"` |
| Anything else | `"other"` |

### 1d — Determine next_step

If the user provided `$ARGUMENTS`, use it verbatim as `next_step`.

Otherwise, auto-detect from context. The `next_step` must name the active work and point at `SESSION_CONTEXT.md` whenever it exists:

- **If in a plan with TASKS.md**: find the first `[ ]` (pending) task. Use: `"Continue <slug>: implement <first pending task id> — <task description>. First read SESSION_CONTEXT.md for the live handoff, then TASKS.md for acceptance criteria."`
- **If in a plan with FIX.md** (light mode): use: `"Continue <slug>: <one-line summary from FIX.md Approach section>. First read SESSION_CONTEXT.md for live state."`
- **If no plan (ad-hoc)**: describe what the agent was last doing. Use: `"Continue <brief description of current work>. First read SESSION_CONTEXT.md and the listed context files."`

The `next_step` must be specific enough that a fresh agent can begin work without asking "what was I doing?"

After detection, assign to a variable:

```bash
# NEXT_STEP is the continuation prompt string
NEXT_STEP="Continue <slug>: ..."
```

### 1e — Determine status

| Condition | Status |
|-----------|--------|
| Agent context window is visibly near capacity (long history, repeated summarization) | `"context_pressure"` |
| Natural stopping point: phase boundary, batch complete, user requested clean break | `"clean_break"` |
| All planned tasks are `[x]` (TASKS.md fully complete) or FIX.md status is `shipped` | `"complete"` |
| Agent is blocked: waiting for user decision, external dependency, or upstream change | `"blocked"` |

When unsure, default to `"clean_break"`.

### 1f — Identify agent

Set the `agent` field to a short identifier for the current agent platform:

- `"pi"` for pi
- `"claude"` for Claude Code
- `"codex"` for Codex CLI
- `"gemini"` for Gemini CLI
- `"other"` as fallback

This is for **provenance only** — consumers MUST NOT branch behavior on this field.

## Phase 2 — Assemble and validate

Assemble the `handoff.json` payload following the schema at `docs/schemas/handoff.schema.json`.

The payload is a single JSON object. Required fields: `protocol_version`, `timestamp`, `agent`, `status`, `next_step`, `context_files`. Optional: `slug` (null when not in a plan).

Validate mechanically before writing:

```bash
# Validate context_files is non-empty (JSON string, not bash array)
[ -n "$CONTEXT_FILES" ] || { echo "handoff: context_files must have at least one entry"; exit 1; }

# Validate next_step is non-empty (unless status is complete)
[ "$STATUS" = "complete" ] || [ -n "$NEXT_STEP" ] || { echo "handoff: next_step must be non-empty for status=$STATUS"; exit 1; }
```

## Phase 3 — Write handoff.json

Write `handoff.json` to the **plan directory** — `$Z_HARNESS_PLAN_DIR/handoff.json`. This is the canonical home: it sits next to `SESSION.md`/`TASKS.md`/`LEDGER.md` (the artifacts `context_files` points at), it survives a `/clear` and a change of working directory, and it matches where `scripts/write-handoff.sh` (the automated `/z-execute` producer) and `/z-attend` (the resume consumer) read and write the token. Only fall back to the workspace root when there is genuinely no active plan (`slug` is null):

```bash
HANDOFF_PATH="${Z_HARNESS_PLAN_DIR:-${WORKSPACE_ROOT:-$PWD}}/handoff.json"
```

Write atomically: write to a temp file, then rename:

```bash
cat > "${HANDOFF_PATH}.tmp.$$" << 'HANDOFF_EOF'
{...assembled JSON...}
HANDOFF_EOF
mv "${HANDOFF_PATH}.tmp.$$" "$HANDOFF_PATH"
```

When in a plan, the resume consumers (`/z-attend`, the `/z-execute` compaction flow) look for `handoff.json` inside `$Z_HARNESS_PLAN_DIR`. Write it there. The workspace-root path is only the plan-less fallback.

### Alternate output: SESSION.md

`SESSION_CONTEXT.md` is the required live handoff brief for `/z-handoff`. `SESSION.md` remains the bounded curated execution log produced by `context-curator`; do not rely on it for live conversational state. If both exist, include both in `context_files` with `SESSION_CONTEXT.md` before `SESSION.md`.

## Phase 4 — Emit telemetry

If z-harness telemetry is available (`scripts/log-event.sh` exists):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
  "${RUN_ID}" handoff_written \
  "$(python3 -c 'import json,sys; print(json.dumps({
    "protocol_version":"1.0","agent":"<agent>","slug":"<slug_or_null>",
    "status":"<status>","context_file_count":<n>
  }))')"
```

If no run is active (ad-hoc work outside a plan), log under a generated run id:

```bash
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-handoff"
```

## Phase 5 — Exit

After writing `handoff.json`:

1. Print a brief summary to the user:
   ```
   Handoff written to <path>
     Status: <status>
     Slug: <slug or "none (ad-hoc)">
     Context files: <n>
     Session log: <path to SESSION.md if written>
   ```
2. Print the copy-paste resume block — the FULL `next_step`, untruncated, in its own fenced
   block so a human operator (no Hermes watcher) can `/clear` and paste it as the next prompt:

   ````markdown
   Resume after /clear — copy-paste:

   ```
   <full next_step verbatim>
   ```
   ````

   This block is the portable fallback for a human operator driving the handoff without an
   automatic watcher.
3. Exit the agent session. A watcher detects `handoff.json` and spawns the next session.

## Examples

### Mid-plan context pressure

```json
{
  "protocol_version": "1.0",
  "timestamp": "2026-06-08T14:30:00Z",
  "agent": "pi",
  "slug": "handoff-protocol",
  "status": "context_pressure",
  "next_step": "Continue handoff-protocol: implement commands/z-handoff.md — the /handoff command spec. Schema and docs are done.",
  "context_files": [
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/HANDOFF.md", "role": "handoff"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/INTENT.md", "role": "intent"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/SPEC.md", "role": "spec"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/PLAN.md", "role": "plan"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/TASKS.md", "role": "tasks"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/FIX.md", "role": "plan"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/LEDGER.md", "role": "ledger"},
    {"path": "<state>/z-harness/example-repo-00000000/plans/handoff-protocol/archive/20260609T014456Z-handoff-protocol/events.jsonl", "role": "session_log"},
    {"path": "<repo>/docs/schemas/handoff.schema.json", "role": "other"}
  ]
}
```

### Ad-hoc work, clean break

```json
{
  "protocol_version": "1.0",
  "timestamp": "2026-06-08T15:00:00Z",
  "agent": "claude",
  "slug": null,
  "status": "clean_break",
  "next_step": "Continue refactoring src/auth/handlers.py — extract token validation into a separate function. Current diff in /tmp/auth-refactor.patch.",
  "context_files": [
    {"path": "/tmp/auth-refactor.patch", "role": "diff"},
    {"path": "<project>/src/auth/handlers.py", "role": "other"}
  ]
}
```

## Hard rules

- **Write to the plan dir when in a plan.** `handoff.json` goes in `$Z_HARNESS_PLAN_DIR` (the canonical home, co-located with HANDOFF.md/INTENT.md/SESSION.md/TASKS.md/LEDGER.md). Fall back to `$PWD`/`$WORKSPACE_ROOT` only when there is no active plan.
- **Never duplicate plan state.** `context_files` points to HANDOFF/INTENT/SPEC/PLAN/TASKS/FIX/LEDGER artifacts — do not inline their contents in `next_step`.
- **next_step must be specific.** A fresh agent must be able to begin work from `next_step` alone; when `SESSION_CONTEXT.md` exists, `next_step` must tell the agent to read it first.
- **Capture live state outside handoff.json.** Put current work, workspace state, decisions, open questions, landmines, and immediate next action in `SESSION_CONTEXT.md`; keep `handoff.json` thin.
- **Validate before writing.** `context_files` must be non-empty. `next_step` must be non-empty (unless status is `"complete"`).
- **Atomic write.** Use temp-file in same directory + rename so the orchestrator never sees a partially-written `handoff.json`.
- **At least 1 context file.** An empty `context_files` array is invalid. If no files are found, include a fallback file from the workspace root.
- **next_step max 2000 chars.** If the auto-detected prompt is too long, summarize. Empty string is valid when status is `"complete"`.
- **Pre-existing handoff.json is overwritten.** If `handoff.json` already exists at the target path, overwrite it. The consumer is responsible for reading it before a new one is written.
