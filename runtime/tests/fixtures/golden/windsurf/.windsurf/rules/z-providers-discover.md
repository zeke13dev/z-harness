---
trigger: model_decision
description: "Discover LLM CLI providers in PATH and generate providers.json."
---

You are running the **z-harness `/z-providers-discover`** command.

This command probes your PATH for known LLM CLIs (`codex`, `gemini`, `claude`, `ollama`, `agy`, `gpt`), proposes a `providers.json` configuration, asks the user to bind roles, enforces `consultant_primary ≠ consultant_secondary`, then atomically writes the file.

## Procedure

### Step 1 — Probe PATH and show proposal

Run the discovery script:

```bash
python3 "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/discover-providers.py"
```

Capture the JSON output as `$PROPOSAL`. Display it to the user so they can review what was detected.

### Step 2 — Choose write target

Check whether `--repo` was passed as an argument to this command.

- Default (no `--repo`): `TARGET_PATH="$HOME/.config/z-harness/providers.json"`
- With `--repo`: `TARGET_PATH=".z-harness/providers.json"` (relative to repo root)

Tell the user which target will be written.

### Step 3 — Bind roles interactively

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the per-CLI role-binding multi-select question via their native channel. Silent omission is forbidden. -->
For **each detected CLI** in the discovered providers list, use `AskUserQuestion` with a multiSelect to ask which roles to bind to it. Present all three role names as options:

- `consultant_primary`
- `consultant_secondary`
- `reviewer`

Example prompt for a CLI named `codex`:
> Which roles should be bound to **codex**? (select all that apply)
> Options: `consultant_primary`, `consultant_secondary`, `reviewer`, `(none)`

Collect all answers. Build a `roles` map by taking the **last assignment wins** if the same role is selected for multiple CLIs — but flag conflicts to the user.

### Step 4 — Enforce `consultant_primary ≠ consultant_secondary`

After collecting all role bindings, check: if `roles.consultant_primary` and `roles.consultant_secondary` are both set **and** point to the same provider name, the assignment is invalid.

When a collision is detected:
1. Tell the user: "consultant_primary and consultant_secondary must be different providers. Currently both are bound to `<name>`."
<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface the consultant_secondary collision-resolution question via their native channel. Silent omission is forbidden. -->
2. Use `AskUserQuestion` to reprompt: ask the user to choose a **different** provider for `consultant_secondary` from the remaining detected CLIs (excluding the one already bound to `consultant_primary`).
3. Repeat the collision check until the constraint is satisfied or the user picks `(none)` for one of the roles.

### Step 5 — Build final JSON

Merge the user's role bindings into the proposal:

```python
proposal["roles"] = role_bindings  # role_bindings built in steps 3–4
```

The final JSON must conform to schema version 1:
```json
{
  "version": 1,
  "providers": { ... },
  "roles": {
    "consultant_primary": "<provider-name>",
    "consultant_secondary": "<provider-name>",
    "reviewer": "<provider-name>"
  }
}
```

Omit any role key that the user left unbound (do not emit null values).

### Step 6 — Atomic write

Create the parent directory if it does not exist, then write atomically using a tmpfile + rename so no reader ever sees a partial file:

```bash
python3 - <<'PYEOF'
import json, os, tempfile, pathlib

target = os.environ["Z_PROVIDERS_TARGET"]
payload = os.environ["Z_PROVIDERS_JSON"]

path = pathlib.Path(target)
path.parent.mkdir(parents=True, exist_ok=True)

data = json.loads(payload)

# Write to sibling tmpfile then rename atomically
fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".providers-tmp-")
try:
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
except Exception:
    os.unlink(tmp)
    raise

print(f"Written: {path}")
PYEOF
```

Set `Z_PROVIDERS_TARGET` to `$TARGET_PATH` and `Z_PROVIDERS_JSON` to the final JSON string before running.

### Step 7 — Emit event

```bash
DETECTED_LIST=$(echo "$PROPOSAL" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(list(d['providers'].keys())))")
ROLE_BINDINGS=$(echo "$FINAL_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('roles', {})))")

bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" providers_discovered \
  "$(printf '{"detected":%s,"written_to":"%s","role_bindings":%s}' \
     "$DETECTED_LIST" "$TARGET_PATH" "$ROLE_BINDINGS")"
```

Tell the user: "providers.json written to `$TARGET_PATH`."

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | no | — |
| `ask_user` | yes | Step 3 per-CLI role-binding multi-select; Step 4 consultant_secondary collision resolution |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
