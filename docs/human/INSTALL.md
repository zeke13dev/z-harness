# INSTALL — z-harness Installation Guide

> Last updated: 2026-06-29

## Overview

z-harness ships two public beta install surfaces:

1. **Setup CLI bootstrap** (`z-harness setup`) for first-run detection, provider/auth checks, and Claude/OMP release guidance.
2. **Host plugin/export install** for Claude Code and OMP. Claude has the direct public plugin installer; OMP uses package/export layouts. Non-core hosts remain explicit source/dev or advanced export-only paths.

The canonical command source is `skills/<id>/SKILL.md`; canonical agent source is `agents/`; runtime/export code is under `runtime/` and `z_harness_cli/`. The prod allowlist is `z_harness_cli.release_surface`: public defaults are Claude + OMP, while generated mirrors remain scratch output rather than release source.

## Setup CLI bootstrap

```bash
curl -fsSL https://github.com/zeke13dev/z-harness/releases/latest/download/install.sh | sh
z-harness setup --target all --dry-run
z-harness setup --target claude --install
```

The curl installer fetches `latest.json`, requires an HTTPS wheel URL and a 64-character SHA-256 digest, verifies the downloaded wheel, then installs it via `uv tool install`. The CLI is an onboarding/setup entrypoint; day-to-day workflows run inside the selected harness.

## Plugin install locations

Claude Code installs to:

```text
~/.claude/plugins/z-harness@zeke-tools
```

Codex source/dev plugin installs still use the personal marketplace at:

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
# advanced/source-only plugin path while developing Codex support
bash install.sh --target=codex
# source/dev all still includes explicit dev targets
bash install.sh --target=all
```

Source mode requires `.git/`, `skills/`, `agents/`, and `runtime/` in the checkout. It symlinks the checkout into the selected host plugin location.

## CLI setup and plugin wrapper

After installing the wheel, use setup for first-run guidance or direct plugin install for Claude:

```bash
z-harness setup --target all --dry-run
z-harness setup --target claude --install --force
z-harness install --target=claude
```

`setup --target all` selects the release defaults (Claude + OMP) in installed prod artifacts. Source checkouts keep explicit dev paths such as `z-harness setup --target codex --install --force`. `install` wraps `install.sh` from the installed harness payload; Claude is the public plugin install path.

## Tarball mode

Tarball mode installs an audited plugin payload without keeping a source clone:

```bash
bash install.sh --target=claude --tarball=<release-tarball-url>
bash install.sh --target=claude --tarball=<release-tarball-url> --tarball-sha256=<sha256>
```

Release tarballs are built by `Z_HARNESS_RELEASE_SURFACE=prod bash scripts/bundle-plugin.sh`, audited by `scripts/audit-tarball.sh`, and uploaded by release CI. Manifest-backed installs verify `plugin_tarball_sha256` before extracting or replacing an existing plugin install. They must include `skills/`, `agents/`, `runtime/`, `scripts/`, plugin manifests, and docs needed by the shipped commands, excluding dev-only experimental surfaces from the public prod tarball.

## OMP package export and advanced target exports

OMP is the public package/export target:

```bash
z-harness export --host omp --surface prod --out ./temp/z-harness-omp --force
```

Use `--surface prod` for public-beta OMP exports. It keeps `/z-learn`, `/z-sharpen`, `/z-grill`, and `/z-brainstorm`, while hiding dev-only experimental commands such as `/z-research`, `/z-map`, `/z-overnight`, `/z-attend`, and `z-axiom-*`.

Cursor, Codex, Antigravity, pi, Windsurf, Kiro, Cline, and Copilot remain explicit dev/advanced or export-only targets; they are not selected by installed prod `setup --target all` or prod export defaults.

## Updating

z-harness has no silent background updater.

- **CLI wheel install:** run `z-harness update` explicitly; it fetches the release manifest, verifies the downloaded wheel, then upgrades via `uv`.
- **Claude plugin source symlink:** run `/z-update` in Claude or `z-harness update` from the checkout; dirty trees abort and only `git pull --ff-only` is attempted. Source/dev Codex symlinks follow the same deterministic source-checkout update path.
- **Tarball plugin install:** host `/z-update` does not self-swap tarballs. Reinstall through the deterministic manifest-backed installer, for example `z-harness install --target=claude --force` (use `python3 -m z_harness_cli install ...` from the plugin payload if the executable is not on `PATH`), which passes the audited tarball URL and SHA-256 to `install.sh`.
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
z-harness install --target=claude --force
```

## Requirements

- Python 3.11+.
- `uv` for the curl/CLI install path.
- At least one supported host CLI/IDE for runtime use.
- Optional provider CLIs (`codex`, `gemini`, `claude`, `ollama`, `agy`) depending on which workflows you run.

## Uninstall

```bash
rm ~/.claude/plugins/z-harness@zeke-tools
# source/dev Codex plugin cleanup, if you opted into that explicit path:
codex plugin remove z-harness@personal
rm ~/plugins/z-harness
uv tool uninstall z-harness
```

Removing a symlink install removes only the symlink, not your source checkout.
