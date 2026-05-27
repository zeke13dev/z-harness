# TASKS — z-harness TOML config (slice 1)

Reference: SPEC.md + PLAN.md in this directory. Each task fits a fresh implementer context window and produces ~50–500 lines of diff.

**Sequencing (post-audit revision):** Two PRs.

- **PR1 = T001 + T002 + T003 + T004 + T005** — README slim + loader + docs + smoke tests, landing together so the README's link to `docs/human/config.md` isn't broken transiently.
- **PR2 = T006 + T007 + T008 + T009** — command migrations + e2e verification + prose cleanup of non-migrated commands' Z_HARNESS_NOTIFY references.

---

## T001 — README slim + content relocation
- [x] **Status** — done; reviewer flagged 1 false blocker (config.md forward-ref) — overridden, T003 lands in same PR per acceptance criteria.
- **Files:** `README.md` (rewrite); new files under `docs/human/<topic>.md` as needed; `docs/human/INDEX.md` (add entries).
- **Dependencies:** none (ships in PR1 with T002–T005).
- **Acceptance:**
  - README contains exactly: pitch + install + 3 quickstart commands (`/z-do`, `/z-plan`, `/z-implement-all`) + pointers to `docs/human/INDEX.md`, `docs/llm/INDEX.json`, `docs/human/config.md` + license.
  - Install section includes the line: `bash scripts/config.sh ensure-defaults  # creates ~/.config/z-harness/config.toml with defaults`.
  - Every section of the OLD README that's removed is preserved in `docs/human/` (new file or appended to existing). Nothing is *deleted*, only relocated.
  - `docs/human/INDEX.md` updated with entries for any new files created.
  - Word count for new README ≤ 300 (excluding code blocks).
  - The `docs/human/config.md` link is valid at PR merge time — i.e. T003 lands in the same PR.
- **DOCS:** none (slice this is the docs work).
- **Complexity:** low

## T002 — `scripts/config.py` loader + `scripts/config.sh` wrapper
- [x] **Status** — done (cycle 2); reviewer flagged 1 major in v1 (unknown TOML keys leaking via export-env); fixed in v2 with load-time filter; clean review.
- **Files:** `scripts/config.py` (new), `scripts/config.sh` (new).
- **Dependencies:** none.
- **Acceptance:**
  - `scripts/config.py` exists with `DEFAULTS` dict (schema_version, notify.level, docs.always_apply) and `VALIDATORS` dict (separate from DEFAULTS for clarity).
  - All five subcommands implemented per SPEC: `get`, `export-env`, `ensure-defaults`, `explain`, `should-notify --event <kind>`.
  - `META_KEYS = {"schema_version"}` module constant; `export-env`, `get`, `explain` skip meta keys (e.g. `config.py get schema_version` exits 3).
  - `_dotted_to_env(key)` is a standalone pure function that validates key format against regex `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`; mismatched keys → exit 2.
  - `config_resolved` event reads `$Z_HARNESS_RUN` from env (callers `export Z_HARNESS_RUN="$RUN"` before invoking).
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
- [x] **Status** — done; clean review, no findings.
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
- [x] **Status** — done (cycle 2); v1 had 2 blockers (source_file type, out-of-scope timestamp mutation) + format + minor; all fixed in v2; clean review.
- **Files:** `docs/llm/config-design.json` (new); `docs/llm/INDEX.json` (add concept entry).
- **Dependencies:** T002 (so `source_files` paths exist).
- **Acceptance:**
  - `docs/llm/config-design.json` matches SPEC §"File 4" shape (concept, summary, invariants array, key_files, depends_on, consumed_by).
  - `docs/llm/INDEX.json` gains a new entry with `slug: "config-design"`, `source_file: "scripts/config.py"`, `source_files` array, `last_updated` = ISO timestamp of write, `confidence: "high"`, `depends_on`, `consumed_by`, `summary`.
  - JSON is valid (round-trips through `python3 -m json.tool`).
- **DOCS:** config-design (this IS the docs file)
- **Complexity:** low

