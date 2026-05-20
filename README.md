# z-harness

A Claude Code plugin that wraps planning and implementation in a rigorous, cross-LLM-reviewed pipeline.

## What it does

- **`/z-plan <task>`** — Exploratory pass over the codebase, identifies non-obvious decisions, consults **Gemini** and **Codex** in parallel for each, pushes back on weak reasoning, requires user approval for major decisions and any shortcuts, then produces:
  - `z-harness/SPEC.md` — per-file detailed spec
  - `z-harness/PLAN.md` — approved plan with rationale
  - `z-harness/TASKS.md` — small independently-implementable tasks
  - `z-harness/archive/<timestamp>/` — frozen copy of all three

- **`/z-implement-next`** — Picks the next pending task from `TASKS.md`, implements per `SPEC.md`, then spawns a Codex reviewer subagent that scrutinizes the diff. User is push-notified at each task boundary.

## Operating principles

- Push back by default — on Gemini, Codex, and the user.
- Always ask when unclear. No silent assumptions.
- No shortcuts without explicit user approval.
- DRY / KISS / SOLID are non-negotiable in the final plan.

## Requirements

- `codex` CLI installed and authenticated (uses the Codex/ChatGPT app endpoint, *not* the OpenAI API endpoint).
- `gemini` CLI installed and authenticated.
- Claude Code with `PushNotification` available (for mobile notifications).

## Install

From any Claude Code session:

```
/plugin marketplace add /Users/zeke/dev/z-harness
/plugin install z-harness@zeke-tools
```

Or, for git distribution:

```
/plugin marketplace add <github-org>/z-harness
/plugin install z-harness@zeke-tools
```

## Per-repo auto-enable

In each project where you want z-harness on automatically, commit `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "zeke-tools": { "source": { "source": "github", "repo": "<org>/z-harness" } }
  },
  "enabledPlugins": { "z-harness@zeke-tools": true }
}
```

## Layout

```
z-harness/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── commands/
│   ├── plan.md
│   └── implement-next.md
├── agents/
│   ├── gemini-consultant.md
│   ├── codex-consultant.md
│   └── codex-reviewer.md
└── README.md
```
