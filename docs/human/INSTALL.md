# INSTALL — z-harness Installation Guide

> Last updated: 2026-07-09

## Overview

z-harness ships three public beta install surfaces:

1. **Setup CLI bootstrap** (`z-harness setup`) for first-run detection, provider/auth checks, and Claude/OMP/Codex release guidance.
2. **Direct plugin install** for Claude Code and Codex.
3. **Package/export install** for OMP. Non-core hosts remain explicit source/dev or advanced export-only paths.

The canonical command source is `skills/<id>/SKILL.md`; canonical agent source is `agents/`; runtime/export code is under `runtime/` and `z_harness_cli/`. The prod allowlist is `z_harness_cli.release_surface`: public defaults are Claude, OMP, and Codex, while generated mirrors remain scratch output rather than release source.

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

Codex plugin installs use the personal marketplace at:

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
bash install.sh --target=codex
bash install.sh --target=all
```

Source mode requires `.git/`, `skills/`, `agents/`, and `runtime/` in the checkout. It symlinks the checkout into the selected host plugin location.

## CLI setup and plugin wrapper

After installing the wheel, use setup for first-run guidance or direct plugin install for Claude/Codex:

```bash
z-harness setup --target all --dry-run
z-harness setup --target all --install --force
z-harness install --target=codex
z-harness install --target=all
```

`setup --target all` selects the release defaults (Claude, OMP, and Codex) in installed prod artifacts. `install` wraps `install.sh` from the installed harness payload; Claude and Codex are the public direct plugin install paths, while OMP remains package/export guidance.

## Tarball mode

Tarball mode installs an audited plugin payload without keeping a source clone:

```bash
bash install.sh --target=claude --tarball=<release-tarball-url>
bash install.sh --target=codex --tarball=<release-tarball-url>
bash install.sh --target=all --tarball=<release-tarball-url>
bash install.sh --target=claude --tarball=<release-tarball-url> --tarball-sha256=<sha256>
```

Release tarballs are built by `Z_HARNESS_RELEASE_SURFACE=prod bash scripts/bundle-plugin.sh`, audited by `scripts/audit-tarball.sh`, and uploaded by release CI. Manifest-backed installs verify `plugin_tarball_sha256` before extracting or replacing an existing plugin install. They must include `skills/`, `agents/`, `runtime/`, `scripts/`, plugin manifests, and docs needed by the shipped commands, excluding dev-only experimental surfaces from the public prod tarball. Replacement is staged and atomic: `install.sh` moves the existing install aside, moves the new payload into place, and rolls back to the staged backup if either move fails (see `replace_with_staged_install` / `replace_two_staged_installs_atomically` in `install.sh`).

## OMP package export and advanced target exports

OMP is the public package/export target:

```bash
z-harness export --host omp --surface prod --out ./temp/z-harness-omp --force
```

Use `--surface prod` for public-beta OMP exports. It keeps `/z-learn`, `/z-sharpen`, `/z-grill`, and `/z-brainstorm`, while hiding dev-only experimental commands such as `/z-research`, `/z-overnight`, `/z-attend`, and `z-axiom-*`.

Cursor, Antigravity, pi, Windsurf, Kiro, Cline, and Copilot remain explicit dev/advanced or export-only targets; they are not selected by installed prod `setup --target all` or prod export defaults. Codex is selected by prod defaults, but remains `flattened` rather than native.

## Updating

z-harness has no silent background updater. `/z-update` (and the `z-harness update` CLI it wraps) is a thin host skill — `skills/z-update/SKILL.md` does no manifest parsing or install-mode logic itself; it just runs `z-harness update` (falling back to `python3 -m z_harness_cli update` when the executable is not on `PATH`) and surfaces the CLI's exact output. All release-manifest fetch/validation, version comparison, and install-mode dispatch live in `z_harness_cli/commands/update.py` and `z_harness_cli/release.py`.

`z-harness update` fetches `latest.json`, compares the installed version against it, and then behaves per install mode:

- **CLI wheel install (`uv tool install`):** downloads the release wheel, verifies its SHA-256 against the manifest, then upgrades via `uv tool install --upgrade`. Aborts on a checksum mismatch.
- **Claude/Codex plugin source symlink:** aborts on a dirty checkout (`git status --porcelain` non-empty); otherwise runs `git pull --ff-only` only — it never merges, resets, or force-updates the source tree.
- **Tarball/runtime plugin install:** does **not** self-swap the tarball. It prints a manifest-backed reinstall command (`z-harness install --target=<host> --force`, or `python3 -m z_harness_cli install --target=<host> --force` when off `PATH`) and exits non-zero without changing anything; the actual audited, atomic tarball replacement happens inside `install.sh`, not inside `update`.
- **Dev build / non-semver version string:** prints a notice only; never blocks or auto-updates. Update a clean checkout with `git pull --ff-only` or reinstall a tagged release with `z-harness install`.
- **MCP `z_update` tool:** read-only version check; it does not mutate installs.

**Caveat:** unlike the pre-2026-06-29 SKILL.md, the current symlink-update path does **not** refresh the Claude Code plugin cache or re-run `codex plugin add` after `git pull --ff-only` — it only tells you to restart the host. If your host loads from a versioned plugin cache rather than the live repo symlink, or if the Codex marketplace registration needs refreshing, you may need to restart the host and/or manually rerun `codex plugin add z-harness@personal` after `/z-update`.

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
z-harness install --target=all --force
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
