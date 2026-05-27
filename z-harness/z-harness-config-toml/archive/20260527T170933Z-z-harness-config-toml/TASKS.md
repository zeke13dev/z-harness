# TASKS — z-harness TOML config (slice 1)

Reference: SPEC.md + PLAN.md in this directory. Each task fits a fresh implementer context window and produces ~50–500 lines of diff.

**Sequencing:** T001 (README) is independent and ships as its own PR. T002–T005 (loader + docs) form the second PR. T006–T007 (command migrations) form the third PR. T008 is end-to-end validation, runs after all merges.

---

## T001 — README slim + content relocation
- [ ] **Status**
- **Files:** `README.md` (rewrite); new files under `docs/human/<topic>.md` as needed; `docs/human/INDEX.md` (add entries).
- **Dependencies:** none.
- **Acceptance:**
  - README contains exactly: pitch + install + 3 quickstart commands (`/z-do`, `/z-plan`, `/z-implement-all`) + pointers to `docs/human/INDEX.md`, `docs/llm/INDEX.json`, `docs/human/config.md` (placeholder link — file lands in T003) + license.
  - Every section of the OLD README that's removed is preserved in `docs/human/` (new file or appended to existing). Nothing is *deleted*, only relocated.
  - `docs/human/INDEX.md` updated with entries for any new files created.
  - Word count for new README ≤ 300 (excluding code blocks).
- **DOCS:** none (slice this is the docs work).
- **Complexity:** low

## T002 — `scripts/config.py` loader + `scripts/config.sh` wrapper
- [ ] **Status**
- **Files:** `scripts/config.py` (new), `scripts/config.sh` (new).
- **Dependencies:** none.
- **Acceptance:**
  - `scripts/config.py` exists with `DEFAULTS` dict (schema_version, notify.level, docs.always_apply) and `VALIDATORS` dict (separate from DEFAULTS for clarity).
  - All five subcommands implemented per SPEC: `get`, `export-env`, `ensure-defaults`, `explain`, `should-notify --event <kind>`.
  - Layer order matches SPEC §"Layered precedence" exactly: defaults → global → repo (via `git rev-parse --show-toplevel`, NO upward search; cwd fallback) → env.
  - Empty env vars treated as missing layer.
  - Hyphenated keys and >2-level nesting rejected at TOML load with exit 2.
  - Global-config invalid-enum: stderr warn + per-key fallback. Repo/env invalid-enum: exit 2.
  - `$Z_HARNESS_REPO_CONFIG=<nonexistent>` → exit 2.
  - 0-byte / unparseable global file in `ensure-defaults` → exit 4 with actionable message; NEVER overwrite.
  - `should-notify` always exits 0 on valid event; exits 2 on unknown event.
  - `config_resolved` event emitted from `export-env` only, gated by `$Z_HARNESS_RUN`, de-duped via `O_EXCL` temp file `$TMPDIR/z-harness-config-resolved-$Z_HARNESS_RUN`.
  - Transliteration `_dotted_to_env(key)` is a standalone pure function.
  - Exit code truth table in SPEC §"Exit code truth table" honored exactly.
  - `scripts/config.sh` is a 2-line bash wrapper invoking `python3 .../config.py "$@"` (mirrors `resolve-provider.sh`).
  - `scripts/config.py` is executable (chmod +x).
- **DOCS:** config-design
- **Complexity:** medium

## T003 — `docs/human/config.md`
- [ ] **Status**
- **Files:** `docs/human/config.md` (new); `docs/human/INDEX.md` (add link).
- **Dependencies:** T002.
- **Acceptance:**
  - Eight sections per SPEC §"File 3" outline (What this is / File locations / The knobs / Transliteration rule / CLI reference / Examples / config_resolved event / Future knobs).
  - "The knobs" table has 2 rows: `notify.level` and `docs.always_apply`, with type/default/values/description.
  - Heavy/light flow split explicitly documented: "`docs.always_apply` applies only to light flows (slice 1: /z-do). Heavy flows always dispatch doc-fetcher."
  - "Future knobs" section explicitly says "do not add knobs without a /z-plan run" — captures the schema-sprawl guardrail from both consultants.
  - Transliteration rule examples for both knobs.
  - `~/.config/z-harness/config.toml` example with both knobs set.
  - `docs/human/INDEX.md` gets a `config.md` link.
- **DOCS:** config-design
- **Complexity:** low

## T004 — `docs/llm/config-design.json` + INDEX.json wiring
- [ ] **Status**
- **Files:** `docs/llm/config-design.json` (new); `docs/llm/INDEX.json` (add concept entry).
- **Dependencies:** T002 (so `source_files` paths exist).
- **Acceptance:**
  - `docs/llm/config-design.json` matches SPEC §"File 4" shape (concept, summary, invariants array, key_files, depends_on, consumed_by).
  - `docs/llm/INDEX.json` gains a new entry with `slug: "config-design"`, `source_file: "scripts/config.py"`, `source_files` array, `last_updated` = ISO timestamp of write, `confidence: "high"`, `depends_on`, `consumed_by`, `summary`.
  - JSON is valid (round-trips through `python3 -m json.tool`).
