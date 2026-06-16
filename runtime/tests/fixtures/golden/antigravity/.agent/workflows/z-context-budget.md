---
description: "Analyze context utilization from z-harness telemetry and surface actionable savings recommendations."
---

You are running **z-harness `/z-context-budget`**. Read-only single-phase command. Analyzes telemetry only — no subagent dispatch, no code edits.

## Phase 0 — Active-plan registration

Register this run in the active-plan registry (advisory only):

```bash
RUN="$(date -u +%Y%m%dT%H%M%SZ)-context-budget"
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" register \
  --run-id "$RUN" --slug "$Z_HARNESS_SLUG" --command /z-context-budget --phase analyze \
  --session "$Z_HARNESS_SESSION_ID" 2>/dev/null || true
```

## Phase 1 — Analysis

Resolve the target archive directory. If the user provided a path, use it. Otherwise default to the latest archive under `$Z_HARNESS_PLAN_DIR/archive/` (most recent by directory name):

```bash
ARCHIVE_DIR="${1:-$(ls -dt "$Z_HARNESS_PLAN_DIR"/archive/*/ 2>/dev/null | head -1)}"
```

Run context-budget.py and surface the output to the user:

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/context-budget.py" "$ARCHIVE_DIR"
```

Log the analysis event:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" \
  "orchestration" context_budget_analysis \
  "$(printf '{"archive_dir":"%s"}' "$ARCHIVE_DIR")"
```

## Phase 2 — Deregister

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" deregister \
  --run-id "$RUN" --status complete 2>/dev/null || true
```

Surface the rendered output to the user. If the output includes recommendations, highlight the top 1-2 most impactful ones.
