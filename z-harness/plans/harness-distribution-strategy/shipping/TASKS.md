# TASKS — C6: shipping

## Phase A — Command migration

- [ ] **T001 — Produce migration template from one representative command**
  - **Files:** `commands/z-plan.md`, `runtime/TEMPLATE-command.md` (new file)
  - **Depends:** C1 runtime contract (external — C1 must be complete), none within C6
  - **Acceptance:**
    - `runtime/TEMPLATE-command.md` exists and documents the standard header/footer/invoke pattern for the C1 runtime contract
    - Template is validated by running the migrated `z-plan.md` command body through the conformance harness on at least one available driver (passes with exit 0)
    - Template documents how to handle subagent dispatch, AskUserQuestion, and skill invocations that the target driver does not support (explicit gate comment pattern, not silent omission)
    - A "migration checklist" section in the template lists every mechanical substitution required per command
  - **Complexity:** medium

- [ ] **T002 — Bulk-migrate all remaining 27 commands to runtime contract**
  - **Files:** `commands/z-amend.md`, `commands/z-audit-plan-style.md`, `commands/z-audit-plan.md`, `commands/z-audit.md`, `commands/z-brainstorm.md`, `commands/z-debug.md`, `commands/z-do.md`, `commands/z-export.md`, `commands/z-fix.md`, `commands/z-implement-all.md`, `commands/z-implement-next.md`, `commands/z-improve.md`, `commands/z-init-docs.md`, `commands/z-maintain-docs.md`, `commands/z-mr-review.md`, `commands/z-plan-light.md`, `commands/z-plan-split.md`, `commands/z-plan.md`, `commands/z-providers-discover.md`, `commands/z-research.md`, `commands/z-review-all.md`, `commands/z-skill-fix.md`, `commands/z-stats.md`, `commands/z-style-init.md`, `commands/z-suggest-memory.md`, `commands/z-test.md`, `commands/z-update.md`, `commands/z-uplift.md`
  - **Depends:** T001
  - **Acceptance:**
    - All 27 remaining command files updated per the T001 migration checklist
    - Each migrated command retains its semantic behavior (same phases, same outputs, same hard rules)
    - Commands with unsupported constructs (subagent dispatch, AskUserQuestion) include explicit gate-comment blocks per the T001 pattern rather than silent removal
    - A diff summary (list of changed files + nature of change) is produced as a migration log in `z-harness/plans/harness-distribution-strategy/shipping/migration-log.md`
  - **Complexity:** medium

- [ ] **T003 — Run conformance acceptance against all migrated commands**
  - **Files:** (reads output of T002; no file writes in this task)
  - **Depends:** T002, C5 conformance harness (external)
  - **Acceptance:**
    - Every migrated command passes the C5 conformance harness on at least one available driver (Claude Code driver minimum)
    - Any commands that fail are listed in a `migration-log.md` appendix with the failure reason and a proposed remediation
    - Zero commands silently omitted from conformance testing — every command in `commands/z-*.md` is exercised
    - Acceptance task exits 0 only when all 28 commands have a PASS result on at least one driver
  - **Complexity:** low

## Phase B — Exporter freeze

- [ ] **T004 — Add deprecation warnings and dated-cutover comments to export-*.py**
  - **Files:** `scripts/export-codex.py`, `scripts/export-agy.py`, `scripts/export-cursor.py`, `scripts/export-common.py`
  - **Depends:** none
  - **Acceptance:**
    - Each of the four files emits a `DeprecationWarning` to stderr (Python `warnings.warn(...)` or explicit `print(..., file=sys.stderr)`) on every invocation that reads: `[z-harness] WARNING: export-<target>.py is deprecated and will be removed in the next minor release. Use the runtime driver instead.`
    - Each file contains a dated comment block at the top: `# DEPRECATED: frozen at v<current>. Remove after v<next-minor>. See C6-D1.`
    - Scripts still exit 0 and produce identical output — no functional regression
    - `export-common.py` deprecation warning fires only when invoked directly, not when imported as a module (use `if __name__ == "__main__":` guard)
  - **Complexity:** low

