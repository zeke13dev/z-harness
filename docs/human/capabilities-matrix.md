# Host Capabilities Matrix

> Last updated: 2026-06-04
> Source: z_harness_cli/adapters/{claude,antigravity,cursor,codex}.py

## Fidelity tiers

The `z-harness` CLI assigns each supported host a **fidelity tier** that
expresses how completely z-harness features are available on that host.

| Tier | Meaning |
|------|---------|
| `native` | Full orchestration + native personas. All `/z-*` commands run identically to the Claude Code reference implementation. Multi-agent dispatch (subagents, panels, consults, gates) works. |
| `high` | Native skills/personas, single-agent only. The host reads persona and skill files via its own native mechanism; single-agent commands run with high fidelity. Multi-agent commands (`/z-implement-all`, `/z-panel`, `/z-consult`, `/z-gate`) are degraded to single-agent transliteration — present but without subagent dispatch. |
| `flattened` | Transliterated rules, single-agent only. z-harness rules are injected as a host-native config file (AGENTS.md, .cursor/rules/*.mdc). Single-agent commands run in degraded mode. Multi-agent commands are **blocked** (not available). |

## Per-host fidelity

| Host | Binary | Fidelity tier | Config injection |
|------|--------|---------------|-----------------|
| Claude Code | `claude` | `native` | `CLAUDE.md` (ephemeral) or installed plugin |
| Antigravity | `agy` | `high` | `.agent/z-harness-session.md` |
| Cursor | `cursor-agent` | `flattened` | `.cursor/rules/z-harness-session.mdc` |
| Codex CLI | `codex` | `flattened` | `AGENTS.md` |

## Per-host capabilities

| Capability | claude | antigravity | cursor | codex |
|------------|--------|-------------|--------|-------|
| `supports_project_mcp` | true | false | true | true |
| `supports_user_mcp` | true | false | true | false |
| `needs_trust_prompt` | false | false | true | false |
| `supports_cwd_override` | true | false | false | false |
| `cleanup_strategy` | ephemeral | ephemeral | ephemeral | ephemeral |

## Command-tier grid

The table below summarises what happens when each `/z-*` command is run on each host.

- **native** — runs identically to the Claude Code reference.
- **degraded** — runs in single-agent transliteration mode; reduced fidelity.
- **blocked** — not available on this host.

| Command | claude | antigravity | cursor | codex |
|---------|--------|-------------|--------|-------|
| `/z-implement-all` | native | degraded | blocked | blocked |
| `/z-panel` | native | degraded | blocked | blocked |
| `/z-consult` | native | degraded | blocked | blocked |
| `/z-gate` | native | degraded | blocked | blocked |
| All other `/z-*` | native | native | degraded | degraded |

Multi-agent commands require subagent dispatch capability; only `native`-tier
Claude Code provides it.  The `high`-tier Antigravity host supports the
underlying skills natively but lacks subagent dispatch, so those commands fall
back to single-agent transliteration (degraded, not blocked).

## Environment injection

On `ephemeral` injection, each adapter sets the appropriate plugin-root env var
so the spawned host process can locate the z-harness runtime:

| Host | Env var injected |
|------|-----------------|
| claude | `CLAUDE_PLUGIN_ROOT` |
| antigravity | `ANTIGRAVITY_PLUGIN_ROOT` |
| cursor | `CLAUDE_PLUGIN_ROOT` |
| codex | `CLAUDE_PLUGIN_ROOT` |

## MCP registration (codex and cursor)

Both Codex and Cursor support project-scoped MCP.  The Codex adapter registers
the z-harness MCP server in `~/.codex/config.toml` via `codex mcp add`; this
write is **global and persistent** — it is not reversed on ephemeral cleanup.
Explicit removal is available via `z-harness doctor --clear-mcp`.

The Cursor adapter writes `.cursor/mcp.json` (project-scoped) and optionally
`~/.cursor/mcp.json` (user-scoped).

## Sources

- `z_harness_cli/adapters/claude.py` — `fidelity_tier = "native"`
- `z_harness_cli/adapters/antigravity.py` — `fidelity_tier = "high"`
- `z_harness_cli/adapters/cursor.py` — `fidelity_tier = "flattened"`
- `z_harness_cli/adapters/codex.py` — `fidelity_tier = "flattened"`
- `z_harness_cli/adapters/base.py` — `KNOWN_COMMANDS`, `register_command_tiers`
