Ripgrep is not available. Falling back to GrepTool.
Error stating path -", "--approval-mode", "plan", "--output-format", "text"],
      "stdin": false,
      "timeout_s": 240,
      "model_label": "gemini-2.5-pro"
    }
  },
  "roles": {
    "consultant_primary":   "my-gemini",
    "consultant_secondary": "my-codex",
    "reviewer":             "my-codex"
  }
}
```

---

## Discovery command

Run `/z-providers-discover` to auto-detect installed LLM CLIs and generate a
starter `providers.json`.  The command probes your `PATH` for `codex`, `gemini`,
`claude`, `ollama`, `agy`, and `gpt`; shows the proposed config; and asks which
roles to bind before writing.

For CLIs not in the auto-detect list, add them manually following the schema
above.

---

## Adding a custom CLI provider

1. Write a wrapper script that reads the prompt from stdin (or a named arg) and
   prints the response to stdout.  Exit 0 on success, nonzero on failure.
2. Put it on your `PATH` (or supply an absolute path as `command`).
3. Add a stanza under `providers` in your `~/.config/z-harness/providers.json`.
4. Bind a role in the `roles` map.

Example wrapper skeleton:

```bash
#!/usr/bin/env bash
# my-llm-wrapper — reads prompt from stdin, writes response to stdout
PROMPT="$: ENAMETOOLONG: name too long, stat '/Users/zeke/dev/z-harness/-", "--approval-mode", "plan", "--output-format", "text"],
      "stdin": false,
      "timeout_s": 240,
      "model_label": "gemini-2.5-pro"
    }
  },
  "roles": {
    "consultant_primary":   "my-gemini",
    "consultant_secondary": "my-codex",
    "reviewer":             "my-codex"
  }
}
```

---

## Discovery command

Run `/z-providers-discover` to auto-detect installed LLM CLIs and generate a
starter `providers.json`.  The command probes your `PATH` for `codex`, `gemini`,
`claude`, `ollama`, `agy`, and `gpt`; shows the proposed config; and asks which
roles to bind before writing.

For CLIs not in the auto-detect list, add them manually following the schema
above.

---

## Adding a custom CLI provider

1. Write a wrapper script that reads the prompt from stdin (or a named arg) and
   prints the response to stdout.  Exit 0 on success, nonzero on failure.
2. Put it on your `PATH` (or supply an absolute path as `command`).
3. Add a stanza under `providers` in your `~/.config/z-harness/providers.json`.
4. Bind a role in the `roles` map.

Example wrapper skeleton:

```bash
#!/usr/bin/env bash
# my-llm-wrapper — reads prompt from stdin, writes response to stdout
PROMPT="$'
Error stating path zeke-tools": true }
}
```

---

## /z-update — refreshing the install

`/z-update` is the in-Claude-Code command for keeping z-harness current. It
detects install mode and takes the appropriate update path.

**Symlink mode:** runs `git -C <plugin-path> pull --ff-only`. If the repo has
uncommitted changes, it aborts and prints `git status`; resolve the changes,
then re-run `/z-update`.

**Tarball mode:** HEAD-checks the release URL, compares version strings, and
performs an atomic swap if a newer version is found. Rolls back automatically
on any swap failure.

After a successful update, both modes emit a `harness_updated` event to
`z-harness/metrics.jsonl` with `old_version` and `new_version`.

```
[z-update] Updated successfully.
  old: abc1234
  new: def5678