- [ ] **T005 — Update z-export.md to print deprecation warning and schedule docs update**
  - **Files:** `commands/z-export.md`
  - **Depends:** T004
  - **Acceptance:**
    - `commands/z-export.md` Phase 1 prepends a deprecation notice: "NOTE: the export scripts invoked by this command are deprecated. They will be removed in the next minor release. Use /z-update to switch to the runtime-based workflow."
    - A `# FOLLOW-UP:` comment block at the bottom of `z-export.md` documents that `docs/llm/multi-ide-exports.json` must be updated via a separate `/z-maintain-docs` invocation after the runtime drivers are stable
    - The existing command behavior (running export scripts) is preserved during the one-minor-version window
  - **Complexity:** low

## Phase C — Install + update refactor

- [ ] **T006 — Refactor install.sh to package runtime binary + trees + frozen exporters**
  - **Files:** `scripts/install.sh`
  - **Depends:** C1 runtime contract (external — runtime/ tree structure must be stable), C2/C3/C4 drivers (at least one driver complete)
  - **Acceptance:**
    - `install.sh` copies `runtime/` tree and `drivers/` tree to the install target alongside the existing `commands/`, `agents/`, `skills/` trees
    - `install.sh --legacy` flag installs the frozen `scripts/export-*.py` exporters in addition to the runtime paths; `--legacy` prints a deprecation notice: "NOTE: --legacy mode is available for one minor release only and will be removed in the next release."
    - Without `--legacy`, the frozen exporters are not installed (but remain available in the repo for direct use)
    - A dated comment in `install.sh` marks the `--legacy` block: `# REMOVE-AT: v<next-minor>. See C6-D1.`
    - Existing symlink mode and tarball mode continue to work; runtime packaging is an additive step
    - `install.sh --help` output updated to document new flags and paths
  - **Complexity:** medium

- [ ] **T007 — Extend z-update.md with runtime-mode detection, legacy nudge, and runtime atomic swap**
  - **Files:** `commands/z-update.md`
  - **Depends:** T006
  - **Acceptance:**
    - `z-update.md` Step 2 "Detect install mode" extended with a third mode: `runtime` (detected by presence of `runtime/` subdirectory in plugin dir)
    - New Step 2b "Detect legacy layout": if install dir contains `exports/codex/` or `exports/agy/` or `exports/cursor/` but lacks `runtime/`, set `LEGACY_LAYOUT=true`
    - When `LEGACY_LAYOUT=true`, emit a one-time nudge message: "[z-update] Your install uses the legacy export layout. Run install.sh to migrate to the runtime-based layout." and emit `migration_nudge` telemetry event with `{"layout": "legacy", "action": "nudge"}`
    - In runtime mode, atomic-swap updates `runtime/` and `drivers/` trees as part of the tarball-mode swap (not just root files)
    - `harness_updated` event payload gains `"mode": "runtime"` variant
    - Existing symlink and tarball modes are not regressed
  - **Complexity:** medium

## Phase D — Audit tarball allowlist update

- [ ] **T008 — Update audit-tarball.sh allowlist for new runtime paths and one-minor-version legacy paths**
  - **Files:** `scripts/audit-tarball.sh`
  - **Depends:** T006 (need runtime/ and drivers/ paths to be stable)
  - **Acceptance:**
    - `scripts/audit-tarball.sh` allowlist (currently implicit: anything not matching a forbidden pattern is allowed) is updated so that `runtime/` and `drivers/` top-level directories are explicitly documented in a `# ALLOWLIST:` comment block as expected new paths
    - The existing forbidden-pattern checks for `z-harness/plans/`, `z-harness/archive/`, etc. are unchanged and still enforce
    - `exports/codex/`, `exports/agy/`, `exports/cursor/` paths are added to a `# LEGACY-ALLOWLIST (remove at v<next-minor>):` comment block with a dated `# REMOVE-AT:` note; their presence in a tarball does NOT trigger the `exports/` forbidden-pattern check during the one-minor-version window
    - The `exports/` forbidden-pattern check is updated to exclude the three legacy exporter output paths during the transition window (pattern narrowed to exclude `exports/codex/`, `exports/agy/`, `exports/cursor/` specifically, while still blocking `exports/<anything-else>/`)
    - `audit-tarball.sh PASS` still exits 0 on a well-formed tarball containing both runtime paths and legacy exporter paths
  - **Complexity:** low
