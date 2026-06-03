---
description: "Inspect persona registry, role bindings, and persona files. Subcommands: list, roles, validate, read <name>, where <name>. Default (no args) = roles."
---

You are running the **z-harness `/z-personas`** command.

This command exposes the persona registry and current role bindings. It is read-only — it never writes any file.

Arguments (from `$ARGUMENTS`): `$ARGUMENTS`

## Dispatch

Parse `$ARGUMENTS` to determine the subcommand:

| Argument | Subcommand |
|---|---|
| _(empty)_ | `roles` (default) |
| `roles` | `roles` |
| `list` | `list` |
| `validate` | `validate` |
| `read <name>` | `read` with `<name>` |
| `where <name>` | `where` with `<name>` |

If the argument is unrecognized, print:

```
Usage: /z-personas [list | roles | validate | read <name> | where <name>]
```

…and stop.

---

## Subcommand: `roles` (default)

Show all effective role bindings as a markdown table.

### Step 1 — Fetch bindings JSON

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-persona.py" list-bindings
```

Capture the JSON output as `$BINDINGS`.

### Step 2 — Render table

Parse `$BINDINGS` and render a markdown table with columns:

| command | role | persona | model | runtime |

One row per `(command, role)` pair. Sort rows by command then role.

**Output translation:** convert internal underscore command keys back to slash-command form before printing. Examples:
- `z_plan` → `/z-plan`
- `z_implement_all` → `/z-implement-all`
- `z_review_all` → `/z-review-all`

Rule: replace leading `z_` with `/z-` and replace all remaining `_` with `-`.

If `$BINDINGS` is an empty JSON object `{}` or the list-bindings call returns no data, print:

```
No explicit bindings configured. Run `/z-personas validate` to check default bindings.
```

### Example output

```
| command          | role                 | persona                    | model | runtime   |
|------------------|----------------------|----------------------------|-------|-----------|
| /z-plan          | consultant_primary   | codex-default-consultant   |       | codex-cli |
| /z-plan          | reviewer             | codex-default-reviewer     |       | codex-cli |
| /z-review-all    | reviewer             | codex-default-reviewer     |       | codex-cli |
```

---

## Subcommand: `list`

Show all discovered personas across layers, grouped by layer.

### Step 1 — Fetch personas JSON

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-persona.py" list-personas
```

Capture the JSON array as `$PERSONAS`.

### Step 2 — Render by layer

Group entries by `source_layer`. For each layer in order (builtin first, then user-global, then repo-local), print a section header and a bulleted list of persona names. Example:

```
### builtin
- codex-default-consultant
- codex-default-reviewer
- gemini-default-consultant

### user-global (~/.config/z-harness/personas/)
- my-custom-reviewer

### repo-local (.z-harness/personas/)
_(none)_
```

If a layer has no entries, print `_(none)_`.

---

## Subcommand: `validate`

Run the schema + binding validation pass.

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-persona.py" validate
```

- If the command exits **0**: print `All personas and bindings are valid.`
- If the command exits **non-zero**: print its stdout/stderr output verbatim, then print:

  ```
  Validation failed. Check the errors above.
  Run `/z-personas list` to review discovered personas.
  ```

  Exit with the same non-zero status.

---

## Subcommand: `read <name>`

Print the frontmatter and full body of the named persona.

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-persona.py" read <name>
```

Pass the output through verbatim. If the script exits non-zero (persona not found), display its stderr and suggest:

```
Persona '<name>' not found. Run `/z-personas list` to see available personas.
```

---

## Subcommand: `where <name>`

Show all layers that define the named persona, in load order (lowest priority first).

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/resolve-persona.py" where <name>
```

Pass the output through verbatim. Each line is one layer path. The last line is the winning (highest-priority) layer.

If the script exits non-zero (persona not found in any layer), display its stderr and suggest:

```
Persona '<name>' not found in any layer. Run `/z-personas list` to see available personas.
```

---

## Hard rules

- **READ ONLY.** Never write any file.
- **No subagent dispatch.** All work happens via `resolve-persona.py`.
- Do not log a start/end event — this command is diagnostic and low-cost.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | no | — |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
