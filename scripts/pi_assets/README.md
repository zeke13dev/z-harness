# z-harness → pi export

Brings z-harness to [pi](https://pi.dev): every agent as an executable fan-out subagent, every command/skill as a prompt, and the global rule that wires `doc-fetcher` (cheap grounding) and `explore` (parallel recon) together. Unlike the Cursor/Codex/agy exports, pi has no native subagent primitive — fan-out runs through pi's **subagent extension**, which this export vendors.

This tree is **generated** by `/z-export --target=pi`, which calls the runtime-owned `runtime.drivers.pi.export.export` entry point. Do not edit generated pi export output by hand; regenerate it into scratch output such as `temp/exports/pi/`.

For first-class OMP support, use `/z-export --target=omp`; the legacy pi export remains separate and does not route native OMP through pi rewrites or `scripts/omp-consult.sh` (the consult-provider fallback shim, not the native OMP export path).

## What's here

```
temp/exports/pi/
├── AGENTS.md             # generated: fan-out preamble + auto agent index
├── CAPABILITIES.md       # what maps cleanly to pi and what's lossy
├── README.md             # this file
├── agents/
│   ├── <id>.md           # generated: every z-harness agent, frontmatter normalized
│   └── explore.md        # pi-only fan-out recon agent (no z-harness source)
├── prompts/
│   └── <id>.md           # generated: skills rendered as prompts, Agent()/Skill() → subagent hints
└── extensions/subagent/  # vendored pi subagent extension (the fan-out primitive)
```

### Source of truth

| Output | Comes from |
|--------|-----------|
| `agents/<id>.md`, `prompts/<id>.md`, `AGENTS.md` index | z-harness `agents/` and `skills/*/SKILL.md` (generated) |
| `agents/explore.md`, `extensions/subagent/`, AGENTS preamble, `CAPABILITIES.md`, this README | `scripts/pi_assets/` (copied verbatim) |

## How pi consumes each piece

| Piece | pi mechanism | Discovery path |
|-------|--------------|----------------|
| `subagent` extension | auto-discovered extension | `~/.pi/agent/extensions/*/index.ts` |
| `agents/*.md` | read by the subagent extension | `~/.pi/agent/agents/*.md` — **not** a pi package resource type |
| `prompts/*.md` | prompt templates | `prompts` setting / `~/.pi/agent/prompts/` |
| `AGENTS.md` | global agent instructions | `~/.pi/agent/AGENTS.md` |

> pi packages auto-surface `extensions/`, `skills/`, `prompts/`, `themes/` — but **not** `agents/`. So even though z-harness is installed as a pi package, its agents must be linked into the agent-discovery dir separately (below).

## Install (symlink live)

Source of truth stays in this repo; symlinks make it live under `~/.pi/agent/`:

```bash
PI=~/.pi/agent
ZX="$(cd "$(dirname "$0")" && pwd)"   # absolute path to the generated pi export root

# subagent extension (the fan-out primitive)
mkdir -p "$PI/extensions/subagent"
ln -sf "$ZX/extensions/subagent/index.ts"  "$PI/extensions/subagent/index.ts"
ln -sf "$ZX/extensions/subagent/agents.ts" "$PI/extensions/subagent/agents.ts"

# agents — link each .md so the subagent extension discovers them
mkdir -p "$PI/agents"
for f in "$ZX"/agents/*.md; do ln -sf "$f" "$PI/agents/$(basename "$f")"; done

# global rule
ln -sf "$ZX/AGENTS.md" "$PI/AGENTS.md"
```

Then start pi and run `/reload`. To wire the prompts, add the generated `<pi-export-root>/prompts` path to the `prompts` array in `~/.pi/agent/settings.json` (the subagent-aware versions supersede the codex prompts).

## Usage

```
# grounding first
subagent { "agent": "doc-fetcher",
           "task": "query: how does the strategy router pick a model?\nrepo_root: /abs/repo\ndepth: standard" }

# parallel recon for the gaps
subagent { "tasks": [
  { "agent": "explore", "task": "Find where the router is defined in /abs/repo" },
  { "agent": "explore", "task": "Find all callers of select_model in /abs/repo" }
] }
```

Or just describe the intent — `AGENTS.md` tells the orchestrator to reach for these automatically.

## Regenerating

```bash
/z-export --target=pi
```

Edit z-harness sources (`agents/`, `skills/`) or the pi-only assets (`scripts/pi_assets/`), then re-run `/z-export --target=pi`. After regenerating, `pi /reload` picks up extension changes; symlinks stay valid since paths are stable.

See `CAPABILITIES.md` for the full mapping and its lossy edges (no Haiku tier, line-based call rewrites, etc.).
