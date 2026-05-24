# SPEC.md — portable-harness

## Overview
Restructure z-harness so plan output is namespaced under `z-harness/plans/<slug>/` (cleans up the plugin repo's own dogfooded state), generalize LLM-provider routing through a config-file registry (so any CLI-addressable model can play the consultant/reviewer roles), export commands+agents+skills to Cursor / Codex CLI / Antigravity (agy), and introduce a symlink + `install.sh` distribution path with an explicit `/z-update` refresh command.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/portable-harness/BRAINSTORM.md | n/a |
| RESEARCH.md | z-harness/portable-harness/RESEARCH.md | n/a |

Neither artifact present — fresh /z-plan run. Grounding came from `doc-fetcher` (Haiku) reading `docs/llm/INDEX.json` + concept JSONs.

---

## File-level spec

### Path layout — every command + script

**New canonical path:** `${Z_HARNESS_PLANS_DIR:-z-harness/plans}/<slug>/`. Inside: `SPEC.md`, `PLAN.md`, `TASKS.md`, `BRAINSTORM.md`, `RESEARCH.md`, `archive/<run-id>/`, `improvements/`, etc. *Must support environment variable override for `Z_HARNESS_PLANS_DIR`.*

**Legacy path (read-only fallback):** `z-harness/<slug>/`. Commands try the new path first; if missing, look at legacy; if found, emit a one-line warning suggesting `scripts/migrate-plan-layout.sh <slug>`.

**Files updated** (all use the same pattern — replace literal `z-harness/$Z_HARNESS_SLUG` with the new helper):
- `commands/z-plan.md` — Setup steps 1, 4, 5; phase checkpoints; final archive copy.
- `commands/z-plan-light.md`, `z-plan-split.md`, `z-amend.md`, `z-implement-all.md`, `z-implement-next.md`, `z-debug.md`, `z-fix.md`, `z-improve.md`, `z-research.md`, `z-brainstorm.md`, `z-audit.md`, `z-test.md`, `z-maintain-docs.md`, `z-mr-review.md`, `z-style-init.md`, `z-stats.md`, `z-review-all.md`, `z-do.md`, `z-skill-fix.md`, `z-init-docs.md` — wherever they construct plan-relative paths.
- `scripts/log-event.sh`, `scripts/log-phase.sh` — `Z_HARNESS_SLUG`-based path construction; respect `Z_HARNESS_PLANS_DIR` override.
- `agents/implementer.md`, `agents/spec-precheck.md`, `agents/codex-reviewer.md` (will be renamed; see below), `agents/cluster-planner.md`, `agents/doc-updater.md` — any reference to `z-harness/<slug>/...` paths.

**Helper:** `scripts/plan-path.sh` (new) — exports two functions:
```
plan_dir <slug>   # echoes ${Z_HARNESS_PLANS_DIR:-z-harness/plans}/<slug>
legacy_plan_dir <slug>  # echoes z-harness/<slug>
```
Used by all the above. Commands also expose `Z_HARNESS_PLAN_DIR` env to subagents.

**Invariant doc update:** `docs/llm/commands.json` — invariant at line 197 (re-numbered after edit) and human-tier counterparts.

### scripts/migrate-plan-layout.sh (new)
- Single arg: slug (or `--all` to migrate every dir in `z-harness/` that contains a `PLAN.md`, `SPEC.md`, or `TASKS.md` at its root).
- For each slug: `mv z-harness/<slug> z-harness/plans/<slug>`; idempotent (no-op if already at new path); refuses to clobber existing new-path dirs (errors with diff).
- Updates nothing inside the moved files (paths inside are runtime-resolved via Z_HARNESS_PLANS_DIR).
- Logs a `migration_done` event per slug.

### Provider registry — config files + resolution

**Files:**
- `~/.config/z-harness/providers.json` — user-global default.
- `<repo>/.z-harness/providers.json` — repo-local override (commit-friendly; primarily for `roles`, not provider definitions).

**Schema (versioned):**
```json
{
  "version": 1,
  "providers": {
    "<name>": {
      "kind": "cli",
      "command": "codex",
      "args_template": ["exec", "-"],
      "stdin": true,
      "timeout_s": 300,
      "model_label": "gpt-5-codex"
    }
  },
  "roles": {
    "consultant_primary": "<provider-name>",
    "consultant_secondary": "<provider-name>",
    "reviewer": "<provider-name>"
  }
}
```

**Precedence:** repo-local overrides user-global *per key* (provider name OR role name), not whole-file merge. Shadowing emits a `provider_shadowed` event (warn) at run-start.

**Resolution (one-liner, used by every consultant/reviewer):**
```
scripts/resolve-provider.sh <role>
# prints JSON: {"provider":"codex","command":"codex","args_template":["exec","-"],"stdin":true,"model_label":"gpt-5-codex"}
```

**Run-start observability:** every command that may dispatch a consultant/reviewer logs a `provider_resolved` event per role with `{role, provider, command, model_label}` and prints a one-line stdout summary `[providers] consultant_primary=codex(gpt-5-codex)  consultant_secondary=gemini(gemini-2.5-pro)  reviewer=codex(gpt-5-codex)`.

### Consultant + reviewer agents — generalized, shims removed

**Removed (delete in this plan):** `agents/gemini-consultant.md`, `agents/codex-consultant.md`, `agents/codex-reviewer.md`.

**New canonical files:**
- `agents/consultant-primary.md`
- `agents/consultant-secondary.md`
- `agents/reviewer.md`

Each:
- Model frontmatter: `model: haiku` (same as today).
- Tools: `Bash, Read, Grep, Glob`.
- Body: identical structure, parametrized only on the role name. They call `scripts/resolve-provider.sh <role>`, parse JSON, then invoke `command + args_template` with stdin = prompt. Transcripts saved to current run's `transcripts/` dir under name `NNN-<role>-<provider>-<topic>.{prompt,response}.md`.

**Every dispatch site updated.** Commands previously written `Agent(subagent_type="codex-consultant", ...)` now write `Agent(subagent_type="consultant-primary", ...)` and the parallel pair becomes `consultant-primary` + `consultant-secondary`. Same for `codex-reviewer` → `reviewer`. Affected commands: `z-plan`, `z-plan-light`, `z-plan-split`, `z-audit`, `z-debug`, `z-fix`, `z-mr-review`, `z-test`, `z-implement-all`, `z-implement-next`, `z-review-all`, `z-amend`, `z-brainstorm`, `z-do`, `z-skill-fix`, `z-improve`.

### `/z-providers-discover` (new slash command)

- File: `commands/z-providers-discover.md`.
- Behavior: invokes `scripts/discover-providers.py` to probe PATH for known LLM CLIs (`codex`, `gemini`, `claude`, `ollama`, `agy`, `gpt`), emits a proposed `providers.json`, shows it via the command body, prompts user for confirm before write.
- Default write target: user-global (`~/.config/z-harness/providers.json`). `--repo` flag writes to `<repo>/.z-harness/providers.json` instead.
- For each detected CLI, asks the user via AskUserQuestion which roles to bind (e.g., "bind `codex` to consultant_primary, consultant_secondary, or reviewer?").
- Logs a `providers_discovered` event with `{detected, written_to, roles_set}`.

### scripts/discover-providers.py (new)

- Probes a hardcoded list via `subprocess`. For each found CLI: emits a stanza with default `args_template` for known shapes (codex uses `exec -`, gemini uses `-p ... --approval-mode plan --output-format text`, claude uses `--print`, ollama uses `run <model-stdin>`).
- Unknown CLIs in PATH: not auto-detected. Documented manual-add pattern in `docs/human/PROVIDERS.md`.
- Output: prints proposed JSON to stdout. Never writes a file directly — the slash command does that after confirmation.

### Multi-IDE export — pipeline + per-target adapter

**Source-of-truth (unchanged):** Claude Code shape — `commands/*.md`, `agents/*.md`, `skills/*/SKILL.md`, `scripts/*`, `docs/`.

**New: `exports/` tree.**
```
exports/
├── cursor/
│   ├── CAPABILITIES.md
│   ├── .cursor/rules/<one-per-command-or-agent>.mdc
│   └── README.md
├── codex/
│   ├── CAPABILITIES.md
│   ├── AGENTS.md
│   ├── prompts/<one-per-command>.md
│   └── README.md
└── agy/
    ├── CAPABILITIES.md
    ├── agy-plugin.yaml
    ├── prompts/<one-per-command>.md
    └── README.md
```

**Build script:** `scripts/export-all.sh` (and per-target `scripts/export-cursor.py`, `export-codex.py`, `export-agy.py`). Each:
- Reads source files; emits target artifacts.
- Per-target adapter handles format translation; constructs that don't translate produce `CAPABILITIES.md` entries.
- Share `scripts/export_common.py` (Python) for path enumeration, schema validation, and filter logic.
- **Smoke-test gate:** At least one command + one agent per target verified to load and *execute* (not just valid syntax) in target IDE before plan completion.
- **Automated export filter audit:** Lint script rejecting any export tarball that includes `providers.json`, `.z-harness/`, `z-harness/plans/`, or anything under `~/`.

**Slash command:** `commands/z-export.md` — wraps `scripts/export-all.sh`. Args: `--target=<cursor|codex|agy|all>` (default `all`).

**Agy first-class adapter (per user direction):**
- Pre-impl research task to read `agy --help` and any agy docs accessible via WebFetch.
- `agy-plugin.yaml` schema implemented to spec. If agy supports native subagent dispatch, map our agents to it; if not, lower to shell-wrappers and document in CAPABILITIES.md.

### Distribution + `/z-update`

**Symlink path:** `install.sh` script auto-detects local clone; if present, symlinks to plugin dir (`~/.claude/plugins/z-harness@zeke-tools` → `<repo-path>`). Edits in the repo go live without re-install.

**Tarball path:** `scripts/bundle-plugin.sh` emits `z-harness-<version>.tar.gz` containing only the plugin payload (excludes `z-harness/plans/`, `z-harness/archive/`, `z-harness/improvements/`, transcripts, providers.json).
- **Versioning:** Keyed by git short SHA generated by `scripts/version.sh` at build time.
- **README install one-liner:** `curl -fsSL <url>/install.sh | sh`.

**/z-update slash command:**
- File: `commands/z-update.md`.
- Behavior: detects install mode (symlink vs tarball); for symlink: `git -C <plugin-path> pull --ff-only`; for tarball: HEAD-check release URL, download new tarball, atomically swap.
- Logs a `harness_updated` event with old/new version stamps.
- Determines version via `scripts/version.sh`.

### Docs updates

- `docs/llm/INDEX.json` — add new concepts: `providers-registry`, `multi-ide-exports`, `plan-layout-migration`, `z-update`. Run `/z-maintain-docs` (out of scope for this plan; only the INDEX entries are spec'd here).
- `docs/human/PROVIDERS.md` — user-facing guide: how to register a new CLI, how to bind roles, how `/z-providers-discover` works, how shadowing precedence works.
- `docs/human/INSTALL.md` — symlink vs tarball, `/z-update`.
- `docs/human/MULTI-IDE.md` — per-target install steps, CAPABILITIES caveats.
- `README.md` — install section rewritten; new commands listed.
- **Dual-Read Fallback & Warn Summary:** Explicit summary detailing which exact commands will emit the fallback warning and under what conditions.

---

## DRY / KISS / SOLID checks

- **DRY:** path construction goes through `scripts/plan-path.sh` (one definition; every command sources it). Provider resolution goes through `scripts/resolve-provider.sh` (one definition; every consultant/reviewer calls it). Export adapters share `scripts/export_common.py` (Python) for source-file enumeration and CAPABILITIES.md schema.
- **KISS:** registry kind = `cli` only (no API kind). Roles fixed to three names (`consultant_primary`, `consultant_secondary`, `reviewer`). No autoupdate. No parameterized middleman agent. Python scripts for discovery, not LLM agents.
- **SOLID:**
  - SRP: each export adapter owns one target; each script in `scripts/llm-cli/` is a CLI adapter for exactly one provider; consultant/reviewer agents do only role-routing.
  - OCP: adding a new IDE target = new `scripts/export-<name>.py` + new `exports/<name>/` tree; no edits to source files. Adding a new provider = entry in providers.json; no code changes.
  - DIP: commands/agents depend on the abstraction (`scripts/resolve-provider.sh`), not on concrete CLI names.

---

## Edge cases / invariants

- A command run with **no providers.json** at all: `/z-providers-discover` runs implicitly if interactive, else exits with actionable error pointing to docs/human/PROVIDERS.md.
- A role with **no provider bound**: command halts at the dispatch site with `[providers] role=reviewer unbound — run /z-providers-discover` and exits non-zero.
- A CLI in registry that **isn't on PATH**: command halts with `[providers] reviewer=codex but \`codex\` not on PATH`.
- `Z_HARNESS_PLANS_DIR` set to an absolute path: respected verbatim (no normalization).
- `/z-update` with **uncommitted local changes** in symlink mode: aborts with `git status` printed; user resolves.
- Export adapters MUST NOT include any file matching `providers.json`, `.z-harness/`, `z-harness/plans/`, `z-harness/archive/`, or anything under `~/`.
- `consultant-primary` and `consultant-secondary` MUST resolve to **distinct** providers (the cross-model critique invariant); resolver errors if they collide. Must enforce this as a pre-flight check during provider resolution.

---

## Non-goals
- Lossless multi-IDE compile.
- Background/autoupdate.
- Per-task per-provider override (roles are global to a run).
- Building `anthropic-api-as-cli` adapter in this plan (provider registry is CLI-only; if a user wants Anthropic API access, they ship their own wrapper — documented but not bundled).
- Lossy legacy-removal (it's now a goal for agent files, but command read fallback stays for one release).
