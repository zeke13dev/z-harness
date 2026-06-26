# pi export capabilities

How z-harness constructs map onto [pi](https://pi.dev), and where the mapping is lossy. This file is copied from `scripts/pi_assets/CAPABILITIES.md` by the runtime-owned `runtime.drivers.pi.export.export` entry point, normally via `/z-export --target=pi`.

## Supported

- **Subagent fan-out.** pi's subagent extension (vendored under `extensions/subagent/`) spawns isolated `pi` child processes. `Agent(subagent_type="X", ...)` call sites in command/skill/agent bodies are rewritten to `> [pi] Use the subagent tool: { "agent": "X", "task": "..." }`. Parallel and chain modes are available (`tasks: [...]`, `chain: [...]`).
- **Agents as executable files.** Every z-harness agent is emitted to `agents/<id>.md` with frontmatter normalized to pi tool names, discoverable by the subagent extension from `~/.pi/agent/agents/`.
- **Commands & skills as prompts.** Each command and skill becomes `prompts/<id>.md`, loadable via pi's `prompts` setting and invokable as `/<id>`.
- **Skills natively.** z-harness is also installed as a pi *package*, so its `skills/` auto-surface. `Skill("z-foo")` call sites are rewritten to `> [pi] Run the /z-foo skill.`
- **Tools.** `read, grep, find, ls, bash, write, edit` map directly. `Glob` maps to `find`.
- **Model pinning (omp v16).** The `omp` binary (v16.1.11) supports `--model provider/id` fuzzy pinning, so per-agent models are no longer dropped — an exported agent can name e.g. `openai-codex/gpt-5.5` or `google-antigravity/gemini-3.1-pro`. The previous "no pinning / deepseek-only" limitation is gone.
- **OAuth provider auth.** omp authenticates subscriptions via `/login` (ChatGPT/Codex, Claude Pro/Max, GitHub Copilot, google-antigravity, xAI Grok), so pi-exported agents can use provider-backed defaults on an omp-backed pi install. Native OMP users should use `/z-export --target=omp`.
- **Native skills + profiles (omp v16).** omp discovers `skills/` natively and supports isolated `--profile` auth/session sandboxes through the first-class OMP export; `scripts/omp-consult.sh` is only the consult-provider fallback shim, not the native OMP export path.

## Unsupported

- **Claude model-id mapping is not 1:1.** Source agents pin Claude tiers (`haiku`, `sonnet`); there is no automatic translation to an omp `provider/id`, so on export those pins are dropped and the agent inherits omp's configured default unless an explicit `--model` is set in `scripts/pi_assets/`. Pinning itself works (above) — only the automatic Claude→omp tier mapping is absent.
- **`AskUserQuestion()` / `TaskCreate()` / `SubagentCreate()` / plan-mode tools** have no native pi tool. Those call lines are rewritten to a `> [pi]` inline-handling hint; the orchestrator must ask the user or track state itself.
- **Dropped tools.** `WebFetch`, `WebSearch`, `Agent`-as-tool, `NotebookEdit`, and other Claude-only tools are removed from agent allowlists; `/z-export --target=pi` reports the per-agent drop list.
- **Multi-line call rewrites are line-based.** Only the line containing `Agent(` / `Skill(` is rewritten; argument lines on following lines (e.g. a `prompt="""..."""` block) are left in place. Treat the `> [pi]` hint as the authoritative instruction and ignore residual argument text.
- **Many internal agents assume an orchestrator.** Agents like `implementer`, `reviewer`, `cluster-planner` are written for a driving orchestrator and may not be useful as standalone one-shot subagents. `doc-fetcher` and `explore` are the headline fan-out agents.

## Notes

- **Source of truth.** Generated files (`agents/`, `prompts/`, `AGENTS.md`) come from z-harness `commands/`, `agents/`, `skills/`. pi-only files (`explore` agent, the subagent extension, the AGENTS preamble, this file, `README.md`) live in `scripts/pi_assets/` and are copied verbatim by `runtime.drivers.pi.export.export`. Never edit `exports/pi/` by hand — re-run `/z-export --target=pi`.
- **OMP is separate.** First-class OMP support writes `exports/omp` via `/z-export --target=omp`; do not route native OMP export through the legacy pi exporter or `scripts/omp-consult.sh`.
- **Refreshing the vendored extension** after a pi upgrade: see `extensions/subagent/VENDOR.md`.
- **Install** is by symlink from `exports/pi/` into `~/.pi/agent/` — see `README.md`.
