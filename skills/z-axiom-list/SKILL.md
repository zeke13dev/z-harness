---
name: z-axiom-list
description: List axiom records from the store, rendered as a readable table. Supports filtering by status, scope, and discipline.
argument-hint: [--status <candidate|approved|rejected>] [--scope <global|project>] [--discipline <tag>] [--repo-root <path>]
---

You are running **z-harness `/z-axiom-list`**. Read-only. Renders `axiom-store.py list` output as a human-readable table.

## Phase 0 — Parse arguments

Parse `$ARGUMENTS`:

- `--status <candidate|approved|rejected>` — filter by status. Optional; omit to show all.
- `--scope <global|project>` — filter by scope. Optional; omit to show global+project merged (project shadows global on same id).
- `--discipline <tag>` — filter by discipline tag. Optional.
- `--repo-root <path>` — override repo root. Optional.

Build the `axiom-store.py list` invocation:

```bash
CMD="python3 scripts/axiom-store.py list"
[[ -n "$STATUS_ARG" ]]     && CMD="$CMD --status $STATUS_ARG"
[[ -n "$SCOPE_ARG" ]]      && CMD="$CMD --scope $SCOPE_ARG"
[[ -n "$DISCIPLINE_ARG" ]] && CMD="$CMD --discipline $DISCIPLINE_ARG"
[[ -n "$REPO_ROOT_ARG" ]]  && CMD="$CMD --repo-root $REPO_ROOT_ARG"
```

## Phase 1 — Run axiom-store.py list

```bash
RESULT="$(eval "$CMD" 2>&1)"
EXIT_CODE=$?
```

If exit code is non-zero, print the error output and stop.

Parse the result as a JSON array:
```python
import json
records = json.loads(result)  # array of axiom record objects
```

If the array is empty:
- Print: "No axiom records found matching the given filters."
- Exit cleanly.

## Phase 2 — Render as table

Print a human-readable table. Each row is one axiom record.

```
Axioms (<n> records)  scope=<scope_filter|all>  status=<status_filter|all>  discipline=<disc_filter|any>

ID          STATUS      SCOPE    CONF   DISCIPLINE  STATEMENT
---------   ---------   -------  -----  ----------  ----------------------------------------
ax-1a2b3c4d candidate   global   0.82   engineering Prefer separate explicit slash commands…
ax-5e6f7a8b approved    project  0.91   —           Always emit a kernel_regen event on approve…
ax-9c0d1e2f rejected    global   0.60   —           Use flag-routed modes for simple options…
```

Column definitions:
- **ID** — the axiom id (`ax-<8hex>`), left-aligned, 11 chars wide.
- **STATUS** — `candidate`, `approved`, or `rejected`, 9 chars wide.
- **SCOPE** — `global` or `project`, 7 chars wide.
- **CONF** — `confidence` rounded to 2 decimal places, 5 chars wide.
- **DISCIPLINE** — `discipline` field, or `—` if absent, 10 chars wide.
- **STATEMENT** — `statement` field, truncated to 60 chars with `…` if longer.

After the table, print a footer:

```
Total: <n>  (candidate: <c>  approved: <a>  rejected: <r>)

Next steps:
  /z-axiom-approve <id>   — approve a candidate (regens kernel)
  /z-axiom-reject <id>    — reject a candidate
  /z-axiom-edit <id> --set <field>=<value>   — edit a record
```

## STATUS lines from axiom-store.py list

`axiom-store.py list` emits a JSON array to stdout. Each element is an axiom record object. The command renders it; no additional STATUS lines are defined for the list subcommand.

## Hard rules

- **Read-only.** Never write to the store or any file.
- **No subagent dispatch.** This command runs instantly with a single `axiom-store.py list` call.
