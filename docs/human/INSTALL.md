# INSTALL — z-harness Installation Guide

> Last updated: 2026-07-21

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

Release tarballs are built from one canonical stage by `scripts/bundle-plugin.sh`, audited by `scripts/audit-tarball.sh`, and uploaded by release CI. Manifest-backed installs verify `plugin_tarball_sha256` and validate archive paths and links before extraction. They must include `skills/`, `agents/`, `runtime/`, `scripts/`, plugin manifests, and docs needed by the shipped commands, excluding dev-only experimental surfaces from the public prod tarball.

Replacement uses the durable lifecycle transaction in `install.sh`. Before the first host-visible mutation it validates every selected destination, inventories CLI/Claude/Codex, records the candidate, and persists reversible pre-state under `${XDG_STATE_HOME:-$HOME/.local/state}/z-harness/lifecycle/`. One exclusive owner lock covers payloads, Codex marketplace/registration, optional exports, and an optional uv-tool replacement handed off by `z-harness update`. Candidate-version coherence is verified before commit. A failure rolls components back in reverse order; an interrupted transaction is recovered on the next lifecycle invocation, and unresolved recovery state remains fail-closed instead of being discarded.

## OMP package export and advanced target exports

OMP is the public package/export target:

```bash
z-harness export --host omp --surface prod --out ./temp/z-harness-omp --force
```

Use `--surface prod` for public-beta OMP exports. It keeps `/z-learn`, `/z-sharpen`, `/z-grill`, and `/z-brainstorm`, while hiding dev-only experimental commands such as `/z-research`, `/z-overnight`, `/z-attend`, and `z-axiom-*`.

Cursor, Antigravity, pi, Windsurf, Kiro, Cline, and Copilot remain explicit dev/advanced or export-only targets; they are not selected by installed prod `setup --target all` or prod export defaults. Codex is selected by prod defaults, but remains `flattened` rather than native.

## Updating

z-harness has no silent background updater. `/z-update` (and the `z-harness update` CLI it wraps) is a thin host skill — `skills/z-update/SKILL.md` does no manifest parsing or install-mode logic itself; it just runs `z-harness update` (falling back to `python3 -m z_harness_cli update` when the executable is not on `PATH`) and surfaces the CLI's exact output. All release-manifest fetch/validation, version comparison, and install-mode dispatch live in `z_harness_cli/commands/update.py` and `z_harness_cli/release.py`.

`z-harness update` fetches `latest.json`, inventories the CLI and Claude/Codex payloads independently, compares each detected component to the explicit release candidate, and then chooses one coherent transaction:

- **Packaged Claude/Codex payloads:** update downloads the audited tarball identity from the manifest and invokes `install.sh --tarball=<url> --tarball-sha256=<digest> --force`. The selected packaged hosts are replaced directly; missing hosts are not added. If a stale uv CLI is present, its verified wheel, tool root, and launchers join the same durable transaction through an ownership-token handoff.
- **CLI-only uv-tool install:** downloads and verifies the wheel, durably backs up the confined uv tool root and `z-harness`/`zh` launchers, upgrades with `uv tool install --upgrade`, verifies the reported candidate version, and restores the pre-state on failure or interrupted recovery.
- **Claude/Codex source symlinks:** require one clean checkout under `HOME`. Update fetches the manifest candidate tag, verifies its canonical `VERSION`, requires the installed commit to be an ancestor, writes a durable old-HEAD recovery record, and applies only `git merge --ff-only`. Candidate mismatch or failed coherence restores with `git reset --keep`; update never creates a merge commit or force-resets a checkout.
- **Mixed/incoherent installs:** mixed source-symlink and packaged hosts, symlink hosts backed by different checkouts, a stale non-uv CLI beside packaged hosts, or any component newer than the candidate are rejected without mutation. Missing Claude/Codex installs remain missing.
- **Dev build / non-release version:** prints a notice and does not auto-update. Use the source checkout workflow or reinstall a tagged release explicitly.
- **MCP `z_update` tool:** remains a read-only version check; it does not mutate installs.

Every invocation first acquires the lifecycle lock and attempts recovery of retained CLI, source, or installer journals before fetching a new manifest. Concurrent live owners are rejected; stale lock ownership is reclaimed only after PID/start-identity validation.

### Update implementation entry points

- `skills/z-update/SKILL.md:10` — `/z-update` — thin host wrapper around the deterministic CLI.
- `z_harness_cli/commands/update.py:1021` — `run` — recovery, manifest fetch, inventory, comparison, and dispatch.
- `z_harness_cli/commands/update.py:156` — `inventory_components` — independently classify CLI, Claude, and Codex.
- `z_harness_cli/commands/update.py:589` — `_apply_detected_transaction` — select one coherent component-set update.
- `z_harness_cli/commands/update.py:536` — `_apply_packaged_transaction` — hand packaged hosts and optional uv replacement to `install.sh`.
- `z_harness_cli/commands/update.py:686` — `_apply_uv_upgrade` — verified, recoverable standalone uv-tool replacement.
- `z_harness_cli/commands/update.py:879` — `_apply_candidate_source_update` — exact-tag, fast-forward-only source update with recovery.
- `install.sh:1197` — `rollback_lifecycle_transaction` — reverse mutations from durable pre-state.
- `install.sh:1254` — `recover_lifecycle_transaction` — resume rollback after interruption.
- `install.sh:1569` — `run_lifecycle_transaction` — validate, prepare, mutate, verify coherence, and commit.
- `z_harness_cli/release.py:262` — `fetch_manifest` — fetch and validate the release manifest.
- `z_harness_cli/release.py:408` — `compare_versions` — classify installed versions against the candidate.
- `scripts/bundle-plugin.sh:1` — deterministic audited tarball builder for the canonical stage.
- `scripts/version.sh:1` — observational checkout telemetry; never release identity.

Updating depends on the release manifest and canonical packaging contract, while the actual mutation boundary is shared with direct install through `install.sh`. The lifecycle state directory is operational recovery data, not release identity or repository source.

**Gotchas:** restart the affected host after a successful update. Source updates do not separately refresh a versioned Claude cache or re-run Codex registration; packaged Codex transactions do update the marketplace and verify registration when the `codex` CLI is available. Corrupt/unconfined recovery paths, uncertain Codex registration compensation, and incomplete rollback retain recovery state and block further mutation for manual inspection.

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