## T005 — Sanity-test `scripts/config.py` end-to-end (smoke tests)
- [x] **Status** — done (cycle 3, user override of MAX_ATTEMPTS); v1 9 majors→v2 fixed 7→v3 fixed remaining 2 assertion-strictness items; 45 tests passing.
- **Files:** new `scripts/test_config.py` OR a `scripts/test-config.sh` smoke script — implementer's choice. Add a brief invocation note to `docs/human/config.md` "CLI reference" section if a shell test script is added.
- **Dependencies:** T002.
- **Acceptance:** All scenarios below pass under `set -e`. Use a hermetic test fixture (`XDG_CONFIG_HOME=$(mktemp -d)` per test; cleanup on exit) to avoid touching the developer's real `~/.config/z-harness/`.

  **Baseline (defaults):**
  - `config.py get notify.level` → `approval_only`.
  - `config.py get docs.always_apply` → `always`.
  - `config.py get schema_version` → exit 3 (meta key, not user-exposed).

  **Env override:**
  - `Z_HARNESS_NOTIFY_LEVEL=off config.py get notify.level` → `off`.
  - `Z_HARNESS_NOTIFY_LEVEL="" config.py get notify.level` → `approval_only` (empty = missing layer).
  - `Z_HARNESS_NOTIFY_LEVEL=loud config.py get notify.level` → exit 2.

  **Repo-local precedence:** with `.z-harness/config.toml` containing `notify.level = "off"`:
  - `config.py get notify.level` → `off`.
  - `config.py explain notify.level` shows source `repo`.
  - With ALSO `Z_HARNESS_NOTIFY_LEVEL=all`: `get` → `all`, `explain` source → `env`.

  **Unknown / typo'd keys:**
  - `config.py get notify.lvel` → exit 3.
  - `config.py explain notify.lvel` → exit 3.

  **`should-notify` truth table (9 branches):** for every `(level, event)` pair with `level ∈ {off, approval_only, all}` and `event ∈ {approval, phase_end, error}`, assert stdout matches SPEC §"should-notify Logic":
  - `off` × `{approval, phase_end, error}` → `no`, `no`, `no`.
  - `approval_only` × `{approval, phase_end, error}` → `yes`, `no`, `yes`.
  - `all` × `{approval, phase_end, error}` → `yes`, `yes`, `yes`.
  - `config.py should-notify --event failre` (typo) → exit 2 + stderr lists allowlist.

  **`ensure-defaults` behavior:**
  - On empty `$XDG_CONFIG_HOME`: creates `~/.config/z-harness/config.toml`; prints `created <path>`.
  - Second invocation: `exists <path>`; file unchanged.
  - With pre-existing 0-byte file: exit 4 with actionable message; file NOT overwritten.
  - With pre-existing malformed TOML (e.g. `notify.level = `): exit 4; file NOT overwritten.

  **TOML / schema errors:**
  - Repo-local file with `notify.level = "loud"` → exit 2 (project-specific invalid: hard-fail).
  - Global file with `notify.level = "loud"` → stderr warn + `get notify.level` returns `approval_only` (default; per-key fallback).
  - Any layer with `schema_version = 2` → exit 2 + message naming the file.
  - Malformed TOML at any layer → exit 2 with parser line/column.

  **Explicit override path:**
  - `Z_HARNESS_REPO_CONFIG=/nonexistent/path config.py get notify.level` → exit 2 (explicit miss is loud).

  **Event de-dup:** with `Z_HARNESS_RUN=test-run-123`:
  - First `config.py export-env` emits one `config_resolved` event.
  - Second `config.py export-env` with same `Z_HARNESS_RUN` emits zero (O_EXCL temp file blocks).
  - Without `$Z_HARNESS_RUN`: zero events emitted.

  **Pure transliteration function:**
  - `_dotted_to_env("notify.level")` → `"Z_HARNESS_NOTIFY_LEVEL"`.
  - `_dotted_to_env("docs.always_apply")` → `"Z_HARNESS_DOCS_ALWAYS_APPLY"`.
  - `_dotted_to_env("notify-level")` raises / exits 2.
  - `_dotted_to_env("a.b.c")` raises / exits 2 (>2 levels).
  - `_dotted_to_env("notify")` raises / exits 2 (no dot).

  **eval-cleanliness:** `eval "$(config.py export-env)"` under `set -e` succeeds and sets `$Z_HARNESS_NOTIFY_LEVEL` and `$Z_HARNESS_DOCS_ALWAYS_APPLY` but NOT `$Z_HARNESS_SCHEMA_VERSION`.
- **DOCS:** none (test scaffolding)
- **Complexity:** low

