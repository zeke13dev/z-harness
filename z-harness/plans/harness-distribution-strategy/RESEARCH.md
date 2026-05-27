---
artifact: research
slug: harness-distribution-strategy
generated_at: 2026-05-27T03:47:50Z
command: /z-research "Map terrain for host-neutral z-harness runtime: Codex/Claude/Gemini SDK auth, Antigravity & Cursor programmatic surfaces, MCP posture, prior-art wrappers." --slug=harness-distribution-strategy
input_hash: 8cddeb6328158d3c
depends_on: [BRAINSTORM.md]
explore_calls: 3
explore_failures: 2
status: complete
---

# Research: host-neutral z-harness runtime — terrain map


## Findings

### Existing z-harness baseline (from doc-fetcher)
- z-harness already uses Codex CLI's machine-readable mode: `cat prompts/<id>.md | codex exec -` ([scripts/export-codex.py:22,30](scripts/export-codex.py:22), [PROVIDERS.md:52](PROVIDERS.md:52), [scripts/resolve-provider.py:220](scripts/resolve-provider.py:220)).
- z-harness imports no SDKs anywhere; all multi-provider dispatch is CLI-subprocess only (`resolve-provider.py:65-68` validates `provider.kind == "cli"` only).
- Antigravity dispatch today uses the non-nesting workaround `agy chat --mode <workflow-id>` ([scripts/export-agy.py:327](scripts/export-agy.py:327)); MCP wiring is declared `status: not_implemented` ([scripts/export-agy.py:284-287](scripts/export-agy.py:284), [exports/agy/CAPABILITIES.md:30](exports/agy/CAPABILITIES.md:30)).
- Cursor integration is static `.mdc` rule files; no CLI dispatch path exists today.
- Claude Code integration is plugin-symlink injection at `~/.claude/plugins/z-harness@zeke-tools` ([install.sh:102](install.sh:102)); the harness runs *inside* Claude Code.

