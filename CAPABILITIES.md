# z-harness capabilities matrix

This document summarizes the beta support level for each shipped host/export target. The canonical implementation source is `skills/<id>/SKILL.md`, `agents/`, `personas/`, `runtime/`, and `scripts/`.

## Fidelity tiers

- **native** — command semantics match the harness contract directly.
- **high** — most commands are available; unsupported host constructs are translated with explicit fallback instructions.
- **flattened** — single-agent translation; multi-agent orchestration is degraded or blocked.
- **export-only** — z-harness can generate files for the target, but no runtime adapter/launcher is promised.

## Hosts

### Public release defaults

| Host / target | Tier | Runtime CLI adapter | Export support | Notes |
|---|---:|---:|---:|---|
| Claude Code | native | yes | plugin/source install | Best-supported beta path and public plugin installer. |
| OMP | native | yes | `.omp/z-harness/` package | First-class public package/export target; native claims are bounded by parity evidence. |

### Explicit dev/advanced or export-only targets

| Host / target | Tier | Runtime CLI adapter | Export support | Notes |
|---|---:|---:|---:|---|
| Antigravity | high | yes | `.agent/` workflows/rules/skills | Explicit dev/advanced path; not selected by installed prod defaults. |
| Cursor | flattened | yes | `.cursor/skills` + rules | Explicit dev/advanced export/injection; subagent fan-out is not native. |
| Codex | flattened | yes | `skills/` + `.codex-plugin/plugin.json` | Explicit source/dev plugin/export path; MCP registration is global/persistent in `~/.codex/config.toml`; subagent fan-out is not native. |
| legacy pi | export-only | no | pi compatibility exports | Explicit compatibility export-only target. |
| Windsurf | export-only | no | rules | Explicit export-only target. |
| Kiro | export-only | no | steering docs | Explicit export-only target. |
| Cline | export-only | no | `.clinerules/` | Explicit export-only target. |
| Copilot | export-only | no | instructions/prompts | Explicit export-only target. |

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

- `z_harness_cli.release_surface` is the single release-surface manifest. MCP tool registration, CLI/runtime export filtering, prod tarball pruning, release staging, and tarball audits read that contract instead of maintaining separate hidden-command lists.
- **dev/main surface:** includes experimental research, axiom, Hermes/Discord/tmux, and generated-mirror resources for local development.
- **prod surface:** ships the manifest-approved public surface and physically excludes `/z-research`, `/z-explore`, `/z-map` (legacy), `/z-overnight`, `/z-attend`, `z-axiom-*`, their dev-only agents, Hermes/Discord/tmux orchestration paths, and generated mirrors.
- Installed wheels/tarballs default to prod, and public CLI/setup/export auto-selection defaults to Claude + OMP. Source checkouts can opt into the full development surface with `z-harness export --surface dev ...` or explicit dev/advanced hosts.

## Safety posture

- Release artifacts are expected to be self-contained and smoke-tested from an installed wheel or audited tarball.
- Tarballs must exclude runtime state, provider files, archives, generated scratch exports, local worktrees, and maintainer-specific paths.
- Commands that mutate code or shared state keep explicit review/confirmation gates unless a documented no-ask policy resolves them.

## More detail

- Detailed install/update flows: `docs/human/INSTALL.md`.
- Export implementation: `runtime/drivers/*/export.py`.
- CLI host adapters: `z_harness_cli/adapters/`.
