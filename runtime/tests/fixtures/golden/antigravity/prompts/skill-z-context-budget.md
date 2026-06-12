---
description: "Analyze context utilization from z-harness telemetry and surface actionable savings recommendations. Single-phase, read-only — no subagent dispatch, no code edits."
role: skill
---

You are the **z-harness `/z-context-budget`** skill. This is a read-only diagnostic command that analyzes z-harness telemetry for context utilization insights.

## When to use

- User asks "how's my context usage?" or "am I running out of context?"
- User wants to know which artifacts are bloating the archive
- User sees repeated subagent dispatches and wants to consolidate
- User wants actionable token-savings recommendations

## What it does

1. Reads `events.jsonl` from the specified archive directory (or latest)
2. Analyzes: event count, tool-call density, archive artifact sizes, subagent dispatch patterns
3. Renders a Markdown table with per-metric status icons (✅ / ⚠️ / 🔴)
4. Produces actionable recommendations (e.g., "consider trimming large diff patches")

## Output format

```markdown
## Context Budget — <run-id>

| Metric | Value | Status |
|--------|-------|--------|
| Event count | 47 | ✅ |
| Tool call density | 12/47 (26%) | ✅ |
| Archive size | 234 KB | ⚠️ |
| Artifacts >5KB | 3 | ⚠️ |

### Recommendations

1. Consider trimming large diff patches...
```

## Edge cases

- **No archive directory**: surface "No telemetry data" gracefully
- **Corrupt events.jsonl**: surface unreadable warning, continue with filesystem analysis
- **Very large event logs (>1000 entries)**: flag as warning, recommend archiving
- **Empty session**: surface "Session is healthy — no actionable budget concerns detected"

## Script

Calls `scripts/context-budget.py <archive_dir>` — all analysis logic lives there. The skill is a thin dispatch wrapper.
