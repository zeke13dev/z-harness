# Route decision

**From:** `/z-plan`
**To:** `/z-research`
**Class:** deterministic
**Confidence:** high
**Classifier used:** no — deterministic signals decided

## Reason codes
- `terrain_uncertain`

## Signals
- `terrain_uncertain: true` — three load-bearing factual questions are unresolved and gate SPEC content:
  1. Does Codex CLI expose a non-TUI, machine-readable execution mode (`codex exec`, `--json`, or equivalent)? If not, Codex CLI driver is pty-only, which the chosen framing explicitly demotes to "last resort."
  2. Do the official Claude SDK and Codex SDK reuse the host CLI's auth (keyring, OAuth refresh tokens, etc.), or require their own keys? This gates the "SDK tier sidesteps credential plumbing" claim.
  3. What programmatic execution surfaces do Antigravity (`agy`) and Cursor expose beyond their plugin/workflow formats?
- `has_brainstorm: true` — BRAINSTORM.md exists with `chosen_framing: codex` (host-neutral runtime with tiered drivers).
- `approach_uncertain: false` — architectural direction is settled; only terrain is missing.

## User choice
User picked `switch` — run `/z-research` first, then return to `/z-plan` with full multi-host runtime scope.

## Route chain
1. `/z-brainstorm` (complete, chose Codex framing)
2. `/z-plan` (this run — routed away at Phase 0)
3. `/z-research` (next)

## What /z-research should map

Concrete open questions for the research run, with file:line citations or external doc citations:

1. **Codex CLI execution surfaces.** Does it have a `codex exec`, `codex run`, or `--json` mode returning structured output? Can it be driven via stdin without TUI? Latency / prompt-cache behavior of any such mode vs interactive TUI?
2. **Claude SDK auth model.** Anthropic SDK (Python / TypeScript): does it read `~/.claude/credentials.json` or equivalent that `claude` CLI writes? Or require `ANTHROPIC_API_KEY` env? Same for `gemini` / `codex` SDKs.
3. **Antigravity (agy) programmatic surface.** Beyond `.agent/workflows/` and `.agent/rules/`, does agy expose an MCP server, daemon socket, CLI subcommand, or language-server protocol? The 12k-char workflow limit is a forcing function.
4. **Cursor extension API.** Cursor has a VS-Code-derived extension API. Is there a stable surface for "register a slash command that calls out to a local binary"? MCP integration? Auth model for tool calls inside Cursor?
5. **MCP server posture across hosts.** Which of {Claude Code, Codex CLI, Antigravity, Cursor} currently support MCP servers as a first-class extension surface? Concurrency model (sequential vs parallel tool calls)?
6. **Existing wrappers / prior art.** OSS projects already doing "wrap claude/codex CLI as subprocess and own the UX" (e.g. `claudia`, `claude-squad`, aider-style wrappers)? What did they learn?

These map directly to the three load-bearing decisions: driver tier per host, auth strategy, and transport layer per host.
