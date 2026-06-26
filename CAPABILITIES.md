# z-harness capabilities matrix

This document summarizes the beta support level for each shipped host/export target. The canonical implementation source is `skills/<id>/SKILL.md`, `agents/`, `personas/`, `runtime/`, and `scripts/`.

## Fidelity tiers

- **native** — command semantics match the harness contract directly.
- **high** — most commands are available; unsupported host constructs are translated with explicit fallback instructions.
- **flattened** — single-agent translation; multi-agent orchestration is degraded or blocked.
- **export-only** — z-harness can generate files for the target, but no runtime adapter/launcher is promised.

## Hosts

| Host / target | Tier | Runtime CLI adapter | Export support | Notes |
|---|---:|---:|---:|---|
| Claude Code | native | yes | plugin/source install | Best-supported beta path. |
| Antigravity | high | yes | `.agent/` workflows/rules/skills | Some subagent/provider-routing features require explicit fallback instructions. |
| Cursor | flattened | yes | `.cursor/skills` + rules | Supported setup/export target; subagent fan-out is not native and remains blocked until parity tests prove otherwise. |
| Codex | flattened | yes | `skills/` + `.codex-plugin/plugin.json` | Supported setup/export target; MCP registration is global/persistent in `~/.codex/config.toml`; subagent fan-out is not native. |
| OMP / pi | native/export | yes for OMP, no for legacy pi | `.omp/z-harness/` package and pi compatibility exports | OMP native claims are bounded by parity evidence; legacy pi remains export-only. |
| Windsurf | export-only | no | rules | Curated/full export only. |
| Kiro | export-only | no | steering docs | Curated/full export only. |
| Cline | export-only | no | `.clinerules/` | Pointer export by default to avoid context bloat. |
| Copilot | export-only | no | instructions/prompts | Pointer/curated export only. |

## Unsupported or degraded constructs

Non-native hosts may not support these z-harness runtime constructs directly:

- subagent dispatch (`Agent(...)` / task fan-out),
- programmatic skill invocation,
- structured `AskUserQuestion` return values,
- multi-provider routing through `providers.json`,
- multi-model review loops,
- long-running telemetry handshakes across host context resets.

Export drivers must not silently drop those constructs. They preserve `RUNTIME-GATE` comments and replace unsupported call blocks with target-specific fallback instructions.

## Release surfaces

- **dev/main surface:** includes experimental research commands for local development.
- **prod surface:** hides `/z-research`, `/z-explore`, `/z-map` (legacy), `/z-overnight`, `/z-attend`, and `z-axiom-*` by default while keeping `/z-learn`, `/z-sharpen`, `/z-grill`, and `/z-brainstorm`.
- Use `z-harness export --surface prod ...` for public-beta exports.

## Safety posture

- Release artifacts are expected to be self-contained and smoke-tested from an installed wheel or audited tarball.
- Tarballs must exclude runtime state, provider files, archives, generated scratch exports, local worktrees, and maintainer-specific paths.
- Commands that mutate code or shared state keep explicit review/confirmation gates unless a documented no-ask policy resolves them.

## More detail

- Detailed install/update flows: `docs/human/INSTALL.md`.
- Export implementation: `runtime/drivers/*/export.py`.
- CLI host adapters: `z_harness_cli/adapters/`.
