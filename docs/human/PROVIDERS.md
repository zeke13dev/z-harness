# PROVIDERS — Provider Registry Guide

> Last updated: 2026-05-24

## Overview

z-harness uses a **provider registry** to route consultant and reviewer
dispatches to any CLI-addressable LLM.  A provider is anything reachable via a
shell command — `codex`, `gemini`, `claude`, `ollama`, `agy`, or a custom
wrapper you write yourself.

Roles are kept separate from provider definitions so a team can share a repo
config that says "use codex for reviews" without hard-coding credentials or
install paths.

---

## Config file locations + precedence

| Priority | Path | Wins on |
|----------|------|---------|
| Repo-local (higher) | `<repo>/.z-harness/providers.json` | Any key present in this file |
| User-global (lower) | `~/.config/z-harness/providers.json` | All other keys |

Merge is **per-key**, not whole-file.  If both files define `providers.codex`,
the repo file wins for that key only.  All other providers come from the global
file.  Same rule applies to the `roles` map.

Whenever a repo key shadows a global key, z-harness prints a warning to stderr:

```
[providers] provider_shadowed: providers.codex — repo (.z-harness/providers.json) overrides global (~/.config/z-harness/providers.json)
```

…and emits a `provider_shadowed` event to `metrics.jsonl`.

### Testability env override

Set `Z_HARNESS_REPO_PROVIDERS=/path/to/fixture.json` to point the resolver at
any file instead of the actual repo config.  Useful in CI or test scripts.

---

## Schema (version 1)

```json
{
  "version": 1,
  "providers": {
    "<name>": {
      "kind": "cli",
      "command": "codex",
      "args_template": ["exec", "-"],
      "stdin": true,
      "timeout_s": 300,
      "model_label": "gpt-5-codex"
    }
  },
  "roles": {
    "consultant_primary":   "<provider-name>",
    "consultant_secondary": "<provider-name>",
    "reviewer":             "<provider-name>"
  }
}
```

### Field reference

| Field | Required | Description |
|-------|----------|-------------|
| `version` | yes | Must be `1` — resolver exits with an error otherwise. |
| `providers.<name>.kind` | yes | Must be `"cli"` (only kind supported). |
| `providers.<name>.command` | yes | Executable name on `PATH`. |
| `providers.<name>.args_template` | yes | Positional args passed to the command. |
| `providers.<name>.stdin` | yes | If `true`, the prompt is piped to the command's stdin. |
| `providers.<name>.timeout_s` | no | Seconds before the CLI call is killed (default 300). |
| `providers.<name>.model_label` | no | Human-readable model name (used in logs/summaries). |
| `roles.consultant_primary` | required for most commands | Primary consultant CLI. |
| `roles.consultant_secondary` | required for most commands | Secondary consultant CLI — **must differ** from primary. |
| `roles.reviewer` | required for review commands | Reviewer CLI (may equal either consultant). |

---

## The three roles

| Role | Purpose |
|------|---------|
| `consultant_primary` | First external LLM consulted during planning, implementation, and review. |
| `consultant_secondary` | Second LLM for cross-model critique.  **Must resolve to a different provider** than `consultant_primary` (the resolver rejects configs where they collide). |
| `reviewer` | LLM used by the reviewer agent.  May overlap with either consultant role. |

---

## Minimal example

```json
{
  "version": 1,
  "providers": {
    "my-codex": {
      "kind": "cli",
      "command": "codex",
      "args_template": ["exec", "-"],
      "stdin": true,
      "timeout_s": 300,
      "model_label": "gpt-5-codex"
    },
    "my-gemini": {
      "kind": "cli",
      "command": "gemini",
      "args_template": ["-p", "@-", "--approval-mode", "plan", "--output-format", "text"],
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
PROMPT="$(cat)"
my-llm-api call --prompt "$PROMPT"
```

---

## Error messages

| Message | Cause | Fix |
|---------|-------|-----|
| `[providers] role=<r> unbound — run /z-providers-discover` | Role not in `roles` map | Run `/z-providers-discover` or edit your `providers.json`. |
| `[providers] role=<r>, provider=<p>, command=<c> not on PATH` | CLI missing from shell `PATH` | Install the CLI or update `PATH`. |
| `[providers] schema version must be 1` | `version` field wrong or missing | Set `"version": 1` in your config. |
| `[providers] consultant_primary and consultant_secondary must resolve to DISTINCT providers` | Both consultant roles point to the same provider | Bind them to different providers. |

---

## Run-start observability

Every command that dispatches a consultant or reviewer calls
`scripts/log-providers.sh` at start-up.  It prints a one-line summary:

```
[providers] consultant_primary=my-gemini(gemini-2.5-pro)  consultant_secondary=my-codex(gpt-5-codex)  reviewer=my-codex(gpt-5-codex)
```

…and emits a `provider_resolved` event per role to `metrics.jsonl`.
