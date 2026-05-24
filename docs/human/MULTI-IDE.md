# MULTI-IDE — Exporting z-harness to Cursor, Codex CLI, and Antigravity

> Last updated: 2026-05-24

## Overview

z-harness source of truth lives in Claude Code format (`commands/*.md`,
`agents/*.md`, `skills/*/SKILL.md`). The multi-IDE export pipeline translates
this source into IDE-specific formats under `exports/` so that Cursor,
Codex CLI, and Antigravity (agy) users can run the same workflows.

---

## Export targets

| Target | Output dir | Format |
|--------|-----------|--------|
| `cursor` | `exports/cursor/` | `.cursor/rules/*.mdc` + README.md |
| `codex` | `exports/codex/` | `AGENTS.md` + `prompts/*.md` + README.md |
| `agy` | `exports/agy/` | `agy-plugin.yaml` + `prompts/*.md` + README.md |

Each target also contains a `CAPABILITIES.md` that documents which Claude Code
constructs are not representable in that IDE and how they were handled.

---

## Running an export

### Via /z-export (recommended)

From any Claude Code session with z-harness loaded:

```
/z-export --target=cursor
/z-export --target=codex
/z-export --target=agy
/z-export                    # exports all three targets
```

`/z-export` runs the corresponding Python adapter script, reports per-target
success or failure, and never aborts early — a single target failure does not
skip the remaining targets.

### Via Python scripts directly

```bash
python3 scripts/export-cursor.py
python3 scripts/export-codex.py
python3 scripts/export-agy.py
```

All three scripts share `scripts/export-common.py` for source-file
enumeration, CAPABILITIES.md schema validation, and filter logic.

---

## Per-target CAPABILITIES.md

Each target's `CAPABILITIES.md` records what was translated and what was
dropped. Read it before using the exported files to understand the fidelity
boundaries.

Paths:

- `exports/cursor/CAPABILITIES.md`
- `exports/codex/CAPABILITIES.md`
- `exports/agy/CAPABILITIES.md`

Common unsupported constructs across all non-Claude-Code targets:

| Construct | Reason |
|-----------|--------|
| `Agent(subagent_type=...)` | Native subagent dispatch is a Claude Code primitive |
| `Skill(name=...)` | Skill invocation is a Claude Code plugin primitive |
| `AskUserQuestion(...)` | Anthropic tool-use schema; not available in other IDEs |

When a source file contains these constructs, the export adapter replaces them
with an inline comment explaining the limitation. Refer to the target's
`CAPABILITIES.md` for the full list.

---

## Cursor

The Cursor export produces `.mdc` rule files under
`exports/cursor/.cursor/rules/`. Each source file (command, agent, skill) gets
its own `.mdc` file.

### Install instructions for Cursor

1. Run `/z-export --target=cursor` (or `python3 scripts/export-cursor.py`).
2. Copy or symlink `exports/cursor/.cursor/rules/` into your project:
   ```bash
   cp -r exports/cursor/.cursor /path/to/your/project/
   ```
3. Open the project in Cursor. The rules load automatically.

---

## Codex CLI

The Codex export produces:

- `exports/codex/AGENTS.md` — consolidated agent definitions.
- `exports/codex/prompts/*.md` — one file per command.

### Install instructions for Codex CLI

1. Run `/z-export --target=codex` (or `python3 scripts/export-codex.py`).
2. Copy `exports/codex/AGENTS.md` and `exports/codex/prompts/` to your repo:
   ```bash
   cp exports/codex/AGENTS.md /path/to/your/project/
   cp -r exports/codex/prompts /path/to/your/project/
   ```
3. Reference the prompt files in your Codex CLI invocations.

---

## Antigravity (agy)

The agy export produces:

- `exports/agy/agy-plugin.yaml` — plugin manifest.
- `exports/agy/prompts/*.md` — one file per command.

### Install instructions for Antigravity

1. Run `/z-export --target=agy` (or `python3 scripts/export-agy.py`).
2. Copy the output to your agy plugin directory:
   ```bash
   cp -r exports/agy/ ~/.agy/plugins/z-harness/
   ```
3. The plugin is loaded on the next agy session start.

Refer to `exports/agy/CAPABILITIES.md` for agy-specific translation notes.

---

## Export filter — what is excluded

The export scripts never include:

- `providers.json` or `.z-harness/` (contains credentials and local paths)
- `z-harness/plans/` or `z-harness/archive/` (run artifacts)
- Anything under `~/` (home directory paths)

This filter is enforced by `scripts/audit-tarball.sh`, which the CI pipeline
runs after every export build.

---

## Keeping exports up to date

Exports are not automatically regenerated when source files change. Re-run
`/z-export` (or the per-target script) whenever you update commands, agents,
or skills.

The `scripts/export-common.py` shared library handles path enumeration, so
new source files are picked up automatically on the next export run without
changes to the adapter scripts.