## T006 — Migrate `/z-do` (notify gate + docs.always_apply branching)
- [x] **Status** — done (cycle 1); scope expanded post-preflight to ADD 4 PushNotification calls at halt/finalize points per user decision; clean review.
- **Files:** **Both** `commands/z-do.md` AND `skills/z-do/SKILL.md` — both contain the matching code paths; update both. If they have drifted from each other (different doc-fetcher dispatch wording or different PushNotification call sites), halt and escalate before editing.
- **Dependencies:** T002, T003.
- **Pre-flight (must pass before editing):**
  - `grep -n 'PushNotification' commands/z-do.md skills/z-do/SKILL.md` returns ≥1 hit per file.
  - `grep -n 'doc-fetcher' commands/z-do.md skills/z-do/SKILL.md` returns the expected dispatch lines (Phase 2 in current SKILL.md).
  - If either grep is empty or returns unexpected counts, halt: the SPEC assumption has drifted; escalate to user.
- **Acceptance:**
  - Both files gain the setup snippet immediately after the existing `RUN=...` line:
    ```
    export Z_HARNESS_RUN="$RUN"
    eval "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" export-env)"
    ```
  - Every existing `PushNotification` call in both files wrapped: `[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event <kind>)" = yes ] && <emit>` with kind ∈ `{approval, phase_end, error}` matching event purpose.
  - The doc-fetcher dispatch conditional in both files reads `$Z_HARNESS_DOCS_ALWAYS_APPLY`:
    - `always` (default, matches current behavior) → unconditionally dispatch doc-fetcher when `docs/llm/INDEX.json` exists.
    - `never` → skip doc-fetcher even when INDEX.json exists.
  - No `Z_HARNESS_NOTIFY` references remain in either file.
  - Prose mentioning Z_HARNESS_NOTIFY policy replaced by pointer to `docs/human/config.md`.
- **DOCS:** config-design (this is the canonical migration example)
- **Complexity:** medium

## T007 — Migrate `/z-plan` (notify gate ONLY)
- [x] **Status** — done (cycle 1); clean review; both files symmetric.
- **Files:** **Both** `commands/z-plan.md` AND `skills/z-plan/SKILL.md` — update both. If they have drifted, halt and escalate.
- **Dependencies:** T002.
- **Pre-flight (must pass before editing):**
  - `grep -n 'PushNotification' commands/z-plan.md skills/z-plan/SKILL.md` returns ≥1 hit per file.
  - If either grep is empty, halt: SPEC assumption drifted; escalate.
- **Acceptance:**
  - Both files gain the setup snippet (matching T006):
    ```
    export Z_HARNESS_RUN="$RUN"
    eval "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" export-env)"
    ```
  - Every `PushNotification` in both files wrapped with the `should-notify --event <kind>` guard.
  - **NO changes to doc-fetcher dispatch logic** — /z-plan is a heavy flow; `docs.always_apply` does not apply to it (the knob is out-of-scope for heavy flows).
  - Z_HARNESS_NOTIFY prose references replaced by pointer to `docs/human/config.md`.
- **DOCS:** config-design
- **Complexity:** medium

## T008 — End-to-end smoke + event verification
- [x] **Status** — closed by user decision: T005's 45 hermetic unit tests (covering event de-dup, payload accuracy with `sources` mapping, full 9-branch should-notify matrix, repo-precedence, env-shadows-repo, global-fallback path) provide equivalent coverage at the loader level. Live `/z-do` integration smoke deferred to slice 2.
- **Files:** none (verification only); may add a note to `docs/human/config.md` if issues found.
- **Dependencies:** T002, T006, T007.
- **Isolation:** All tests run with `export XDG_CONFIG_HOME=$(mktemp -d)` and `trap 'rm -rf $XDG_CONFIG_HOME' EXIT` to avoid touching the developer's real `~/.config/z-harness/config.toml`.
- **Acceptance:**
  - Run `/z-do "trivial test"` with `notify.level = off` in `$XDG_CONFIG_HOME/z-harness/config.toml`; verify no PushNotification fires through any phase.
  - Re-run with `notify.level = all`; verify notifications fire at phase boundaries.
  - Run `/z-do "trivial test"` with `docs.always_apply = always`; verify doc-fetcher dispatched.
  - Re-run with `docs.always_apply = never`; verify doc-fetcher skipped.
  - Inspect `z-harness/*/archive/<run>/events.jsonl` for `config_resolved` events; verify **exactly one** per run.
  - **Payload accuracy:** Run /z-do with `.z-harness/config.toml` (repo-local) containing `notify.level = "all"`; parse the emitted `config_resolved` event; assert `event.values["notify.level"] == "all"` AND `event.sources["notify.level"] == "repo"`.
  - **Env shadows repo precedence:** with `.z-harness/config.toml` (notify.level=approval_only) AND `Z_HARNESS_NOTIFY_LEVEL=all` set, run `config.py explain notify.level`; assert source=`env`, value=`all`.
  - Run `config.py explain notify.level` from inside a repo with `.z-harness/config.toml` override (env unset); verify source layer reported as `repo`.
  - Run `config.py explain notify.level` with `Z_HARNESS_NOTIFY_LEVEL=all` env override (no repo file); verify source `env`.
