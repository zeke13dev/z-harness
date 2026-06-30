# z-harness

z-harness is a plugin/workflow layer for existing AI coding harnesses. It adds planning, implementation, review, documentation, and release workflows through host-native skills/agents where available, with explicit fallbacks where a host cannot support the full orchestration model.

## Beta status

This project is pre-1.0 beta software. It can orchestrate tools that read and write production code. Use it in a clean worktree, review generated plans before execution, and keep the review/test gates enabled. Expect host-specific fidelity differences while the export drivers stabilize.

## Supported release surfaces

- **Claude Code plugin:** primary/native command and agent workflow.
- **Oh My Pi / OMP:** first-class package/export target; native claims are bounded by the documented parity gate.
- **Advanced/dev exports:** Cursor, Codex, Antigravity, pi, Windsurf, Kiro, Cline, and Copilot exporters remain in source and explicit export paths, but they are not public release defaults.
- **Python CLI (`z-harness`):** small setup/onboarding entrypoint for Claude/OMP install and export guidance. It is not the day-to-day z-harness workflow surface.

See `CAPABILITIES.md` for the host matrix and known fidelity limits.

## Install

### Setup bootstrap

```bash
curl -fsSL https://github.com/zeke13dev/z-harness/releases/latest/download/install.sh | sh
z-harness setup --target claude --dry-run
z-harness setup --target claude --install
```

The CLI installer uses the release manifest, downloads the wheel over HTTPS, verifies SHA-256, and installs via `uv tool install`. Use `z-harness setup --target all --dry-run` to inspect the release defaults: Claude Code and OMP readiness without writing host config.

### Source checkout / plugin development

```bash
git clone https://github.com/zeke13dev/z-harness
cd z-harness
bash install.sh --target=claude
# advanced/source-only plugin path remains available when developing Codex support
bash install.sh --target=codex
```
Source installs symlink the checkout into the host plugin location. Edits take effect after the host reloads its plugin/cache.

### Export artifacts

```bash
make export
# Installed public wheels/tarballs default to the prod surface.
z-harness export --host omp --out temp/exports/omp --force
# Explicit advanced/dev export paths remain available in source checkouts.
z-harness export --host codex --surface dev --out temp/exports/codex-dev --force
```

The manifest in `z_harness_cli.release_surface` defines which skills, agents, MCP tools, scripts/backends, generated mirrors, and docs are prod-visible. Canonical command source is `skills/<id>/SKILL.md`; generated exports go under `temp/exports/` by default and are not committed release source. Release tarballs and staged wheels are audited against the manifest before publication.

## Configuration and state

z-harness resolves runtime state outside the repository by default, under the platform state directory, e.g. `~/.local/state/z-harness/<repo-id>/`. Repo-local `.z-harness/` contains per-user provider/config overrides and is ignored by git.

## Development checks

```bash
make test
make test-sh
make export
Z_HARNESS_RELEASE_SURFACE=prod bash scripts/bundle-plugin.sh
```

Release CI also builds the wheel, installs it in isolation, runs CLI/export smoke checks, and audits the plugin tarball.

## Documentation map

- `docs/human/INSTALL.md` — detailed install/update flows.
- `docs/human/capabilities-matrix.md` — host fidelity details.
- `docs/human/SETUP.md` — configuration wizard and posture presets.
- `skills/` — canonical command/skill source.
- `agents/` — canonical agent definitions.
- `runtime/drivers/` — host/export driver implementations.

## License

MIT. See `LICENSE`.