- **DOCS:** config-design (this IS the docs file)
- **Complexity:** low

## T005 — Sanity-test `scripts/config.py` end-to-end (smoke tests)
- [ ] **Status**
- **Files:** new `scripts/test_config.py` OR a `scripts/test-config.sh` smoke script — implementer's choice. Add a brief invocation note to `docs/human/config.md` "CLI reference" section if a shell test script is added.
- **Dependencies:** T002.
- **Acceptance:** at minimum, these manual scenarios pass and are documented (asserted by python `assert` or `[ ... ]` in shell + `set -e`):
  - With no user config: `config.py get notify.level` → `approval_only`.
  - With no user config: `config.py get docs.always_apply` → `auto`.
  - `Z_HARNESS_NOTIFY_LEVEL=off config.py get notify.level` → `off`.
  - `Z_HARNESS_NOTIFY_LEVEL=loud config.py get notify.level` → exit 2.
  - `config.py get notify.lvel` (typo) → exit 3.
  - `config.py should-notify --event approval` with default → `yes`.
  - `Z_HARNESS_NOTIFY_LEVEL=off config.py should-notify --event approval` → `no`.
  - `config.py should-notify --event failre` (typo) → exit 2.
  - `config.py explain notify.level` shows source `defaults` when no user file.
  - `config.py export-env` output is `eval`-clean (running it under `set -e` does not error).
  - `_dotted_to_env("notify.level")` → `"Z_HARNESS_NOTIFY_LEVEL"`.
  - `_dotted_to_env("docs.always_apply")` → `"Z_HARNESS_DOCS_ALWAYS_APPLY"`.
- **DOCS:** none (test scaffolding)
- **Complexity:** low

## T006 — Migrate `/z-do` (notify gate + docs.always_apply branching)
- [ ] **Status**
- **Files:** `commands/z-do.md`, `skills/z-do/SKILL.md` (whichever holds the dispatch logic — likely SKILL.md; verify at implementation).
- **Dependencies:** T002, T003.
- **Acceptance:**
  - `eval "$(bash $PLUGIN_ROOT/scripts/config.py export-env)"` added to setup, after version.sh / log-event.sh stanza.
  - Every existing `PushNotification` call wrapped: `[ "$(... should-notify --event <kind>)" = yes ] && <emit>` with kind ∈ `{approval, phase_end, error}` matching event purpose.
  - The doc-fetcher dispatch conditional reads `$Z_HARNESS_DOCS_ALWAYS_APPLY`:
    - `always` → unconditionally dispatch doc-fetcher.
    - `auto` (default) → current heuristic preserved verbatim.
    - `never` → skip doc-fetcher.
  - No `Z_HARNESS_NOTIFY` references remain in /z-do files.
  - Prose mentioning Z_HARNESS_NOTIFY policy replaced by pointer to `docs/human/config.md`.
- **DOCS:** config-design (this is the canonical migration example)
- **Complexity:** medium

## T007 — Migrate `/z-plan` (notify gate ONLY)
- [ ] **Status**
- **Files:** `commands/z-plan.md`, `skills/z-plan/SKILL.md` (whichever holds dispatch logic).
- **Dependencies:** T002.
- **Acceptance:**
  - `eval "$(... config.py export-env)"` added to setup.
  - Every `PushNotification` wrapped with `should-notify` guard (events: `approval`, `phase_end`, `error`).
  - **NO changes to doc-fetcher dispatch logic** — /z-plan is a heavy flow; `docs.always_apply` does not apply.
  - Z_HARNESS_NOTIFY references replaced by pointer to `docs/human/config.md`.
- **DOCS:** config-design
- **Complexity:** medium

## T008 — End-to-end smoke + event verification
- [ ] **Status**
- **Files:** none (verification only); may add a note to `docs/human/config.md` if issues found.
- **Dependencies:** T002, T006, T007.
- **Acceptance:**
  - Run `/z-do "trivial test"` with `notify.level = off` in `~/.config/z-harness/config.toml`; verify no PushNotification fires through any phase.
  - Re-run with `notify.level = all`; verify notifications fire at phase boundaries.
  - Run `/z-do "trivial test"` with `docs.always_apply = always`; verify doc-fetcher dispatched even when heuristic would skip.
  - Re-run with `docs.always_apply = never`; verify doc-fetcher skipped.
  - Inspect `z-harness/*/archive/<run>/events.jsonl` for `config_resolved` events; verify **exactly one** per run.
  - Run `config.py explain notify.level` from inside a repo with `.z-harness/config.toml` override; verify source layer reported as `repo`.
  - Run `config.py explain notify.level` with `Z_HARNESS_NOTIFY_LEVEL=all` env override; verify source `env`.
- **DOCS:** none
- **Complexity:** low

---

## Task summary
- 8 tasks total (target was 10–20; this is on the lean side because slice 1 is deliberately scoped).
- 3 PRs natural shape: PR1 = T001 (README, independent); PR2 = T002–T005 (loader + docs); PR3 = T006–T008 (command migration + e2e).
- Complexity distribution: 6 low, 2 medium, 0 high.
