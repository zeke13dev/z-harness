# z-harness — Capabilities Overview

z-harness is an AI-assisted software-development workflow harness built on
Anthropic's Claude Code SDK.  It ships slash commands, subagent definitions,
and skills that orchestrate common dev tasks (planning, implementing,
reviewing, auditing, exporting).

## This is a *pointer* export

Only this single rule file has been written to `.clinerules/`.  Cline loads
every rule file in `.clinerules/` on every prompt, so the z-harness default
strategy avoids bloating your context with 100+ files.

## How to invoke z-harness

z-harness commands are invoked as slash commands in the Cline chat interface.
Type `/z-<command>` to trigger a command, e.g.:

- `/z-plan`              — plan a feature or refactor
- `/z-implement-all`     — implement all tasks in a TASKS.md plan
- `/z-audit-plan`        — audit an existing TASKS.md plan
- `/z-review`            — run a post-implementation review pass
- `/z-export`            — export z-harness to IDE rule files
- `/z-debt`              — harvest z: debt markers from the codebase
- `/z-debug`             — iterative debug ladder

## Subagent / skill dispatch

Cline does not support native subagent fan-out or skill invocation.  Lines in
<!-- agent dispatch / skill invocation not supported in Cline; invoke z-harness slash commands manually in the Cline chat -->
<!-- agent dispatch / skill invocation not supported in Cline; invoke z-harness slash commands manually in the Cline chat -->
to handle those actions manually within the Cline chat.

<!-- agent dispatch / skill invocation not supported in Cline; see this file -->

## Expanding to more rules

Set `strategy = "curated"` or `strategy = "full"` in `config.toml` under
`[export]` and re-run `/z-export` (or `python3 scripts/export.py --target cline`)
to populate `.clinerules/` with the always-on agent subset or the full rule
set respectively.

## More information

- **Repository:** https://github.com/anthropics/z-harness
- **Commands:** `commands/` directory in the repository root
- **Agents:** `agents/` directory
- **Skills:** `skills/` directory
- **Config:** `config.toml` (see `scripts/config.py ensure-defaults`)
