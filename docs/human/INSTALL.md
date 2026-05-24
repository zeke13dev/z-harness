# INSTALL — z-harness Installation Guide

> Last updated: 2026-05-24

## Overview

z-harness is a Claude Code plugin distributed in two modes: **symlink** (for
active development) and **tarball** (for stable deploys). Both modes install
to the same location so Claude Code picks them up identically.

---

## Plugin install location

Both modes install to:

```
~/.claude/plugins/z-harness@zeke-tools
```

In symlink mode this is a symlink to your local clone.
In tarball mode this is an extracted directory.

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

`install.sh` detects the presence of `.git + commands/ + agents/` and
creates:

```
~/.claude/plugins/z-harness@zeke-tools -> <absolute path to clone>
```

Any edit you make in the repo takes effect immediately in Claude Code — no
re-install needed.

---

## Tarball mode (from a release URL)

Tarball mode is for users who want a stable, versioned install without keeping
a local clone.

```bash
bash install.sh --tarball=<release-url>
```

Or set the env variable and run without a flag:

```bash
Z_HARNESS_RELEASE_URL=<release-url> bash install.sh
```

`install.sh` downloads the tarball, extracts it under
`~/.claude/plugins/z-harness@zeke-tools/`, and prints the installed version.

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

`/z-update` is the in-Claude-Code command for keeping z-harness current. It
detects install mode and takes the appropriate update path.

**Symlink mode:** runs `git -C <plugin-path> pull --ff-only`. If the repo has
uncommitted changes, it aborts and prints `git status`; resolve the changes,
then re-run `/z-update`.

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
```

If you installed via tarball, this removes the extracted directory. If you
installed via symlink, this removes only the symlink — the local clone is
untouched.
