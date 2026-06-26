# z-harness

z-harness is a plugin/workflow layer for existing AI coding harnesses. It adds planning, implementation, review, documentation, and release workflows through host-native skills/agents where available, with explicit fallbacks where a host cannot support the full orchestration model.

## Beta status

This project is pre-1.0 beta software. It can orchestrate tools that read and write production code. Use it in a clean worktree, review generated plans before execution, and keep the review/test gates enabled. Expect host-specific fidelity differences while the export drivers stabilize.

## Supported surfaces

- **Claude Code plugin:** primary/native command and agent workflow.
- **Oh My Pi / OMP:** first-class package/export target; native claims are bounded by the documented parity gate.
- **Cursor and Codex:** supported setup/export/injection targets; multi-agent orchestration remains explicitly degraded or blocked until host-native subagent parity is proven.
- **Python CLI (`z-harness`):** small setup/onboarding entrypoint for installing/configuring existing harnesses. It is not the day-to-day z-harness workflow surface.

See `CAPABILITIES.md` for the host matrix and known fidelity limits.

## Install

### Setup bootstrap

```bash
curl -fsSL https://github.com/zeke13dev/z-harness/releases/latest/download/install.sh | sh
z-harness setup --target claude --dry-run
z-harness setup --target claude --install
```

The CLI installer uses the release manifest, downloads the wheel over HTTPS, verifies SHA-256, and installs via `uv tool install`. Use `z-harness setup --target all --dry-run` to inspect Claude, OMP, Cursor, and Codex readiness without writing host config.

### Source checkout / plugin development

```bash
git clone https://github.com/zeke13dev/z-harness
cd z-harness
bash install.sh --target=claude
# or
bash install.sh --target=codex
```

Source installs symlink the checkout into the host plugin location. Edits take effect after the host reloads its plugin/cache.

### Export artifacts

```bash
make export
# or produce a public-beta surface that hides experimental commands
z-harness export --host codex --surface prod --out temp/exports/codex --force
```

Generated exports go under `temp/exports/` by default and are not committed release source. Release tarballs are audited before publication.

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
