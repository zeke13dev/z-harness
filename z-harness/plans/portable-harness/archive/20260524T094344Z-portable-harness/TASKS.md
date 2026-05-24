# TASKS.md — portable-harness

Status legend: `[ ]` pending · `[x]` done · `[!]` blocked.

---

## T001 — Plan-path helper + `Z_HARNESS_PLANS_DIR` env wiring
- **Files:** `scripts/plan-path.sh` (new); `scripts/log-event.sh`, `scripts/log-phase.sh` (edit).
- **Deps:** —
- **Acceptance:**
  - `plan-path.sh` exports `plan_dir <slug>` and `legacy_plan_dir <slug>`; honors `Z_HARNESS_PLANS_DIR` (default `z-harness/plans`).
  - `log-event.sh` and `log-phase.sh` source `plan-path.sh` and route writes accordingly.
  - Smoke test: `plan_dir foo` echoes `z-harness/plans/foo`; with `Z_HARNESS_PLANS_DIR=/tmp/p` echoes `/tmp/p/foo`.
- **DOCS:** plan-layout-migration
- **Status:** `[ ]`

## T002 — Migration script `scripts/migrate-plan-layout.sh`
- **Files:** `scripts/migrate-plan-layout.sh` (new).
- **Deps:** T001.
- **Acceptance:**
  - Single-slug mode: `migrate-plan-layout.sh <slug>` moves `z-harness/<slug>` → `z-harness/plans/<slug>` iff destination missing. Errors on conflict (prints diff).
  - `--all` flag: enumerates legacy slugs (any `z-harness/*/` with PLAN.md/SPEC.md/TASKS.md), excluding `z-harness/archive/`, `z-harness/plans/`, `z-harness/improvements/`, and `z-harness/metrics.jsonl`.
  - `--dry-run` flag: prints plan without `mv`.
  - Idempotent.
  - Emits a `migration_done` event per slug.
- **DOCS:** plan-layout-migration
- **Complexity:** medium
- **Status:** `[ ]`

