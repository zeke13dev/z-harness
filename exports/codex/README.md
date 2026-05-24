# z-harness for Codex CLI

This directory contains z-harness commands, agents, and skills exported as
prompt files for use with the [Codex CLI](https://github.com/openai/codex)
(`codex exec`).

## What is this?

z-harness is a structured planning and implementation pipeline for Claude Code.
This export makes the same procedural knowledge available for Codex CLI so you
can drive z-harness workflows using OpenAI's Codex.

See `CAPABILITIES.md` for a complete list of what is and is not supported in
the Codex CLI export.

## Directory layout

```
exports/codex/
├── CAPABILITIES.md        # what is/isn't supported
├── AGENTS.md              # all agent roles (consolidated reference)
├── README.md              # this file
└── prompts/
    ├── z-plan.md          # one file per command
    ├── z-implement-all.md
    ├── z-debug.md
    ├── ...                # all commands and skills
    └── z-suggest-memory.md
```

## Usage

### Run a single command

Pipe a prompt file into `codex exec`:

```sh
cat exports/codex/prompts/z-plan.md | codex exec -
```

### Reference agents

Agents (subagent roles) are documented in `AGENTS.md`. Codex CLI has no native
subagent dispatch, so multi-agent workflows must be sequenced manually. For
each step:

1. Identify the appropriate agent section in `AGENTS.md`.
2. Copy the relevant agent description into your next `codex exec` invocation
   as context, or pipe the agent role as a preamble:

```sh
(cat exports/codex/AGENTS.md | grep -A 30 "## implementer"; \
 cat exports/codex/prompts/z-implement-all.md) | codex exec -
```

### Copy prompts to a local directory

If you maintain a local Codex prompt library, copy the `prompts/` directory:

```sh
cp -r exports/codex/prompts/ ~/my-codex-prompts/z-harness/
```

Then invoke any prompt from your library:

```sh
cat ~/my-codex-prompts/z-harness/z-plan.md | codex exec -
```

## Keeping exports up to date

The prompt files in `prompts/` and the `AGENTS.md` file are generated from the
source files in `commands/`, `agents/`, and `skills/`. After pulling updates
to z-harness, regenerate the exports from the repository root:

```sh
python3 scripts/export-codex.py
```

## Filing bugs

For issues with the Codex CLI export specifically, file an issue in the
z-harness repository and tag it `codex-export`.

For issues with z-harness itself, see the main `README.md` at the repository
root.
