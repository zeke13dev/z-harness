# Codex CLI Export — Capabilities

This document describes what is and is not supported when running z-harness
prompts with the Codex CLI (`codex exec`).

---

## Supported

- All prose instructions, heuristics, and workflow steps defined in command,
  agent, and skill source files are included verbatim in the exported prompt
  files.
- Markdown formatting (headers, lists, code blocks, tables) is preserved as-is.
- File-path patterns and shell command examples are preserved.
- Each exported prompt includes a one-line header (`# /<command-id>`) so you
  can identify it at a glance when browsing the `prompts/` directory.
- Agents are documented in `AGENTS.md` for reference when composing multi-step
  workflows manually.

---

## Unsupported

The following Claude Code / Anthropic-specific constructs **cannot be
represented natively in Codex CLI** and have been elided or replaced with
inline comments in the exported prompt files:

| Construct | Reason | Replacement in export |
|-----------|--------|----------------------|
| `Agent(subagent_type=..., ...)` | Native subagent dispatch is a Claude Code concept; Codex CLI has no equivalent. Users must manually sequence prompts. | Replaced with `<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->` |
| `Skill(name=..., ...)` | Skill invocation is a Claude Code plugin primitive with no Codex CLI analogue. | Same replacement comment. |
| `AskUserQuestion(...)` | Anthropic tool-use schema call; not available in Codex CLI. | Same replacement comment. |
| `TaskCreate(...)` | Anthropic tool-use schema call. | Same replacement comment. |
| Subagent model selection (`model: haiku/sonnet/opus`) | Codex CLI manages its own model selection via its own flags; the frontmatter `model` key is not emitted in prompts. | Not emitted. |
| Push notifications / scheduled wakeups | No equivalent in Codex CLI. | Not emitted. |
| `scripts/log-phase.sh` / `scripts/log-event.sh` telemetry | Relies on z-harness plugin infrastructure not present in Codex CLI. | Preserved as prose/code blocks but will not execute automatically. |
| Provider registry (`scripts/resolve-provider.sh`) | CLI-dispatch infrastructure specific to z-harness plugin. | Preserved as prose; user must manually invoke. |
| Consolidated AGENTS.md (one file for all agents) | Codex CLI has no native subagent dispatch concept; agents cannot be invoked by name. Users must manually read `AGENTS.md` and select the appropriate role prompt. | Documented in `AGENTS.md`. |

---

## Notes

- The prompt files are **best-effort** translations. They give Codex CLI the
  same procedural knowledge encoded in the z-harness commands and agents, but
  the CLI will not have access to the plugin infrastructure that makes z-harness
  fully automated in Claude Code.
- For full automation (subagent dispatch, telemetry, provider routing), use the
  z-harness plugin in Claude Code (`claude --dangerously-skip-permissions` or
  standard plugin install).
- These exports are regenerated from source by running:
  ```
  python3 scripts/export-codex.py
  ```
  from the repository root. Re-run after updating any `commands/`, `agents/`,
  or `skills/` file to keep the exports current.
- Bug reports for the Codex CLI export: file an issue in the z-harness
  repository and tag it `codex-export`.
