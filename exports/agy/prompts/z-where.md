---
description: Read-only "what's active / why am I blocked" query. Prints resolved base + repo-id, lists all active plans (slug, command, phase, branch, current_task, age, status), and optionally shows path-overlap with the current run. No writes, no LLM calls.
role: workflow
---

You are running **z-harness `/z-where`**. Read-only diagnostic. Cheap — uses only Bash/Python on the active-plan registry; no subagent dispatch, no LLM calls.

## Phase 0 — Resolved base header

Print a small header at the very top of the output (unconditionally):

```bash
_zh_base="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir 2>/dev/null)"
_zh_repo_id="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" z_harness_repo_id 2>/dev/null)"
```

Display as:

```
Base:    <_zh_base>
Repo-id: <_zh_repo_id>
```

Fallback rules:
- If `_zh_base` is empty → print `Base: (unavailable)`
- If `_zh_repo_id` is empty → print `Repo-id: (unavailable)`

## Phase 1 — Active plan list

Fetch all active-plan records from the registry:

```bash
_zh_registry_json="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" list --json 2>/dev/null)"
```

If the command fails or returns empty/invalid JSON, print:

```
Active plans: (registry unavailable)
```

Otherwise, parse the JSON array and render a table. For each record compute `age` = current time minus `last_heartbeat` (round to whole minutes or hours). Determine `status` from the record's `status` field: `running` if `status == "running"`, `stale` if `status == "stale"` or if `last_heartbeat` is more than 30 minutes old.

Render as a table:

```
Active plans: <N>

slug               command            phase     branch         current_task  age     status
---------          -------            -----     ------         ------------  ---     ------
<slug>             <command>          <phase>   <branch>       <task>        <Xm>    running
<slug>             <command>          <phase>   <branch>       (none)        <Xh>    stale
```

- Truncate long values to fit: slug/command 20 chars, branch 15 chars, current_task 12 chars.
- If no records → print `Active plans: 0 — no active plans registered.`
- If `age` < 60 s → show `<N>s`; if < 3600 s → show `<N>m`; else show `<N>h`.

## Phase 2 — Overlap with current run (best-effort)

Parse `--run-id <id>` from `$ARGUMENTS` if present. Also check environment variable `Z_HARNESS_RUN_ID`.

```bash
# Extract --run-id from $ARGUMENTS if present
_zh_run_id="$(echo "$ARGUMENTS" | grep -oP '(?<=--run-id\s)\S+' || true)"
# Fall back to environment variable
if [ -z "$_zh_run_id" ]; then
  _zh_run_id="${Z_HARNESS_RUN_ID:-}"
fi
```

**If a run-id is available:**

```bash
_zh_overlaps="$(python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/active-plan-registry.py" overlaps --run-id "$_zh_run_id" 2>/dev/null)"
_zh_overlap_exit=$?
```

Render:

- Exit code 0 → `Overlaps: none (no shared paths with other active plans)`
- Exit code 10 → parse and display the human-readable overlap output returned by the registry
- Exit code 20 → display the overlap output and prepend `[BLOCKING] ` to the section header
- Non-zero exit other than 10/20 → `Overlaps: (registry error — could not compute)`

**If no run-id is available:**

Print:

```
Overlaps: pass --run-id <id> or set Z_HARNESS_RUN_ID to see path-overlap with a specific active run.
          (The active plan list above shows all concurrent runs regardless.)
```

## Hard rules

- **READ ONLY.** Never edit any file. Never write to `metrics.jsonl` or any archive.
- **No subagent dispatch.** This command must run instantly (≤2s wall time).
- **No LLM API calls.** Just shell + Python against the existing registry.
- **Robust to registry unavailability.** If the registry is absent or empty, print a clear message and exit cleanly — never error out.
- Do not log a start/end event for `/z-where` itself.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | no | — |
| `skill_invoke` | no | — |

This command has no gated blocks; it runs in any driver that supports Bash execution.