```

### Environment variable

| Variable | Default | Purpose |
|---|---|---|
| `Z_HARNESS_RELEASE_URL` | placeholder | Override the tarball release URL for `/z-update` in tarball mode |

---

## Distribution model

z-harness has **no autoupdate mechanism**. Updates are explicit — either a
`git pull` in your clone, or `/z-update` inside Claude Code. This is
intentional: autoupdate in a tool that rewrites production code would be a
footgun.

---

## Uninstall

```bash
rm ~/.claude/plugins/z-harness@zeke-tools
```

If you installed via tarball, this removes the extracted directory. If you
installed via symlink, this removes only the symlink — the local clone is
untouched.
--- END NEW FILE: docs/human/INSTALL.md ---

--- BEGIN NEW FILE: docs/human/MULTI-IDE.md ---
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
--- END NEW FILE: docs/human/MULTI-IDE.md ---

--- BEGIN NEW FILE: docs/human/PLAN-LAYOUT.md ---
# PLAN-LAYOUT — Plan Directory Layout and Migration Guide

> Last updated: 2026-05-24

## Overview

Plan output is namespaced under `z-harness/plans/<slug>/`. This is the
canonical layout since the portable-harness restructure. The legacy path
(`z-harness/<slug>/`) is supported as a read-only fallback so existing plans
continue to work without immediate migration.

---

## Canonical layout

```
z-harness/
└── plans/
    └── <slug>/
        ├── SPEC.md
        ├── PLAN.md
        ├── TASKS.md
        ├── TESTS.md              (if /z-test was run)
        ├── BRAINSTORM.md         (if /z-brainstorm was run)
        ├── RESEARCH.md           (if /z-research was run)
        ├── archive/
        │   └── <run-id>/
        │       └── events.jsonl
        └── improvements/
```

---

## Z_HARNESS_PLANS_DIR override

The plans root directory can be overridden with the `Z_HARNESS_PLANS_DIR`
environment variable:

```bash
Z_HARNESS_PLANS_DIR=/tmp/my-plans /z-plan my-task
```

When set, the variable is used verbatim — no normalization or relative
expansion. This is the recommended way to isolate plans in CI or test
environments.

Default (variable unset): `z-harness/plans`

---

## Dual-read fallback

All commands try the new path first. If the new path does not exist, they fall
back to the legacy path and emit a one-line warning:

```
[plan-path] WARNING: using legacy path z-harness/<slug>/ — run:
  bash scripts/migrate-plan-layout.sh <slug>
```

This fallback is read-only: commands never write new artifacts to the legacy
path. Once a plan has been migrated, the fallback warning disappears.

The `scripts/plan-path.sh` helper exposes two functions used by all commands:

```bash
plan_dir <slug>         # echoes ${Z_HARNESS_PLANS_DIR:-z-harness/plans}/<slug>
legacy_plan_dir <slug>  # echoes z-harness/<slug>
```

---

## Migrating existing plans

### Single slug

```bash
bash scripts/migrate-plan-layout.sh my-slug
```

This moves `z-harness/my-slug/` to `z-harness/plans/my-slug/`. The operation
is idempotent: if the plan is already at the new path, the script exits with
a success message and does nothing.

### All plans at once

```bash
bash scripts/migrate-plan-layout.sh --all
```

Scans `z-harness/` for any subdirectory that contains `PLAN.md`, `SPEC.md`,
or `TASKS.md` at its root and migrates each one.

### Dry run

```bash
bash scripts/migrate-plan-layout.sh --dry-run my-slug
bash scripts/migrate-plan-layout.sh --all --dry-run
```

Prints what would be moved without making any changes. Combine with `--all`
to preview a bulk migration.

### Safety

- The script refuses to overwrite an existing directory at the new path. If
  `z-harness/plans/<slug>/` already exists and is non-empty, it exits with an
  error showing the diff.
- Nothing inside the moved files is rewritten — path construction is
  runtime-resolved via `Z_HARNESS_PLANS_DIR`.
- A `migration_done` event per slug is logged to `z-harness/metrics.jsonl`.

---

## Summary of affected commands

Every command that constructs plan-relative paths uses `scripts/plan-path.sh`.
The affected list includes: `z-plan`, `z-plan-light`, `z-plan-split`,
`z-amend`, `z-implement-all`, `z-implement-next`, `z-debug`, `z-fix`,
`z-improve`, `z-research`, `z-brainstorm`, `z-audit`, `z-test`,
`z-maintain-docs`, `z-mr-review`, `z-style-init`, `z-stats`, `z-review-all`,
`z-do`, `z-skill-fix`, `z-init-docs`.

Scripts that also respect `Z_HARNESS_PLANS_DIR`: `scripts/log-event.sh`,
`scripts/log-phase.sh`.
--- END NEW FILE: docs/human/PLAN-LAYOUT.md ---

--- BEGIN NEW FILE: docs/llm/providers-registry.json ---
{
  "slug": "providers-registry",
  "summary": "Config-file-based: ENAMETOOLONG: name too long, stat '/Users/zeke/dev/z-harness/zeke-tools": true }
}
```

---

## /z-update — refreshing the install

