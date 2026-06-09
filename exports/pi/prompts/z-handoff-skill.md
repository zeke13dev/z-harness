# /z-handoff

You are running **z-harness `/handoff`** — the session continuity protocol. You will dynamically gather the current working context and write `handoff.json` to the workspace root. Any orchestrator (Hermes) can then read it and resume work in a fresh agent session.

The handoff is a **data artifact**. It does NOT duplicate plan state (SPEC.md, PLAN.md, TASKS.md). It says: "I was here, next step is this, load these files."

## Design principles

- **Self-contained**: gathers all context dynamically at call time. No prior session maintenance required.
- **Universal**: no agent-specific branching. Works identically for pi, Claude Code, and any future agent.
- **Lightweight**: `handoff.json` points to context files — it does NOT duplicate plan state.
- **Orchestrator-driven**: the handoff is pure data. The orchestrator decides how to spawn the next session.

## Phase 1 — Detect current context

### 1a — Resolve plan context

Check for plan environment or artifacts:

```bash
# Check for z-harness plan context
echo "SLUG=${Z_HARNESS_SLUG:-none}"
echo "PLAN_DIR=${Z_HARNESS_PLAN_DIR:-none}"
```

If neither is set, search the current directory and parent directories for a z-harness plan state directory:

```bash
# Look for plan artifacts in common locations
find . -maxdepth 4 -name "TASKS.md" -o -name "FIX.md" | head -10
```

If no plan context is found at all, the handoff is for **ad-hoc work** — set `slug: null` and gather context from current git state and files.

### 1b — Identify context files

Gather the files that the next session will need, in priority order:

1. **Plan artifacts** — if `Z_HARNESS_PLAN_DIR` is set, check for:
   - `SPEC.md`, `PLAN.md`, `TASKS.md`, `FIX.md` at plan root
   - `SESSION.md` at plan root (if it was maintained)
   - `workstreams.json` at plan root (for parallel orchestration)
   - `events.jsonl` in `archive/<latest-run>/` (recent telemetry)

2. **Ad-hoc context** — if no plan context:
   - `git diff --stat` (recent changes)
   - Any modified/untracked files the agent was working on
   - Session logs or notes

3. **Prior handoff chain** — if a previous `handoff.json` exists, include it

For each file, determine its `role` from this enum:
- `spec` — SPEC.md
- `plan` — PLAN.md or FIX.md
- `tasks` — TASKS.md
- `workstreams` — workstreams.json
- `session_log` — SESSION.md or events.jsonl
- `diff` — git diff or patch file
- `handoff_chain` — prior handoff.json
- `other` — any other context file

### 1c — Determine status

Decide the `status` value:
- `context_pressure` — agent context window is near capacity. Work is incomplete.
- `clean_break` — natural stopping point (phase boundary, batch complete). Work is incomplete.
- `complete` — all planned work is done.
- `blocked` — agent cannot proceed without external input.

### 1d — Determine next_step

Auto-detect what to do next:
- If TASKS.md exists, find the first unfinished task (`[ ]`) and describe it
- If FIX.md exists, read the remaining acceptance criteria
- If `$ARGUMENTS` was provided, use it as-is
- For ad-hoc work, summarize what was in progress

The `next_step` must be specific enough that a fresh agent can begin work without re-orientation.

## Phase 2 — Assemble handoff.json

Build the JSON payload:

```json
{
  "protocol_version": "1.0",
  "timestamp": "<ISO-8601 UTC now>",
  "agent": "pi",
  "slug": "<plan-slug or null>",
  "status": "<context_pressure|clean_break|complete|blocked>",
  "next_step": "<continuation prompt, 1-2000 chars>",
  "context_files": [
    {"path": "<absolute-or-relative-path>", "role": "<role>"}
  ]
}
```

Validation rules:
- `protocol_version` must be `"1.0"`
- `timestamp` must be ISO-8601 UTC
- `agent` for provenance only — consumers MUST NOT branch behavior on this field. Use `"pi"`, `"claude"`, or similar.
- `status` must be one of the four enum values
- `next_step` must be 1-2000 characters
- `context_files` must have at least 1 entry
- Paths are absolute or relative to the workspace root

### Alternate output: write SESSION.md

If you're in a z-harness plan directory, optionally also write or update `SESSION.md` at the plan root. This is a human-readable context summary that preserves decisions, blockers, and what was done. Format:

```markdown
## Done
- T001: Implemented X
- T003: Fixed Y bug

## Pending
- T002: Depends on T001 — needs input parsing

## Decisions
- Chose approach B over A because of latency constraints

## Blockers
- Waiting on API key from user
```

This SESSION.md can then be included in `context_files` with `role: "session_log"` on subsequent handoffs.

## Phase 3 — Write artifacts

### Write handoff.json

Write to the workspace root (plan dir if available, otherwise current working directory):

```bash
# Atomic write using tmp + rename
cat > /tmp/handoff.json.tmp << 'JSONEOF'
{...json payload...}
JSONEOF
mv /tmp/handoff.json.tmp ./handoff.json
echo "handoff.json written ($(wc -c < ./handoff.json) bytes)"
```

Validate the output against the schema at `docs/schemas/handoff.schema.json` if available:

```bash
python3 -c "
import json, sys
with open('./handoff.json') as f:
    data = json.load(f)
# Basic validation
assert data['protocol_version'] == '1.0'
assert data['status'] in ('context_pressure','clean_break','complete','blocked')
assert len(data['next_step']) >= 1
assert len(data['context_files']) >= 1
print('Validation passed')
" 2>&1 || echo "Warning: validation skipped — schema check unavailable"
```

### Optionally write SESSION.md

If working inside a plan directory:

```bash
cat > $Z_HARNESS_PLAN_DIR/SESSION.md << 'MDEOF'
...context summary...
MDEOF
```

## Phase 4 — Telemetry

If z-harness telemetry is available, log the handoff event:

```bash
if command -v log-event.sh &>/dev/null; then
  log-event.sh "$Z_HARNESS_RUN" handoff_written '{"slug":"<slug>","status":"<status>","files":<N>,"bytes":<N>}'
fi
```

## Phase 5 — Exit

Print a summary:
```
/handoff complete
  slug:       <slug or (ad-hoc)>
  status:     <status>
  files:      N context files
  next_step:  <first 80 chars of next_step>
  session_log: <path to SESSION.md if written>

The orchestrator (Hermes) can now detect handoff.json and resume work.
```

Then exit — the agent session should be cleared after /handoff.

## Hard rules

1. **Do NOT block on user input.** /handoff must complete without questions.
2. **Do NOT modify any source code.** The handoff is read-only — it captures state, it does not change it.
3. **Atomic writes only.** Always write to `.tmp` then `mv` — never truncate a file.
4. **Infer next_step from real context.** Do NOT generate a generic "continue working" — read TASKS.md or FIX.md and report the actual next pending task.
5. **At least 1 context file.** An empty context_files array is invalid.
6. **next_step max 2000 chars.** If the auto-detected prompt is too long, summarize.
7. **handoff.json goes to workspace root.** Not inside archive/, not inside a subdirectory.