## T003 — Sweep all commands + agents + scripts to new path helper
- **Files:** every file matched by `grep -rl 'z-harness/\$Z_HARNESS_SLUG\|z-harness/<slug>' commands/ agents/ scripts/ skills/ docs/` plus `z-harness/portable-harness/SPEC.md` (this file's own self-references).
- **Deps:** T001.
- **Acceptance:**
  - All grep hits updated to use `plan-path.sh` helper (sourced or inlined via `Z_HARNESS_PLAN_DIR=$(plan_dir "$Z_HARNESS_SLUG")`).
  - Commands try new path first; on missing PLAN.md/SPEC.md at new path, check legacy path and warn ONCE per run (env-guard `Z_HARNESS_LEGACY_WARNED=1`).
  - Warning message includes the exact migration command.
  - `docs/llm/commands.json` invariant updated.
- **DOCS:** plan-layout-migration, commands
- **Complexity:** medium
- **Status:** `[ ]`

## T004 — Agy plugin format research + design note
- **Files:** `z-harness/portable-harness/archive/<run>/agy-research.md` (new).
- **Deps:** —
- **Acceptance:**
  - Run `agy --help` and any sub-help. WebFetch agy docs.
  - Document: manifest filename + schema; whether agy supports native subagent dispatch; prompt-format expectations; install/load procedure.
  - Conclude with: target `agy-plugin.yaml` shape for this repo; mapping table from our (command, agent) → agy concept; list of unsupported constructs (→ CAPABILITIES.md feeder).
  - **REMOTE_VERIFY:** none (research-only).
- **Complexity:** medium
- **Status:** `[ ]`

## T005 — Provider registry schema + resolver
- **Files:** `scripts/resolve-provider.py` (new), `scripts/resolve-provider.sh` (thin wrapper), `docs/human/PROVIDERS.md` (new).
- **Deps:** —
- **Acceptance:**
  - Resolver reads `~/.config/z-harness/providers.json` and `<repo>/.z-harness/providers.json` (the latter via env `Z_HARNESS_REPO_PROVIDERS` for testability).
  - Merge precedence: per top-level key in `providers` map, per role key in `roles` map. Repo wins. Shadowing logged to stderr + emitted as `provider_shadowed` event.
  - CLI: `resolve-provider.sh <role>` prints JSON `{role, provider, command, args_template, stdin, timeout_s, model_label}`.
  - Invariants: schema `version` must equal 1; `consultant_primary` ≠ `consultant_secondary` (resolver errors if same); reviewer free.
  - Missing role: exit nonzero with `[providers] role=<role> unbound — run /z-providers-discover`.
  - Missing CLI on PATH: exit nonzero with `[providers] role=<role>, provider=<p>, command=<c> not on PATH`.
  - Run-start observability: a separate `scripts/log-providers.sh` invoked from each consultant/reviewer dispatch site prints the one-line summary + jsonl event.
- **DOCS:** providers-registry
- **Complexity:** high
- **Status:** `[ ]`

## T006 — Discovery script + `/z-providers-discover`
- **Files:** `scripts/discover-providers.py` (new), `commands/z-providers-discover.md` (new).
- **Deps:** T005.
- **Acceptance:**
  - Discovery probes hardcoded list (`codex`, `gemini`, `claude`, `ollama`, `agy`, `gpt`) via `shutil.which`.
  - Per detected CLI, emits stanza with known-shape `args_template`.
  - Outputs proposed JSON to stdout; never writes.
  - Slash command: shows proposal, asks user per CLI which roles to bind (multiSelect over the 3 role names), confirms write target (user-global by default, repo-local with `--repo`), then atomically writes.
  - Enforces `consultant_primary ≠ consultant_secondary` at write time; reprompts on collision.
  - Emits `providers_discovered` event with detected list, write target, role bindings.
- **DOCS:** providers-registry
- **Complexity:** medium
- **Status:** `[ ]`

## T007 — Author canonical consultant + reviewer agents; delete legacy
- **Files:** `agents/consultant-primary.md` (new), `agents/consultant-secondary.md` (new), `agents/reviewer.md` (new). Delete: `agents/gemini-consultant.md`, `agents/codex-consultant.md`, `agents/codex-reviewer.md`.
- **Deps:** T005, T004.
- **Acceptance:**
  - Each new file: model haiku; tools `Bash, Read, Grep, Glob`; body resolves provider via `resolve-provider.sh <role>`; constructs and runs the CLI with stdin = prompt; saves transcripts to current-run `transcripts/`.
  - All three files share identical structure differing only in role name (use a templated comment block at top of each).
  - Legacy three files deleted in the same commit (no compat shim).
- **DOCS:** providers-registry
- **Complexity:** medium
- **Status:** `[ ]`

## T008 — Sweep all dispatch sites to new agent names
- **Files:** every command matched by `grep -rl 'gemini-consultant\|codex-consultant\|codex-reviewer' commands/ agents/ skills/`.
- **Deps:** T007.
- **Acceptance:**
  - `Agent(subagent_type="gemini-consultant", ...)` → `consultant-primary` (preserve order: the file referencing gemini becomes primary, codex becomes secondary; if a single dispatch site is ambiguous, pick deterministically and document).
  - `codex-consultant` → `consultant-secondary` accordingly.
  - `codex-reviewer` → `reviewer`.
  - Verification: no remaining hits of the three legacy names in repo (excluding `archive/` and historical event logs).
  - Sweep also scans `z-harness/plans/**/TASKS.md` and `z-harness/**/TASKS.md` for legacy names and prints (does not edit) a one-shot nudge if any in-flight plan references them.
- **DOCS:** commands
- **Complexity:** medium
- **Status:** `[ ]`

## T009 — Export common helpers + audit/lint
- **Files:** `scripts/export-common.py` (new), `scripts/audit-tarball.sh` (new).
- **Deps:** —
- **Acceptance:**
  - `export-common.py` exposes: source-file enumeration (commands/agents/skills); CAPABILITIES.md schema validation; helper to compute per-target output path.
  - `audit-tarball.sh` accepts a tarball path; fails if it contains `providers.json`, `.z-harness/`, `z-harness/plans/`, `z-harness/archive/`, `z-harness/improvements/`, `exports/`, or any path under `~/`.
- **Complexity:** medium
- **Status:** `[ ]`

## T010 — Cursor export
- **Files:** `scripts/export-cursor.py` (new), `exports/cursor/CAPABILITIES.md` (new), `exports/cursor/README.md` (new), generated `exports/cursor/.cursor/rules/*.mdc` (build-time).
- **Deps:** T009.
- **Acceptance:**
  - One `.mdc` per command + agent + skill.
  - MDC frontmatter populated from source-file frontmatter; body is the source markdown lightly rewritten (no Agent() / Skill() / Anthropic-tool refs — those are listed in CAPABILITIES.md instead).
  - Automated check: every emitted `.mdc` parses (basic MDC syntax).
  - Generated tree excluded from git via `exports/cursor/.cursor/rules/.gitignore`? — actually commit the generated tree so users can `git clone` and use.
- **DOCS:** multi-ide-exports
- **Complexity:** high
- **Status:** `[ ]`

## T011 — Codex CLI export
- **Files:** `scripts/export-codex.py` (new), `exports/codex/CAPABILITIES.md` (new), `exports/codex/AGENTS.md` (new), `exports/codex/README.md` (new), generated `exports/codex/prompts/*.md`.
- **Deps:** T009.
- **Acceptance:**
  - Format-research note inline at top of the export script (citing Codex CLI prompt mechanism).
  - One prompt file per command; one section in `AGENTS.md` per agent.
  - CAPABILITIES.md lists Anthropic-specific Tool() calls left out.
- **DOCS:** multi-ide-exports
- **Complexity:** high
- **Status:** `[ ]`

## T012 — Agy export (first-class)
- **Files:** `scripts/export-agy.py` (new), `exports/agy/CAPABILITIES.md` (new), `exports/agy/agy-plugin.yaml` (generated), `exports/agy/prompts/*.md` (generated), `exports/agy/README.md` (new).
- **Deps:** T004 (research), T009.
- **Acceptance:**
  - `agy-plugin.yaml` schema matches the shape spec'd in T004's research note.
  - Per-command prompt files map to whatever agy's prompt-loading convention is.
  - CAPABILITIES.md documents anything the agy schema can't express.
- **DOCS:** multi-ide-exports
- **Complexity:** high
- **Status:** `[ ]`

## T013 — `/z-export` slash command
- **Files:** `commands/z-export.md` (new).
- **Deps:** T010, T011, T012.
- **Acceptance:**
  - Args: `--target=<cursor|codex|agy|all>` (default `all`).
  - Invokes the per-target script(s); on success prints relative output paths.
  - On any target failure: continues other targets, exits nonzero, prints failed-target summary.
- **DOCS:** multi-ide-exports
- **Complexity:** low
- **Status:** `[ ]`

## T014 — Distribution: `install.sh` + `bundle-plugin.sh` + `/z-update`
- **Files:** `install.sh` (new, repo root), `scripts/bundle-plugin.sh` (new), `commands/z-update.md` (new), `scripts/version.sh` (edit).
- **Deps:** T009 (audit-tarball.sh used by bundle-plugin.sh).
- **Acceptance:**
  - `install.sh`: detects repo clone vs single-file fetch; symlinks `~/.claude/plugins/z-harness@zeke-tools` → repo, or downloads tarball.
  - `bundle-plugin.sh`: produces `dist/z-harness-<version>.tar.gz`; calls `audit-tarball.sh` on output; fails build on audit violation.
  - `version.sh`: emits git short SHA + nearest tag.
  - `/z-update`: detects install mode; symlink → `git -C <plugin> pull --ff-only` with pre-flight `git status` clean check (aborts on dirty tree); tarball → HEAD-check release URL, swap atomically. Emits `harness_updated` event.
- **DOCS:** z-update
- **Complexity:** high
- **Status:** `[ ]`

## T015 — Docs sweep + INDEX.json updates + README rewrite
- **Files:** `docs/human/PROVIDERS.md`, `docs/human/INSTALL.md`, `docs/human/MULTI-IDE.md`, `docs/human/PLAN-LAYOUT.md` (new); `docs/llm/INDEX.json` (edit — add `providers-registry`, `multi-ide-exports`, `plan-layout-migration`, `z-update` concepts; each entry has stubbed `<slug>.json` written here too); `README.md` (edit — install rewrite, command list, providers section).
- **Deps:** T002, T005, T006, T010, T011, T012, T013, T014.
- **Acceptance:**
  - All four new human-tier docs created.
  - All four new INDEX.json entries created with corresponding `docs/llm/<slug>.json` stubs.
  - README install section + commands table updated.
- **Complexity:** medium
- **Status:** `[ ]`

---

## Task count: 15 (within 10–20 target).

## Complexity rollup (preliminary; classifier may revise)
- low: T013 (1)
- medium: T001, T002, T003, T004, T006, T007, T008, T009, T015 (9)
- high: T005, T010, T011, T012, T014 (5)

## Critical ordering
- T001 unblocks T002, T003 (foundation).
- T004 unblocks T012 (agy research → agy adapter).
- T005 unblocks T006, T007 (registry → discovery + agents).
- T007 unblocks T008 (new agents → dispatch sweep).
- T009 unblocks T010, T011, T012, T014.
- T013 needs all three export targets.
- T015 last (docs reference everything else).

## Parallelizable batches
- Batch A (after T001): T002 + T003 in parallel.
- Batch B: T004 + T005 + T009 in parallel.
- Batch C (after T005): T006 + T007.
- Batch D (after T007): T008.
- Batch E (after T009 + T004): T010 + T011 + T012 in parallel.
- Batch F: T013, T014.
- Batch G: T015.
