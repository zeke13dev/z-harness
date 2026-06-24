# INSTALL — z-harness Installation Guide

> Last updated: 2026-06-24

## Overview

z-harness ships two beta install surfaces:

1. **Python CLI bootstrap** (`z-harness` / `zh`) for doctor/export/launch/MCP/update.
2. **Host plugin install** for Claude Code and Codex, either from a source checkout or an audited release tarball.

The canonical command source is `skills/<id>/SKILL.md`; canonical agent source is `agents/`; runtime/export code is under `runtime/` and `z_harness_cli/`.

## CLI bootstrap

```bash
curl -fsSL https://github.com/zeke13dev/z-harness/releases/latest/download/install.sh | sh
z-harness doctor
z-harness install --target=claude
z-harness launch
```

The curl installer fetches `latest.json`, requires an HTTPS wheel URL and a 64-character SHA-256 digest, verifies the downloaded wheel, then installs it via `uv tool install`.

## Plugin install locations

Claude Code installs to:

```text
~/.claude/plugins/z-harness@zeke-tools
```

Codex installs through the personal marketplace at:

```text
~/.agents/plugins/marketplace.json
```

The Codex marketplace entry points at:

```text
~/plugins/z-harness
```

## Source checkout install

Use source checkout mode for contributors or active local development:

```bash
git clone https://github.com/zeke13dev/z-harness
cd z-harness
bash install.sh --target=claude
# or
bash install.sh --target=codex
# or both
bash install.sh --target=all
```

Source mode requires `.git/`, `skills/`, `agents/`, and `runtime/` in the checkout. It symlinks the checkout into the selected host plugin location.

## CLI plugin wrapper

After installing the wheel, the same plugin install can be launched through the CLI:

```bash
z-harness install --target=claude
z-harness install --target=codex
z-harness install --target=all --force
```

This command wraps `install.sh` from the installed harness payload so CLI users do not hit a placeholder command.

## Tarball mode

Tarball mode installs an audited plugin payload without keeping a source clone:

```bash
bash install.sh --target=claude --tarball=<release-tarball-url>
bash install.sh --target=codex --tarball=<release-tarball-url>
```

Release tarballs are built by `scripts/bundle-plugin.sh`, audited by `scripts/audit-tarball.sh`, and uploaded by release CI. They must include `skills/`, `agents/`, `runtime/`, `scripts/`, plugin manifests, and docs needed by the shipped commands.

## Updating

z-harness has no silent background updater.

- **CLI wheel install:** run `z-harness update` explicitly.
- **Claude/Codex plugin source symlink:** run `/z-update` in the host or pull the checkout manually; dirty trees abort.
- **Tarball plugin install:** run the host `/z-update` flow or reinstall from the audited tarball URL.
- **MCP `z_update` tool:** read-only version check; it does not mutate installs.

## Data and config locations

Runtime plan/archive/telemetry state resolves outside the repository by default, for example:

```text
~/.local/state/z-harness/<repo-id>/
```

Repo-local `.z-harness/` contains per-user provider/config overrides and is ignored by git. Do not commit provider registries, plan archives, metrics, or generated export scratch trees.

## Overwriting an existing plugin install

If a plugin path already exists as a regular directory, install refuses to replace it unless `--force` is passed:

```bash
bash install.sh --target=claude --force
z-harness install --target=codex --force
```

## Requirements

- Python 3.11+.
- `uv` for the curl/CLI install path.
- At least one supported host CLI/IDE for runtime use.
- Optional provider CLIs (`codex`, `gemini`, `claude`, `ollama`, `agy`) depending on which workflows you run.

## Uninstall

```bash
rm ~/.claude/plugins/z-harness@zeke-tools
codex plugin remove z-harness@personal
rm ~/plugins/z-harness
uv tool uninstall z-harness
```

Removing a symlink install removes only the symlink, not your source checkout.
