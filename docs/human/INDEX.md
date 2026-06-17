# Docs index

_Updated: 2026-06-03_  
_Plugin: z-harness_

Concepts grouped by top-level module. Each entry links to its human-tier page.
Companion LLM-tier JSON lives at `../llm/<slug>.json`.

## agents

| Concept | Confidence | Source files | Summary |
|---|---|---|---|
| [agents](./agents.md) | high | `agents/auditor.md`, `agents/cluster-planner.md`, `agents/consultant-primary.md` | Scrutinizes codebase targets across correctness/perf/cleanliness/design. |
| [reviewer-capture](./reviewer-capture.md) | high | `agents/reviewer.md`, `agents/consultant-primary.md`, `agents/consultant-secondary.md` | File-based review capture via codex `-o` flag; capability-probed per-PPID; full review archived; honest `response_chars`; fallback emits `review_capture_fallback`. |
| [impl-pre-review](./impl-pre-review.md) | high | `commands/z-implement-all.md`, `agents/pre-reviewer.md`, `agents/complexity-classifier.md` | Opt-in Flash pre-reviewer gate-down (`Z_HARNESS_IMPL_PRE_REVIEW`, default 0, ships inert). Cost-inversion caveat; evidence-gated before recommended. |

## commands

| Concept | Confidence | Source files | Summary |
|---|---|---|---|
| [commands](./commands.md) | high | `commands/z-amend.md`, `commands/z-audit.md`, `commands/z-brainstorm.md`, `commands/z-git-guardrails.md`, `commands/z-grill.md` | Propagates targeted plan amendments consistently across plan artifacts. New: `/z-grill` (requirements interview, produces GRILL.md), `/z-git-guardrails` (installs git-safety PreToolUse hook). Updated: `/z-init-docs` (bootstraps CONTEXT.md by default, `--no-glossary` opts out), `/z-maintain-docs` (new `--glossary` flag), `/z-debug` (Phase 2 feedback-loop ladder + `repro_confidence`), `/z-plan` + `/z-brainstorm` (GRILL.md precontext detection). |

## config

| Concept | Confidence | Source files | Summary |
|---|---|---|---|
| [config](./config.md) | high | `scripts/config.py`, `scripts/config.sh` | Layered TOML config: built-in defaults → global → repo-local → env. Slice 1 knobs: notify.level, docs.always_apply. |

## scripts

| Concept | Confidence | Source files | Summary |
|---|---|---|---|
| [scripts](./scripts.md) | high | `scripts/block-dangerous-git.sh`, `scripts/log-event.sh`, `scripts/log-phase.sh`, `scripts/regenerate-memories-flat.py` | Appends standard JSON events to run and global logs. New: `block-dangerous-git.sh` PreToolUse hook — classifies git commands, blocks rewrite verbs when upstream-reachable, blanket-blocks working-tree-destructive verbs, supports `Z_HARNESS_GIT_GUARDRAILS_OVERRIDE=1`. |
| [subagent-telemetry](./subagent-telemetry.md) | high | `scripts/detect-host.sh`, `scripts/log-event.sh`, `scripts/log-subagent.sh`, `scripts/estimate-tokens.py` | Per-subagent cost telemetry. `detect-host.sh` (claude/pi/codex/cursor/antigravity); `host` on every event; `subagent_call` event with separate `prompt_chars`/`response_chars` (D9); chars-not-tokens limitation for native Claude; drift-guard CI. |

## skills

| Concept | Confidence | Source files | Summary |
|---|---|---|---|
| [skills](./skills.md) | high | `skills/z-amend/SKILL.md`, `skills/z-brainstorm/SKILL.md`, `skills/z-debug/SKILL.md` | Checklists for amending spec, plan, and task checklists consistently. |

## repo-root artifacts

Artifacts managed by z-harness at the repository root (not under `docs/`).

| Artifact | Created by | Summary |
|---|---|---|
| `CONTEXT.md` | `/z-init-docs` (default), `/z-maintain-docs --glossary` | Domain glossary: term / definition / avoid + Relationships + Flagged ambiguities sections. Bootstrapped via Explore + AskUser; idempotent (extends, never clobbers user terms). Pass `--no-glossary` to skip on init. |
| `GRILL.md` | `/z-grill` | Finalized requirements-interview transcript, staged under `$Z_HARNESS_PLAN_DIR/<slug>/GRILL.md`. Detected as precontext by `/z-plan` (step 9) and `/z-brainstorm` (Phase 1 §1c). |

## mcp-server

| Concept | Confidence | Source files | Summary |
|---|---|---|---|
| [mcp-server](./mcp-server.md) | high | `z_harness_cli/mcp/server.py`, `z_harness_cli/commands/serve.py` | `z-harness serve` exposes all /z-* commands as MCP tools over stdio (FastMCP). 39 tools: heavy commands dispatch through runtime/dispatch; fast read-only commands use direct in-process handlers. Includes editor config snippets for Cursor, VS Code, Claude Desktop, and Hermes. |

## reference

| Concept | Source file | Summary |
|---|---|---|
| [INSTALL.md](./INSTALL.md) | — | Install instructions, requirements, uninstall. |
| [PROVIDERS.md](./PROVIDERS.md) | — | Provider registry: roles, config-file locations, precedence. |
| [PLAN-LAYOUT.md](./PLAN-LAYOUT.md) | — | Plan directory layout and plugin directory layout. |
| [MULTI-IDE.md](./MULTI-IDE.md) | — | Exporting z-harness to Cursor, Codex CLI, and Antigravity. |
| [environment-knobs.md](./environment-knobs.md) | — | Environment variable reference for all tunables. |
| [telemetry.md](./telemetry.md) | — | Telemetry event kinds, compaction policy. |
| [plugin-author-conventions.md](./plugin-author-conventions.md) | — | Conventions for downstream `.claude/skills/` authors. |
| [limitations.md](./limitations.md) | — | Known v1 limitations. |

