# z-harness for Cursor

This directory contains z-harness commands, agents, and skills exported as
[Cursor rules](https://docs.cursor.com/context/rules-for-ai) (`.mdc` files).

## What is this?

z-harness is a structured planning and implementation pipeline for Claude Code.
This export makes the same procedural knowledge available inside Cursor so you
can use z-harness workflows with Cursor's AI assistant.

See `CAPABILITIES.md` for a complete list of what is and is not supported in
the Cursor export.

## Installation

### Option A — Copy into your project

Copy (or symlink) the `.cursor/rules/` directory into your Cursor project root:

```sh
cp -r exports/cursor/.cursor /path/to/your/project/
```

Or with a symlink (so updates to the export are reflected automatically):

```sh
ln -s /path/to/z-harness/exports/cursor/.cursor /path/to/your/project/.cursor
```

### Option B — Global Cursor rules

If you want z-harness rules available in all your Cursor projects, copy them
into your global Cursor rules directory (varies by OS; check Cursor settings
under `Cursor > Rules for AI`).

## Keeping exports up to date

The `.mdc` files in this directory are generated from the source files in
`commands/`, `agents/`, and `skills/`. After pulling updates to z-harness,
regenerate the exports from the repository root:

```sh
python3 scripts/export-cursor.py
```

## Filing bugs

For issues with the Cursor export specifically, file an issue in the z-harness
repository and tag it `cursor-export`.

For issues with z-harness itself, see the main `README.md` at the repository
root.