`/z-update` is the in-Claude-Code command for keeping z-harness current. It
detects install mode and takes the appropriate update path.

**Symlink mode:** runs `git -C <plugin-path> pull --ff-only`. If the repo has
uncommitted changes, it aborts and prints `git status`; resolve the changes,
then re-run `/z-update`.

**Tarball mode:** HEAD-checks the release URL, compares version strings, and
performs an atomic swap if a newer version is found. Rolls back automatically
on any swap failure.

After a successful update, both modes emit a `harness_updated` event to
`z-harness/metrics.jsonl` with `old_version` and `new_version`.

```
[z-update] Updated successfully.
  old: abc1234
  new: def5678
```

### Environment variable

| Variable | Default | Purpose |
|---|---|---|
| `Z_HARNESS_RELEASE_URL` | placeholder | Override the tarball release URL for `/z-update` in tarball mode |

---

## Distribution model

z-harness has **no autoupdate mechanism**. Updates are explicit — either a
`git pull` in your clone, or `/z-update` inside Claude Code. This is
intentional: autoupdate in a tool that rewrites production code would be a
footgun.

---

## Uninstall

```bash
rm ~/.claude/plugins/z-harness@zeke-tools
```

If you installed via tarball, this removes the extracted directory. If you
installed via symlink, this removes only the symlink — the local clone is
untouched.
--- END NEW FILE: docs/human/INSTALL.md ---

--- BEGIN NEW FILE: docs/human/MULTI-IDE.md ---
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
--- END NEW FILE: docs/human/MULTI-IDE.md ---

--- BEGIN NEW FILE: docs/human/PLAN-LAYOUT.md ---
# PLAN-LAYOUT — Plan Directory Layout and Migration Guide

> Last updated: 2026-05-24

## Overview

Plan output is namespaced under `z-harness/plans/<slug>/`. This is the
canonical layout since the portable-harness restructure. The legacy path
(`z-harness/<slug>/`) is supported as a read-only fallback so existing plans
continue to work without immediate migration.

---

## Canonical layout

```
z-harness/
└── plans/
    └── <slug>/
        ├── SPEC.md
        ├── PLAN.md
        ├── TASKS.md
        ├── TESTS.md              (if /z-test was run)
        ├── BRAINSTORM.md         (if /z-brainstorm was run)
        ├── RESEARCH.md           (if /z-research was run)
        ├── archive/
        │   └── <run-id>/
        │       └── events.jsonl
        └── improvements/
```

---

## Z_HARNESS_PLANS_DIR override

The plans root directory can be overridden with the `Z_HARNESS_PLANS_DIR`
environment variable:

```bash
Z_HARNESS_PLANS_DIR=/tmp/my-plans /z-plan my-task
```

When set, the variable is used verbatim — no normalization or relative
expansion. This is the recommended way to isolate plans in CI or test
environments.

Default (variable unset): `z-harness/plans`

---

## Dual-read fallback

All commands try the new path first. If the new path does not exist, they fall
back to the legacy path and emit a one-line warning:

```
[plan-path] WARNING: using legacy path z-harness/<slug>/ — run:
  bash scripts/migrate-plan-layout.sh <slug>
```

This fallback is read-only: commands never write new artifacts to the legacy
path. Once a plan has been migrated, the fallback warning disappears.

The `scripts/plan-path.sh` helper exposes two functions used by all commands:

```bash
plan_dir <slug>         # echoes ${Z_HARNESS_PLANS_DIR:-z-harness/plans}/<slug>
legacy_plan_dir <slug>  # echoes z-harness/<slug>
```

---

## Migrating existing plans

### Single slug

```bash
bash scripts/migrate-plan-layout.sh my-slug
```

This moves `z-harness/my-slug/` to `z-harness/plans/my-slug/`. The operation
is idempotent: if the plan is already at the new path, the script exits with
a success message and does nothing.

### All plans at once

```bash
bash scripts/migrate-plan-layout.sh --all
```

Scans `z-harness/` for any subdirectory that contains `PLAN.md`, `SPEC.md`,
or `TASKS.md` at its root and migrates each one.

### Dry run

```bash
bash scripts/migrate-plan-layout.sh --dry-run my-slug
bash scripts/migrate-plan-layout.sh --all --dry-run
```

Prints what would be moved without making any changes. Combine with `--all`
to preview a bulk migration.