- **DOCS:** none
- **Complexity:** low

## T009 — Mechanical prose pass: Z_HARNESS_NOTIFY refs in non-migrated commands
- [x] **Status** — done (cycle 1 + 1 orchestrator-applied fix for environment-knobs.md M2 finding); 27 files updated. M1 (scope creep) rejected as reviewer hallucination (z-plan-light/z-plan-split are siblings of z-plan, not in exclusion list). M3 (z-debug/z-implement-all/z-review-all shell blocks read env without setup) accepted but deferred to slice 2 (env var name change is forward-compat; current behavior unchanged since both old + new vars are unset until export-env runs).
- **Files:** every file in `grep -lr 'Z_HARNESS_NOTIFY' commands/ skills/` EXCLUDING `commands/z-do.md`, `skills/z-do/SKILL.md`, `commands/z-plan.md`, `skills/z-plan/SKILL.md` (those are handled by T006/T007). Expected set: ~16 files including `z-implement-all`, `z-debug`, `z-research`, `z-test`, `z-amend`, `z-brainstorm`, `z-fix`, `z-audit`, `z-maintain-docs`, `z-plan-light`, `z-plan-split`, `z-review-all`, `z-implement-next` (commands and/or skill counterparts).
- **Dependencies:** T002, T003.
- **Acceptance:**
  - Each remaining `Z_HARNESS_NOTIFY` doc reference replaced with prose pointing at `docs/human/config.md` (e.g. "Notification policy: see `docs/human/config.md` — `notify.level` key").
  - No CODE references to `Z_HARNESS_NOTIFY` exist anywhere in the repo after this task (none currently do per audit; verify with final `grep -r 'Z_HARNESS_NOTIFY' scripts/ commands/ skills/` returning empty).
  - No behavior change in any of the touched files — this is a prose-only pass.
- **DOCS:** none (touching command files directly)
- **Complexity:** low

## T010 — docs/human/config.md intro consistency polish (cosmetic)
- [ ] **Status**
- **Files:** `docs/human/config.md`
- **Dependencies:** none (cosmetic; can ship anytime).
- **Acceptance:**
  - Intro paragraph references the loader using the same invocation form as the CLI reference section: `${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py ...` instead of bare `scripts/config.py ...`. (Optional: leave the prose-style bare reference in the intro and document inline that the full invocation is in the CLI reference section.)
- **Source:** Codex final-review minor finding. Cosmetic; not user-blocking.
- **Complexity:** low

## T011 — Slice-2 migration tracker (placeholder)
- [ ] **Status**
- **Files:** N/A — tracker only; no code change.
- **Dependencies:** none.
- **Acceptance:** This task exists so the slice-2 deferred items are not forgotten. When slice-2 planning starts, run `/z-plan` (or `/z-plan-light`) scoped to:
  - Migrate `commands/z-debug.md` + `skills/z-debug/SKILL.md` to use `config.py export-env` + `should-notify` (currently uses `${Z_HARNESS_NOTIFY_LEVEL:-approval_only}` in shell blocks without prior export-env step).
  - Migrate `commands/z-implement-all.md` + `skills/z-implement-all/SKILL.md` (same issue).
  - Migrate `commands/z-review-all.md` + `skills/z-review-all/SKILL.md` (same issue).
  - Decide whether to add `Z_HARNESS_DOCS_ALWAYS_APPLY` enforcement to `/z-plan-light` (light flow; currently untouched).
  - Plus the consult-prefs / escalation-budgets / archive-retention knobs called out in BRAINSTORM.md slice-2.
- **Source:** PLAN.md non-goals + both consultants' Prong A minor recommendations.
- **Complexity:** medium (when actually planned, not just tracked).

---

## Task summary
- **11 tasks total** (originally 8; T009 added in post-audit amendment; T010 + T011 added post-final-review as cosmetic / slice-2 placeholders).
- **2 PRs shipped this slice** (PR1 = T001–T005; PR2 = T006–T009). T010 and T011 are post-merge follow-ups.
- Complexity distribution: 8 low, 2 medium, 0 high (excluding T011 placeholder).
