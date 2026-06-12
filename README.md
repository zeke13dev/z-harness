# z-harness → Antigravity (agy) Export

This directory contains z-harness commands, agents, and skills exported as Antigravity
(Google's agy IDE) workflow, rule, and skill files.

## What's included

| Path | Purpose |
|------|---------|
| `.agent/workflows/*.md` | Custom chat modes — one per z-harness command |
| `.agent/rules/*.md` | Always-on or model-decision rules — one per z-harness agent |
| `.agent/skills/*` | Workspace skills — one per z-harness skill |
| `prompts/*.md` | Flat prompt files (description + role frontmatter) |
| `agy-plugin.yaml` | Export manifest (z-harness convention; not read by agy) |
| `CAPABILITIES.md` | What can and cannot be expressed in Antigravity |

## Install

### Per-project (recommended)

Copy the `.agent/` directory into your project workspace root:

```bash
cp -r exports/agy/.agent /path/to/your/project/
```

Antigravity auto-discovers `.agent/workflows/**/*.md`, `.agent/rules/**/*.md`, and `.agent/skills/**/*`
by watching the workspace directory tree.  No restart required — files become
available immediately in the IDE.

### Global (all workspaces)

To make workflows available across all projects, copy them to the global workflows path:

```bash
mkdir -p ~/.antigravity/antigravity/data/User/globalStorage/antigravity.antigravity/global_workflows/
cp exports/agy/.agent/workflows/*.md \
  ~/.antigravity/antigravity/data/User/globalStorage/antigravity.antigravity/global_workflows/
```

## Usage

After installing, invoke a workflow from the command line:

```bash
agy chat --mode z-plan "Add user authentication feature"
agy chat --mode z-implement-next
agy chat --mode z-review-all
```

Or select the mode from the Antigravity IDE mode picker in the chat panel.

## Re-generating

Run the exporter from the repo root:

```bash
python3 -m z_harness_cli export --host antigravity
# or with a custom output directory:
python3 -m z_harness_cli export --host antigravity --out /path/to/output
```

## Known limitations

See `CAPABILITIES.md` for a full list of z-harness features that cannot be
expressed in Antigravity (subagent dispatch, skills, multi-model review, etc.).
