# Cursor Export — Capabilities

This document describes what is and is not supported when running z-harness
rules inside Cursor.

---

## Supported

- All prose instructions, heuristics, and workflow steps defined in command,
  agent, and skill source files are included verbatim in the exported `.mdc`
  rules.
- Markdown formatting (headers, lists, code blocks, tables) is preserved as-is.
- File-path patterns and shell command examples are preserved.
- YAML frontmatter (`description`, `alwaysApply`, optional `globs`) is
  populated from the source file frontmatter where available.

---

## Unsupported

The following Claude Code / Anthropic-specific constructs **cannot be
represented natively in Cursor rules** and have been elided or replaced with
inline comments in the exported `.mdc` files:

| Construct | Reason | Replacement in export |
|-----------|--------|----------------------|
| `Agent(subagent_type=..., ...)` | Native subagent dispatch is a Claude Code concept; Cursor has no equivalent. | Replaced with `<!-- agent dispatch / skill invocation not supported in Cursor; see CAPABILITIES.md -->` |
| `Skill(name=..., ...)` | Skill invocation is a Claude Code plugin primitive. | Same replacement comment. |
| `AskUserQuestion(...)` | Anthropic tool-use schema call; not available in Cursor. | Same replacement comment. |
| `TaskCreate(...)` | Anthropic tool-use schema call. | Same replacement comment. |
| Subagent model selection (`model: haiku/sonnet/opus`) | Cursor manages its own model selection; frontmatter `model` key is dropped. | Not emitted. |
| Push notifications / scheduled wakeups | No equivalent in Cursor. | Not emitted. |
| `scripts/log-phase.sh` / `scripts/log-event.sh` telemetry | Relies on z-harness plugin infrastructure not present in Cursor. | Preserved as prose/code blocks but will not execute automatically. |
| Provider registry (`scripts/resolve-provider.sh`) | CLI-dispatch infrastructure specific to z-harness plugin. | Preserved as prose; user must manually invoke. |

---

## Notes

- The `.mdc` rules are **best-effort** translations. They give Cursor's AI the
  same procedural knowledge encoded in the z-harness commands and agents, but
  the AI will not have access to the plugin infrastructure that makes z-harness
  fully automated in Claude Code.
- For full automation (subagent dispatch, telemetry, provider routing), use the
  z-harness plugin in Claude Code (`claude --dangerously-skip-permissions` or
  standard plugin install).
- These exports are regenerated from source by running:
  ```
  python3 scripts/export-cursor.py
  ```
  from the repository root. Re-run after updating any `commands/`, `agents/`,
  or `skills/` file to keep the exports current.
- Bug reports for the Cursor export: file an issue in the z-harness repository
  and tag it `cursor-export`.
