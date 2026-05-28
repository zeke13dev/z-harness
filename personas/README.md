# z-harness Personas

A persona is a saved prompt-prefix preset that shapes the tone, style, and
output contract of an agent invocation. Personas are orthogonal to model and
runtime — you bind all three independently per (command, role) in your TOML
config.

## File Format

Persona files are Markdown with a YAML frontmatter block:

```markdown
---
name: my-persona
description: One-line summary of what this persona does.
compatible_roles: [consultant_primary]   # optional
contract: freeform                        # optional: freeform | review-verdict | strict-json
---

The body of the file is the prompt prefix. It is prepended verbatim before the
role's task prompt at dispatch time. Write it in plain markdown.
```

### Frontmatter fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | yes | string | Kebab-case identifier. Must match `^[a-z][a-z0-9-]*$` — starts with a lowercase letter, contains only lowercase letters, digits, and hyphens, no trailing hyphen. |
| `description` | yes | string | One-line human-readable description. |
| `compatible_roles` | no | list of strings | Soft hint: which roles this persona is designed for. Mismatch emits a `persona_compat_warning` event but does not block binding. |
| `contract` | no | enum | Output contract. `freeform` (default if absent), `review-verdict` (expects PASS/FAIL/BLOCKED), `strict-json`. When the bound role declares an `expected_contract`, binding a mismatched persona fails at startup. |

### Name rules

- Must start with a lowercase ASCII letter (`a-z`).
- May contain lowercase letters, digits (`0-9`), and hyphens (`-`).
- No uppercase letters, dots (`.`), slashes (`/`), underscores (`_`), or spaces.
- No leading or trailing hyphens.

Valid: `codex-default-reviewer`, `gemini-v2`, `a`, `fast-draft`
Invalid: `MyPersona`, `codex.reviewer`, `--bad`, `trailing-`

## Layered Storage

Personas are loaded from three layers in this order (lower index = lower priority):

| # | Layer | Path | Who manages it |
|---|-------|------|----------------|
| 1 | **builtin** | `personas/builtin/` (repo root) | Shipped with z-harness |
| 2 | **user-global** | `~/.config/z-harness/personas/` | User's personal presets |
| 3 | **repo** | `<repo>/.z-harness/personas/` | Per-project overrides |

**Last layer wins per name.** When the same persona name appears in multiple
layers, the highest-priority layer's version is used. A `persona_shadowed`
event is emitted once per (process, name) when a collision is detected.

### Precedence example

If `codex-default-reviewer.md` exists in both `personas/builtin/` and
`~/.config/z-harness/personas/`, the user-global version wins. Add it again
under `<repo>/.z-harness/personas/` and the repo version wins.

```
$ scripts/resolve-persona.py where codex-default-reviewer
/path/to/z-harness/personas/builtin/codex-default-reviewer.md
/home/user/.config/z-harness/personas/codex-default-reviewer.md
/path/to/repo/.z-harness/personas/codex-default-reviewer.md
```

The last line is the winner. `list-personas` will show only that entry.

## CLI Reference

```
# List all personas (one entry per name — winner only):
scripts/resolve-persona.py list-personas

# Show all layers defining a persona name:
scripts/resolve-persona.py where <name>
```

### `list-personas` output shape

```json
[
  {
    "name": "codex-default-reviewer",
    "source_layer": "builtin",
    "path": "/path/to/personas/builtin/codex-default-reviewer.md"
  }
]
```

## Example Persona

`personas/builtin/codex-default-reviewer.md`:

```markdown
---
name: codex-default-reviewer
description: Default Codex reviewer persona — adversarial, blockers/majors only.
compatible_roles: [reviewer]
contract: review-verdict
---

You are an adversarial code reviewer. Your job is to find blockers and major
issues only — not style nits. For every finding, state:

VERDICT: PASS | FAIL | BLOCKED
REASON: <one sentence>

Only FAIL or BLOCKED when there is a concrete, demonstrable problem. If the
implementation meets the spec, return PASS with a brief confirmation.
```

## Authoring Tips

- Keep the body short (under 30 lines). Long system prompts dilute focus.
- Declare `contract` explicitly when the consuming role enforces one.
- Use `compatible_roles` as documentation — it does not prevent binding.
- Prefer builtin personas for stable defaults; use user-global for personal
  style; use repo-local only for project-specific requirements.