### Safety

- The script refuses to overwrite an existing directory at the new path. If
  `z-harness/plans/<slug>/` already exists and is non-empty, it exits with an
  error showing the diff.
- Nothing inside the moved files is rewritten — path construction is
  runtime-resolved via `Z_HARNESS_PLANS_DIR`.
- A `migration_done` event per slug is logged to `z-harness/metrics.jsonl`.

---

## Summary of affected commands

Every command that constructs plan-relative paths uses `scripts/plan-path.sh`.
The affected list includes: `z-plan`, `z-plan-light`, `z-plan-split`,
`z-amend`, `z-implement-all`, `z-implement-next`, `z-debug`, `z-fix`,
`z-improve`, `z-research`, `z-brainstorm`, `z-audit`, `z-test`,
`z-maintain-docs`, `z-mr-review`, `z-style-init`, `z-stats`, `z-review-all`,
`z-do`, `z-skill-fix`, `z-init-docs`.

Scripts that also respect `Z_HARNESS_PLANS_DIR`: `scripts/log-event.sh`,
`scripts/log-phase.sh`.
--- END NEW FILE: docs/human/PLAN-LAYOUT.md ---

--- BEGIN NEW FILE: docs/llm/providers-registry.json ---
{
  "slug": "providers-registry",
  "summary": "Config-file-based'
## Prong A — Drift
### Blocker
- Because the implementer created `scripts/log-providers.sh` but never actually injected calls to it into the dispatching commands (`z-plan.md`, `z-debug.md`, `z-implement-all.md`, etc.), the spec's mandate for "Run-start observability" (logging a `provider_resolved` event and printing a stdout summary) is completely dead code.

### Major
- Because the generated Cursor `.mdc` rules and Codex/Agy prompts are absent from the `cumulative.stat` and untracked file lists, the pipeline failed the explicit spec requirement to "actually commit the generated tree so users can git clone and use", meaning users cloning the repo will not receive the exported IDE rules out-of-the-box.
- Because `commands/z-amend.md` and `commands/z-stats.md` reference `$Z_HARNESS_PLAN_DIR` without ever defining it or calling the `scripts/plan-path.sh` helper to resolve it, these commands will evaluate the base path to empty or literal strings, breaking their directory resolution entirely.
- Because there are no test scripts or fixture files added for the provider resolution logic in the cumulative diff, the T005 acceptance criterion demanding "Tests against fixture providers.json" was completely ignored.

### Minor
- Because the implementer skipped creating `scripts/export-all.sh` and instead wired the batch-export iteration loop directly into the `z-export.md` command, the batch-export functionality defined in the spec is unavailable outside of an active Claude Code session.
- Because the consultant agents construct transcript filenames using `$MODE` instead of the spec-mandated `<topic>`, the resulting transcript logs will not group chronologically by user topic as intended.

## Prong B — Spec gaps
### Blocker
- Because macOS (`darwin`) does not include the GNU `timeout` command natively, the spec's decision to mandate a `timeout_s` registry field and execute it via the bare `timeout` command will fatally crash the `consultant-primary`, `consultant-secondary`, and `reviewer` agents for all Mac users.
- Because the exclusion rules for `bundle-plugin.sh` and the `audit-tarball.sh` script only explicitly target `z-harness/plans/` and `z-harness/archive/`, the spec fails to protect legacy plan directories (`z-harness/<slug>/`), meaning bundling a tarball on an unmigrated repo will silently leak the user's private pre-migration plans into the distribution.

### Major
- Because `scripts/plan-path.sh` is invoked by commands via command substitution (`$(bash scripts/plan-path.sh ...)`), the spec's `export Z_HARNESS_LEGACY_WARNED=1` mechanism occurs inside an ephemeral subshell, causing the env-guard to evaporate and the dual-read fallback warning to spam the user on every path resolution instead of "ONCE per run".

### Minor
- Because there are no headless harnesses or CLI surfaces available to programmatically "load and execute" files within the Cursor UI or Antigravity IDE, the spec's demand for an automated "Smoke-test gate" verified in the target IDE cannot be satisfied by autonomous agent execution.
- Because the spec dictates resolving the user-global config strictly at `~/.config/z-harness/providers.json`, it fails to respect the `$XDG_CONFIG_HOME` standard, causing custom XDG configurations to be silently ignored.
