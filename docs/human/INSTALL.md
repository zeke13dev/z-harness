# INSTALL — z-harness Installation Guide

> Last updated: 2026-05-24

## Overview

z-harness can be installed for Claude Code or Codex. Both hosts support
**symlink** mode for active development and **tarball** mode for stable
deploys.

---

## Plugin install locations

Claude Code installs to:

```
~/.claude/plugins/z-harness@zeke-tools
```

Codex installs through the personal marketplace at:

```
~/.agents/plugins/marketplace.json
```

The marketplace entry points at:

```
~/plugins/z-harness
```

In symlink mode these locations point to your local clone. In tarball mode
they contain an extracted directory.

---

## Symlink mode (from a local clone)

Symlink mode is for contributors or users who want live edits to go live
immediately without re-installing.

**Prerequisites:** Git clone with `.git/`, `commands/`, and `agents/` present
in the current working directory.

```bash
git clone https://github.com/<org>/z-harness
cd z-harness
bash install.sh
```

`install.sh` defaults to Claude Code. It detects the presence of
`.git + commands/ + agents/` and creates:

```
~/.claude/plugins/z-harness@zeke-tools -> <absolute path to clone>
```

For Codex:

```bash
bash install.sh --target=codex
```

This creates:

```
~/plugins/z-harness -> <absolute path to clone>
```

It also creates or updates `~/.agents/plugins/marketplace.json` and runs:

```bash
codex plugin add z-harness@personal
```

For both hosts:

```bash
bash install.sh --target=all
```

Any edit you make in the repo takes effect immediately in Claude Code — no
re-install needed. Codex snapshots plugins into its cache, so after editing
plugin skills or metadata, re-run `codex plugin add z-harness@personal` and
start a new Codex thread.

---

## Tarball mode (from a release URL)

Tarball mode is for users who want a stable, versioned install without keeping
a local clone.

```bash
bash install.sh --target=codex --tarball=<release-url>
```

Or set the env variable and run without a flag:

```bash
Z_HARNESS_RELEASE_URL=<release-url> bash install.sh --target=codex
```

Use `--target=claude` or omit `--target` for Claude Code. Use `--target=all`
to install the tarball for both hosts.

`install.sh` downloads the tarball, extracts it under the selected host's
plugin location, and prints the installed version.

To update a tarball install later, use `/z-update` from inside Claude Code.

---

## Overwriting an existing install

If `~/.claude/plugins/z-harness@zeke-tools` already exists as a regular
directory (not a symlink), `install.sh` will refuse to proceed:

```
install.sh: ERROR: ~/.claude/plugins/z-harness@zeke-tools exists and is not a symlink.
  Use --force to overwrite it.
```

Pass `--force` to remove it and reinstall:

```bash
bash install.sh --force
bash install.sh --tarball=<url> --force
```

---

## Per-repo auto-enable

To have z-harness load automatically in a specific project, commit
`.claude/settings.json` at the repo root:

```json
{
  "extraKnownMarketplaces": {
    "zeke-tools": { "source": { "source": "github", "repo": "<org>/z-harness" } }
  },
  "enabledPlugins": { "z-harness@zeke-tools": true }
}
```

---

## /z-update — refreshing the install

`/z-update` in Claude Code, or the `z-update` skill in Codex, keeps z-harness
current. It detects install mode and takes the appropriate update path.

**Symlink mode:** runs `git -C <plugin-path> pull --ff-only`. If the repo has
uncommitted changes, it aborts and prints `git status`; resolve the changes,
then re-run `/z-update` or `z-update`. In Codex, it then reruns
`codex plugin add z-harness@personal` so the cache is refreshed.

**Tarball mode:** HEAD-checks the release URL, compares version strings, and
performs an atomic swap if a newer version is found. Rolls back automatically
on any swap failure.

After a successful update, both modes emit a `harness_updated` event to
`z-harness/metrics.jsonl` with `old_version` and `new_version`.

```
[z-update] Updated successfully.
  old: abc1234
  new: def5678
```

### Environment variable

| Variable | Default | Purpose |
|---|---|---|
| `Z_HARNESS_RELEASE_URL` | placeholder | Override the tarball release URL for `/z-update` in tarball mode |

---

## Distribution model

z-harness has **no autoupdate mechanism**. Updates are explicit — either a
`git pull` in your clone, or `/z-update` inside Claude Code. This is
intentional: autoupdate in a tool that rewrites production code would be a
footgun.

---

## Uninstall

```bash
rm ~/.claude/plugins/z-harness@zeke-tools
codex plugin remove z-harness@personal
rm ~/plugins/z-harness
```

If you installed via tarball, this removes the extracted directory. If you
installed via symlink, this removes only the symlink — the local clone is
untouched.

---

## Requirements

- At least one CLI-addressable LLM (e.g. `codex`, `gemini`, `claude`, `ollama`,
  `agy`) installed and reachable on your `PATH`. Run `/z-providers-discover` to
  auto-configure roles after install. See [PROVIDERS.md](PROVIDERS.md).
- Claude Code with `PushNotification` available (for mobile notifications).
