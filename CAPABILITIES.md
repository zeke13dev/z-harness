# z-harness capabilities matrix

This document summarizes the pre-1.0 beta support level for each public host and export target. `runtime.release_surface` is the canonical positive, default-deny release contract: it classifies the intended prod skills, agents, scripts/backends, schemas, public documents, generated requirements, and host claims. An unclassified staged path is invalid; it is not implicitly shipped.

## Fidelity tiers

- **native** — command semantics match the harness contract directly.
- **high** — most commands are available; unsupported host constructs are translated with explicit fallback instructions.
- **flattened** — single-agent translation; multi-agent orchestration is degraded or blocked.
- **export-only** — z-harness can generate files for the target, but no runtime adapter/launcher is promised.

## Hosts

### Public release support

| Host / target | Tier | Runtime CLI adapter | Export support | Notes |
|---|---:|---:|---:|---|
| Claude Code | primary/native | yes | plugin install | The primary public beta workflow. |
| Python CLI (`z-harness`) | supported | n/a | bootstrap, install, update | Supported release bootstrap and lifecycle surface. |
| OMP | conditional native | yes | `.omp/z-harness/` package | Native status is public only when clean installed-wheel proof is available. |
| Codex | partial/preview | yes | plugin/export preview | Native skill/custom-agent/MCP artifacts may be emitted, but CLI orchestration is not a native public claim. |

### Explicit dev/advanced or export-only targets

| Host / target | Tier | Runtime CLI adapter | Export support | Notes |
|---|---:|---:|---:|---|
| Antigravity | dev/advanced | yes | `.agent/` workflows/rules/skills | Not a public release default. |
| Cursor | dev/advanced | yes | `.cursor/skills` + rules | Not a public release default. |
| legacy pi | export-only | no | pi compatibility exports | Compatibility export only. |
| Windsurf | export-only | no | rules | Export only. |
| Kiro | export-only | no | steering docs | Export only. |
| Cline | export-only | no | `.clinerules/` | Export only. |
| Copilot | export-only | no | instructions/prompts | Export only. |

## Unsupported or degraded constructs

Non-native hosts may not support these z-harness runtime constructs directly:

- subagent dispatch (`Agent(...)` / task fan-out),
- programmatic skill invocation,
- structured `AskUserQuestion` return values,
- multi-provider routing through `providers.json`,
- multi-model review loops,
- long-running telemetry handshakes across host context resets.

Export drivers must not silently drop those constructs. They preserve `RUNTIME-GATE` comments and replace unsupported call blocks with target-specific fallback instructions.

Codex exports custom-agent definitions, native `SKILL.md` files, plugin metadata, and MCP config, but current Codex CLI dispatch does not have a proven z-harness native subagent primitive. Codex command orchestration therefore remains flattened/degraded/blocked until runtime primitive and driver-hook evidence exists.

## Release contract

- `runtime.release_surface` is the single release-surface contract consumed by CLI and runtime filtering, staging, and audits; no consumer keeps a separate implicit allowlist.
- The prod surface explicitly excludes `/z-attend`, `/z-explore`, `/z-map`, `/z-overnight`, `/z-research`, user-facing `z-axiom-*`, research-only agents, Hermes/Discord orchestration, and generated development mirrors. Those remain development resources unless later promoted with blocking evidence.
- A clean candidate is the exact reviewed source/artifact identity exercised from a tracked clean checkout or archive, isolated HOME/config, installed wheel and plugin payloads, and blocking evidence for every claimed host, with no ignored files, untracked files, user configuration, or dev-only dependency supplying required behavior.

## Safety posture

- Release artifacts are expected to be self-contained and smoke-tested from an installed wheel or audited tarball.
- Tarballs must exclude runtime state, provider files, archives, generated scratch exports, local worktrees, and maintainer-specific paths.
- Commands that mutate code or shared state keep explicit review/confirmation gates unless a documented no-ask policy resolves them.

## More detail

- Detailed install/update flows: `docs/human/INSTALL.md`.
- Export implementation: `runtime/drivers/*/export.py`.
- CLI host adapters: `z_harness_cli/adapters/`.
