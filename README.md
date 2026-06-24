# z-harness

z-harness is a workflow harness for AI-assisted software development. It provides commands, agents, skills, runtime dispatch, export drivers, and safety gates for planning, implementation, audit, review, documentation, and release workflows.

## Beta status

This project is pre-1.0 beta software. It can orchestrate tools that read and write production code. Use it in a clean worktree, review generated plans before execution, and keep the review/test gates enabled. Expect host-specific fidelity differences while the export drivers stabilize.

## Supported surfaces

- **Claude Code plugin:** native/highest-fidelity command and agent workflow.
- **Codex, Cursor, Antigravity:** exported or injected host-specific workflows with documented fidelity limits.
- **Export-only targets:** pi, Windsurf, Kiro, Cline, and Copilot are generated artifacts; they do not all have runtime adapters.
- **Python CLI (`z-harness` / `zh`):** installs, exports, launches, serves MCP, checks status, and updates the local install.

See `CAPABILITIES.md` for the host matrix and known fidelity limits.

## Install

### CLI bootstrap

```bash
curl -fsSL https://github.com/zeke13dev/z-harness/releases/latest/download/install.sh | sh
z-harness doctor
z-harness install --target=claude
z-harness launch
```

The CLI installer uses the release manifest, downloads the wheel over HTTPS, verifies SHA-256, and installs via `uv tool install`.

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
# or
z-harness export --host codex --out temp/exports/codex --force
```

Generated exports go under `temp/exports/` by default and are not committed release source. Release tarballs are audited before publication.

## Configuration and state

z-harness resolves runtime state outside the repository by default, under the platform state directory, e.g. `~/.local/state/z-harness/<repo-id>/`. Repo-local `.z-harness/` contains per-user provider/config overrides and is ignored by git.

## Development checks

```bash
make test
make test-sh
make export
bash scripts/bundle-plugin.sh
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
