---
trigger: model_decision
description: "Read-only \"what's active / why am I blocked\" query. Prints resolved base + repo-id, lists all active plans (slug, command, phase, branch, current_task, age, status), and optionally shows path-overlap with the current run. No writes, no LLM calls."
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

slug               command            phase     branch         current_task  hb_age  status    held_paths  waiting_on
---------          -------            -----     ------         ------------  ------  ------    ----------  ----------
<slug>             <command>          <phase>   <branch>       <task>        <Xm>    running   2           (none)
<slug>             <command>          <phase>   <branch>       (none)        <Xh>    stale     (none)      run-20260605T...
```

Column definitions:
- `hb_age` — heartbeat age: time since `last_heartbeat` (same format as the former `age` column: `<N>s` / `<N>m` / `<N>h`). A large value for a `running` record indicates a wedged-but-alive senior whose leases are still active.
- `held_paths` — count of entries in the record's `held_paths` list (schema v2); show `(none)` if the list is absent or empty. Records with `schema_version < 2` or missing `held_paths` show `(v1)` to signal they are lease-incapable.
- `waiting_on` — first run_id in the record's `waiting_on` list, truncated to 24 chars; show `(none)` if empty or absent. If the list has multiple entries, append `+N` (e.g. `run-abc...+2`).

Formatting:
- Truncate long values to fit: slug/command 20 chars, branch 15 chars, current_task 12 chars.
- If no records → print `Active plans: 0 — no active plans registered.`
- If `age` < 60 s → show `<N>s`; if < 3600 s → show `<N>m`; else show `<N>h`.

## Phase 1b — Wait-edge graph

Render wait-edges immediately after the table. Collect every `waiting_on` entry from all records and
render one edge per (waiter, target) pair:

```
Wait edges:
  <run_id_A> ──waits──▶ <run_id_B>
  <run_id_A> ──waits──▶ <run_id_C>
```

- Use the record's `run_id` field for both ends of the edge (not slug — run_id is the unique identity).
- If no record has a non-empty `waiting_on`, print `Wait edges: (none)` on a single line.
- If a `waiting_on` target does not appear in the active-plan list, append `[gone]` to the target:
  `<run_id_A> ──waits──▶ <run_id_B> [gone]` (the target deregistered while the waiter is still
  parked — it should clear on the next `wait-for` poll, but is eyeball-diagnosable here).
- Do not resolve wait-edge cycles (cycles are impossible by design — wait edges are DAG by run_id
  ordering — but do not error if a pathological record claims one; just render as-is).

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