### Host CLI machine-readable / non-interactive modes (ALL four hosts have one)
- **Claude Code**: `claude -p <prompt>` (headless), `--output-format text|json|stream-json`, `--verbose` to surface intermediate tool events. `--bare` mode skips OAuth and keychain reads (intended for CI / scripted use; auth via `ANTHROPIC_API_KEY` or `apiKeyHelper` in `--settings`). ([code.claude.com/docs/en/headless](https://code.claude.com/docs/en/headless))
- **Codex CLI**: `codex exec -` (stdin → stdout), already used by z-harness. ([developers.openai.com/codex/noninteractive](https://developers.openai.com/codex/noninteractive))
- **Antigravity**: `agy --prompt`/`agy -p` (single-shot), `agy --prompt-interactive`/`-i`, `agy --output-format text|json|stream-json`. ([medium.com/google-cloud/antigravity-cli-tutorial-series-12b46cfe3bf2](https://medium.com/google-cloud/antigravity-cli-tutorial-series-12b46cfe3bf2))
- **Cursor**: binary is `cursor-agent` (not `cursor`), with `-p`/`--print` headless, `--output-format text|json|stream-json`, `--stream-partial-output`, `--mode ask|plan|agent`, `--force`/`--yolo` to enable writes in print mode. Auth via `CURSOR_API_KEY`. ([cursor.com/docs/cli/headless](https://cursor.com/docs/cli/headless), [cursor.com/docs/cli/overview](https://cursor.com/docs/cli/overview))

### Host SDK auth models — OAuth tokens NOT reusable across processes
- **Anthropic SDK** (Python `anthropic`, TS `@anthropic-ai/sdk`): auth precedence is `api_key=` ctor arg → `ANTHROPIC_API_KEY` env → `ANTHROPIC_AUTH_TOKEN` env → SDK-internal profile system (NOT `~/.claude/`). The SDK does **not** read `~/.claude/.credentials.json`. Claude Pro/Max OAuth tokens have been explicitly banned in third-party tools / Agent SDK since enforcement began **Jan 9, 2026** ([winbuzzer.com/2026/02/19/anthropic-bans-claude-subscription-oauth-in-third-party-apps-xcxwbn](https://winbuzzer.com/2026/02/19/anthropic-bans-claude-subscription-oauth-in-third-party-apps-xcxwbn/), [github.com/anthropics/claude-code/issues/42106](https://github.com/anthropics/claude-code/issues/42106)). `claude setup-token` produces a token consumed by Claude Code CLI/Agent SDK only, NOT the bare `anthropic` SDK ([code.claude.com/docs/en/authentication](https://code.claude.com/docs/en/authentication)).
- **Codex CLI auth model**: stores ChatGPT OAuth tokens in `~/.codex/auth.json` (or OS keyring); the `openai` Python/TS SDK does NOT read this file. `CODEX_API_KEY` works in `codex exec` only; `OPENAI_API_KEY` requires a custom `~/.codex/config.toml` `model_providers` workaround ([github.com/openai/codex/issues/5212](https://github.com/openai/codex/issues/5212), [developers.openai.com/codex/auth](https://developers.openai.com/codex/auth)). Codex CLI itself is a Rust binary published as `@openai/codex` ([github.com/openai/codex](https://github.com/openai/codex)) — whether it links the OpenAI Rust SDK vs raw HTTP is not verified here; the user-facing observation is that the public Python/TS SDKs do not share state with it.
- **Gemini CLI / `google-genai` SDK**: CLI stores Google OAuth2 tokens at `~/.gemini/oauth_creds.json`; the SDK reads `GEMINI_API_KEY` / `GOOGLE_API_KEY` / Vertex ADC. Token in `~/.gemini/oauth_creds.json` is technically a standard OAuth2 bearer with the correct scopes, but the SDK's `GoogleAuth` chain does not read that path — manual injection is technically possible but unsupported and fragile. ([google-gemini.github.io/gemini-cli/docs/get-started/authentication.html](https://google-gemini.github.io/gemini-cli/docs/get-started/authentication.html))
- **Antigravity SDK**: API key only; no OAuth SDK support as of May 2026 ([discuss.ai.google.dev/t/will-antigravity-sdk-support-oauth/145587](https://discuss.ai.google.dev/t/will-antigravity-sdk-support-oauth/145587)). Antigravity CLI uses Google OAuth and shares `~/.gemini/` with Gemini CLI.
- **Cursor SDK** (`@cursor/sdk`, public beta from 2026-04-29): `CURSOR_API_KEY` env or `apiKey` ctor arg; Team Admin API keys not yet supported. ([cursor.com/blog/typescript-sdk](https://cursor.com/blog/typescript-sdk))

### Antigravity programmatic surfaces beyond workflow files
- **Headless CLI flags exist** (see above): `--prompt`, `--output-format stream-json`. This is materially more than "write a 12k-char workflow file."
- **MCP client**: Antigravity reads `~/.gemini/config/mcp_config.json` (shared by CLI, IDE, and SDK). Supports stdio (`command`+`args`) and remote HTTP (`serverUrl`+`headers`). ([medium.com/google-cloud/configuring-mcp-servers-and-skills-for-antigravity-cli-and-ide-a938c7eebb78](https://medium.com/google-cloud/configuring-mcp-servers-and-skills-for-antigravity-cli-and-ide-a938c7eebb78))
- **Official Antigravity Extension SDK** (TypeScript, on Open VSX): `sdk.cascade` (CascadeManager — send prompts, control steps, list sessions), `sdk.monitor` (EventMonitor — real-time events), `sdk.commands` (60+ Antigravity commands via VS Code command API), `sdk.ls` (Language-Server channel for headless cascade creation), `sdk.state`. Includes `SENSITIVE_KEYS` blocklist preventing extension access to auth tokens. ([antigravity.google/blog/introducing-google-antigravity-sdk](https://antigravity.google/blog/introducing-google-antigravity-sdk), [kanezal.github.io/antigravity-sdk](https://kanezal.github.io/antigravity-sdk/))
- **Managed Agents REST API** (separate from extension SDK): `POST https://generativelanguage.googleapis.com/v1beta/interactions`, Python `AntigravityClient.agents.create_and_run()`. MCP not yet supported in preview as of May 2026. ([ai.google.dev/gemini-api/docs/antigravity-agent](https://ai.google.dev/gemini-api/docs/antigravity-agent))
- **CDP debug port** (optional): launching Antigravity IDE with `--remote-debugging-port=9000` exposes the Chrome DevTools Protocol. A community shim (`cafeTechne/antigravity-link-extension`) bridges this to HTTP + MCP tools. ([github.com/cafeTechne/antigravity-link-extension](https://github.com/cafeTechne/antigravity-link-extension))
- VS Code fork using Open VSX registry; third-party VS Code extensions installable via Open VSX or via `agvs` `.vsix` sideload. ([beginnersinai.org/google-antigravity](https://beginnersinai.org/google-antigravity/))

### Cursor programmatic surfaces beyond .mdc rule files
- **`cursor-agent` CLI headless mode** (above) is the closest analogue to `codex exec`.
- **MCP client**: `~/.cursor/mcp.json` (global) and `.cursor/mcp.json` (project). Supports stdio, SSE, Streamable HTTP. Adds **Resources** (v1.6, Sep 2025), **Elicitation** (v1.5 — servers can request mid-execution user input), **Apps** (interactive UI extensions). ([cursor.com/docs/mcp](https://cursor.com/docs/mcp))
- **Programmatic MCP registration**: extensions can call `vscode.cursor.mcp.registerServer()` to add an MCP server without editing JSON config. Documented as enterprise pattern.
- **Custom slash commands are FILE-BASED**, not extension-API-registered: `.cursor/commands/<command>.md` in the project. No programmatic registration API for slash commands. The closest API-driven slash-command path is exposing MCP prompts (invoked as `mcp.servername.promptname`).
- **REST API for Background/Cloud Agents**: full lifecycle endpoints under `https://api.cursor.com/v1/agents/...` — create, run, SSE stream (with `Last-Event-ID` resumability), artifacts, archive. Accepts up to 50 MCP server definitions per agent, custom subagents, workspace targeting (cloud/self-hosted/local). ([cursor.com/docs/background-agent/api/overview](https://cursor.com/docs/background-agent/api/overview))
- **`@cursor/sdk` TypeScript SDK** (public beta, Apr 2026): `Agent.create({apiKey, model, local|cloud})`, `Agent.resume(id)` (reattach after process restart), `agent.send().stream()` async generator, `run.wait()`. Local runtime runs agent loop inline in Node process; Cloud runtime in isolated VM. The "one active run per agent (HTTP 409 `agent_busy`)" constraint is documented for the Cloud runtime; whether the Local runtime enforces an equivalent in-process lock is not explicitly stated. Token-based billing under "SDK" usage tag. ([cursor.com/blog/typescript-sdk](https://cursor.com/blog/typescript-sdk))

### MCP server posture per host
| Host | Global MCP config | Project MCP config | Concurrency / quirks |
|------|-------------------|--------------------|----------------------|
| Claude Code | `~/.claude.json` (NOT `~/.claude/mcp.json` — silently ignored, [issue #4976](https://github.com/anthropics/claude-code/issues/4976)) | `.mcp.json` (project root) | Tool parallelism requires `readOnlyHint: true` on each tool ([greynewell/mcp-serialization-repro](https://github.com/greynewell/mcp-serialization-repro)); STDIO transport spawns subprocess per concurrent connection (OOM risk under fan-out); Supergateway bridges STDIO→Streamable HTTP for multiplexing |
| Codex CLI | `~/.codex/config.toml` | `.codex/config.toml` (trusted projects only) | STDIO + Streamable HTTP; `codex mcp add <name> -- <command>` registration ([developers.openai.com/codex/mcp](https://developers.openai.com/codex/mcp)) |
| Antigravity | `~/.gemini/config/mcp_config.json` (shared CLI/IDE/SDK) | `.agents/mcp_config.json` | Hardcoded 100-tool limit per server in IDE ([discuss.ai.google.dev/t/.../143969](https://discuss.ai.google.dev/t/critical-dx-issue-antigravity-ide-hardcoded-mcp-tool-limit-100-configuration-fragmentation-with-gemini-cli/143969)); env-var expansion in mcp_config.json reported broken May 2026; `top-level timeout` deprecated |
| Cursor | `~/.cursor/mcp.json` | `.cursor/mcp.json` | stdio + SSE + Streamable HTTP; Resources + Elicitation + Apps protocol features; enterprise perms `~/.cursor/permissions.json`; CVE-2025-54136 ("MCPoison") — trust pinned to config key name, not command |

- Anthropic API itself supports parallel tool calls within an assistant turn via `Promise.all` / `asyncio.gather` ([platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use)). No host has published whether MCP servers themselves can recursively dispatch further parallel sub-tool-calls.

### Prior-art wrappers — what works, what breaks
- **Opcode (formerly Claudia)** — Tauri 2 + Rust + React desktop GUI; spawns `claude` subprocess and parses `--output-format stream-json` + `--verbose` JSONL ([deepwiki.com/getAsterisk/claudia/1-overview](https://deepwiki.com/getAsterisk/claudia/1-overview)). 15k+ stars. Proves the wrapper pattern works for Claude Code specifically.
- **Claude Squad** (Go TUI, 7.6k stars) — does NOT parse agent output; spawns `claude`/`codex`/`aider`/`opencode`/`gemini-cli` inside tmux sessions and displays panes ([github.com/smtg-ai/claude-squad](https://github.com/smtg-ai/claude-squad)). User reprompts by attaching to the tmux session. No structured state visibility.
- **Crush** (Charmbracelet) — does NOT wrap any CLI; talks directly to provider APIs (Anthropic, OpenAI, Gemini, Bedrock, Azure, Groq, etc.) and adds capabilities via MCP. Mid-session provider switching with context preservation.
- **Goose** (Block) — provider-API-direct, not a CLI wrapper. Notable: uses ACP (Agent Client Protocol) to let users auth via existing Claude/ChatGPT/Gemini subscriptions instead of raw API keys ([github.com/block/goose](https://github.com/block/goose)).
- **Cline, Aider, continue.dev, OpenHands, Sweep** — all talk to provider APIs directly, no CLI wrapping. OpenHands has an open issue (#261) for subscription-credential OAuth flow.
- **Mario Zechner's `pi`** — explicitly built from scratch *because* existing harnesses (1) inject context behind the wrapper's back, (2) change system prompt + tools every release (breaking workflows), and (3) don't expose full observability ([mariozechner.at/posts/2025-11-30-pi-coding-agent](https://mariozechner.at/posts/2025-11-30-pi-coding-agent/)).

### Documented failure modes when wrapping `claude`/`codex`/agent CLIs
- **Prompt cache loss**: subprocess approach breaks provider-level prompt caching; each invocation starts fresh from the CLI's perspective; wrapper has no control over cache headers ([avasdream.com/blog/claude-cli-agentic-wrapper](https://avasdream.com/blog/claude-cli-agentic-wrapper)).
- **Subprocess startup overhead**: each `claude -p` spawns a new process with ~1-2s cold start; no persistent daemon mode.
- **`CLAUDECODE=1` env-var inheritance** ([claude-agent-sdk-python#573](https://github.com/anthropics/claude-agent-sdk-python/issues/573), open as of the cited research run): spawning the Agent SDK from inside a Claude Code session inherits `CLAUDECODE=1`, causing nested CLI to refuse launch with "Claude Code cannot be launched inside another Claude Code session". Documented workaround: explicitly `env={"CLAUDECODE": ""}`. Verify issue status before relying on it as a "no-action-needed" assumption.
- **Task-state desync** ([claude-code#59962](https://github.com/anthropics/claude-code/issues/59962)): when subprocesses complete, Claude Code's internal state layers (process runner, UI, model-visible todos, stop-hook) desync. Follow-up prompts become silent no-ops.
- **Windows subprocess init timeout** ([claude-code#50559](https://github.com/anthropics/claude-code/issues/50559)): `claude.exe` spawned but never responds within 60s timeout.
- **ProcessTransport death** ([claude-agent-acp#338](https://github.com/agentclientprotocol/claude-agent-acp/issues/338)): SIGTERM'd subprocess leaves session in memory; subsequent requests fail `ProcessTransport is not ready for writing`.
- **Output format pitfalls**: `--output-format stream-json` REQUIRES `--verbose` to surface intermediate tool events. `--output-format json` with `--json-schema` silently omits `structured_output` if format-pairing wrong. Exit codes only 0/1 — error detection must parse `is_error` JSON field. `--allowedTools` uses prefix matching; `Bash(git diff*)` accidentally matches `git diff-index`.
- **Session IDs must be UUIDs**, not arbitrary strings; `--continue` in synchronous subprocess hits session-ID conflicts.

## Constraints discovered

- **No vendor permits CLI-OAuth reuse from sibling SDK processes today.** Anthropic explicitly bans Pro/Max OAuth in third-party tools (enforced 2026-01-09). Codex's ChatGPT OAuth is unreadable by the `openai` SDK. Gemini's OAuth file is technically reusable but unsupported. Antigravity SDK has no OAuth path. **Any "SDK tier" forces the user to provision per-vendor API keys** — there is no free lunch from credential sharing.
- **The host CLI must be addressable in machine-readable mode for any "CLI tier" driver.** All four hosts have such a mode (`claude -p`, `codex exec`, `agy -p`, `cursor-agent -p`), each with `stream-json` output. So pty/TUI wrapping should never be needed for these four — it's pure subprocess + JSONL parsing.
- **Antigravity workflow body limit (12k chars) is a HARD constraint on the file-injection path** — `/z-plan` already exceeds it. CLI-tier (`agy -p`) or SDK-tier sidesteps this entirely.
- **STDIO MCP transport spawns one subprocess per concurrent client connection.** Under z-harness fan-out (parallel subagents calling the same MCP server) this is an OOM risk; Streamable HTTP via a multiplexing wrapper is the documented workaround.
- **MCP `readOnlyHint: true` is the gate for parallel tool execution in Claude Code.** Any MCP tool z-harness ships that wants to be parallel-callable must set this annotation.
- **One active run per Cursor agent (HTTP 409 `agent_busy`).** Concurrency for Cursor must be modeled as N agents, not N runs per agent.
- **Antigravity IDE hardcodes 100-tool limit per MCP server** and has reported env-var-expansion bugs in `mcp_config.json` (May 2026). Both are upstream constraints, not z-harness choices.
- **Claude Code's `--bare` mode** skips OAuth and keychain, requires `ANTHROPIC_API_KEY` or `apiKeyHelper`. Recommended path for any "spawn `claude` as subprocess from another process" pattern to avoid `CLAUDECODE=1` and OAuth-conflict issues.
- **Cursor custom slash commands are file-based only**; programmatic slash-command registration via extension API is not exposed. The MCP-prompts-as-slash-commands path (`mcp.servername.promptname`) is the only API-driven path.

## Open questions

- **What `claude -p`'s prompt-cache behavior actually is.** Documented as "subprocess breaks provider-level prompt caching" — is this universal, or does Claude Code's `--bare` mode behave differently? No benchmark in the citations.
- **Whether the `agy` binary is actually distributed yet** — the most recent (2026-05-21) public-availability check returned `npm install -g @google/antigravity` → 404 ([jangwook.net analysis](https://jangwook.net/en/blog/en/google-io-2026-antigravity-2-agent-platform-analysis/)). If agy isn't publicly available, the entire Antigravity tier is speculative.
- **Antigravity Extension SDK trustworthiness**: the `kanezal.github.io/antigravity-sdk` doc is community reverse-engineering. The official blog announcement exists but no first-party API reference was located. Code that depends on these surfaces should be treated as "subject to change without notice" until first-party docs confirm.
- **MCP recursive parallelism**: no host has published whether an MCP tool can itself spawn parallel sub-tool-calls back through the protocol. If z-harness wants subagent dispatch to map to MCP, this is the blocking question.
- **Cursor REST API auth + billing scope** for non-Cloud-Agent usage: the `/v1/agents/*/runs` endpoints assume Cloud Agent runs that cost the user money. Whether the same SSE event stream is available for local-runtime SDK agents is unclear from the cited docs.
- **Does `agy chat --mode <workflow-id>` still launch a NEW top-level session when invoked via `agy -p`?** The non-nesting limitation might be specific to in-workflow invocation; `-p` from outside the workflow may behave differently. The current `export-agy.py:327` workaround was for in-workflow.
- **Session resumability across host process restarts** — Cursor SDK has explicit `Agent.resume(id)`. Does `claude -p` accept a session-ID flag to reattach to an in-flight session? Does `codex exec`? Does `agy -p`? Resumption semantics (state snapshot vs full replay) not mapped.
- **Anthropic Agent SDK auth in headless subprocess** — does the official Python/TS Agent SDK (NOT the bare `anthropic` SDK) have a `--bare`-equivalent or its own credential-skip mode? Is its auth path `ANTHROPIC_API_KEY` the same as the raw SDK?
- **Codex `exec` env-var inheritance** — when launched as a subprocess of a parent process that already has `OPENAI_API_KEY` / `CODEX_API_KEY` / `ANTHROPIC_API_KEY` set, does Codex reuse parent env, ignore, or fail? Cross-vendor env-var collision (e.g. running `codex exec -` from a Python process that has both Anthropic and OpenAI keys set) is unmapped.
- **OAuth token expiry / rotation during long-running sessions** — Claude Code, Codex CLI, and Antigravity CLI all use OAuth refresh tokens. If a wrapper holds a subprocess open for hours, does the CLI auto-refresh in-process or does the session die? Not documented.
- **Subprocess startup overhead breakdown** — the ~1-2s `claude -p` cold start: how much is interpreter startup vs config-file read vs auth check vs model handshake? Determines whether a persistent daemon mode is necessary.
- **MCP tool payload size limits** — does any host (Claude Code / Codex / Antigravity / Cursor) silently truncate large tool parameters or results? If z-harness ships an MCP server that returns multi-MB plan artifacts, this matters.
- **Cursor MCP protocol-version requirements** — are Cursor's v1.5-1.6 features (Resources, Elicitation, Apps) opt-in (older MCP servers continue working) or required for any registration? Backwards-compat for z-harness MCP servers across hosts.
- **Cross-project MCP-config isolation** — if z-harness is installed globally, do user's projects share MCP server registrations? Is there a risk of `.mcp.json` in project A's secrets being readable to project B's session?
- **SDK versioning & deprecation cadence** — `@cursor/sdk` is beta as of 2026-04-29, `@google/antigravity` may not be public yet (npm 404 on 2026-05-21). What semver guarantees do these provide? Major-version lock strategy?
- **Subprocess SIGSEGV / hang handling** — `claude -p` / `codex exec` / `agy -p` / `cursor-agent -p` behavior on crash vs hang differs. Wrapper-side timeout + reap policy needs to be per-host.
- **Observability loss in nested subprocess chains** — if z-harness runs inside Claude Code (plugin) and spawns `codex exec -`, can the user attribute wall-time / token spend to the right layer, or does it lump as "model thinking time"?
- **Antigravity public-availability freshness** — `jangwook.net` analysis dated 2026-05-21 reported `npm install -g @google/antigravity` → 404. Re-verify before any planning commits to the Antigravity SDK.
- **Antigravity REST API depth** — `POST /v1beta/interactions` is documented but the cited research didn't establish whether it preserves session state across calls, supports parallel runs, or supports subagent dispatch without MCP.
- **MCP tool-result streaming granularity** — `stream-json` is documented for CLI; whether MCP *tool* results stream incrementally vs arrive as a single JSON block (affecting tail-latency for long-running tools) is not mapped.
- **MCPoison (CVE-2025-54136) exploit shape** — draft notes "trust pinned to config key name, not command"; the actual attack surface (override of legitimate server via name collision in user-editable config) needs verification before z-harness allows user-editable MCP configs.
- **Firewall / proxy posture for streaming** — `stream-json`, SSE, Streamable HTTP behavior under corporate MITM / proxies not mapped.

## Cross-LLM review notes

Gemini critique gaps filled inline:
- Codex Rust-vs-OpenAI-SDK claim softened (now flagged as not verified in-band).
- Cursor `agent_busy` constraint reframed as Cloud-only-documented.
- `CLAUDECODE=1` workaround caveated with "verify issue status before assuming fixed."

Gemini critique gaps moved to Open questions: Antigravity REST API depth; MCP tool-result streaming; Cursor extension model-selection programmability; OAuth expiry; agy publish-status freshness; CVE-2025-54136 exploit shape; firewall/proxy posture; artifact-file semantics per host (Codex/Antigravity not mapped); tool-schema parity across SDK vs CLI (`@cursor/sdk` `send()` vs `cursor-agent -p`).

Codex critique gaps filled inline: none (all required external lookup).

Codex critique gaps moved to Open questions: per-host session resumability across process restarts; cross-vendor env-var collision; subprocess startup overhead breakdown; MCP tool payload size limits; Cursor MCP-protocol-version backwards-compat; cross-project MCP-config isolation; SDK versioning / deprecation cadence; subprocess SIGSEGV/hang handling; nested-subprocess observability; Antigravity SDK OAuth surface freshness.

Unfilled items the user should know about before /z-plan: every Open question item above is a real planning risk; none would be cheap to research in-band (most require running CLIs against live services or reading vendor source). Recommend either (a) accepting the open questions as planning risks and proceeding with /z-plan, or (b) running a second /z-research focused on a narrower slice once an architectural direction is locked.

## No-recommendation

This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
