---
description: "Evaluate a completed z-harness session for patterns worth preserving as memories or skills."
---

You are running **z-harness `/z-evaluate`**. Read-only single-phase command. Analyzes session telemetry for patterns — no subagent dispatch, no code edits.

## Phase 0 — Active-plan registration

```bash
RUN="$(date -u +%Y%m%dT%H%M%SZ)-evaluate"
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
  --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-evaluate --phase analyze \
  --session "$Z_HARNESS_SESSION_ID" 2>/dev/null || true
```

## Phase 1 — Analysis

Resolve the target archive:

```bash
ARCHIVE_DIR="${1:-$(ls -dt "$Z_HARNESS_PLAN_DIR"/archive/*/ 2>/dev/null | head -1)}"
```

Run the evaluation script:

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/evaluate-session.py" "$ARCHIVE_DIR"
```

Log:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
  "orchestration" session_evaluated \
  "$(printf '{"archive_dir":"%s"}' "$ARCHIVE_DIR")"
```

## Phase 2 — Deregister

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status complete 2>/dev/null || true
```

**Always produce visible output** — even with no suggestions, render the "No suggestions — session was routine" header. Never silent-success.

If memory or skill candidates are present, surface them to the user and suggest running `/z-suggest-memory` for memory candidates.
