# PLAN — C6: shipping

## Goal

Cluster C6 delivers the distribution and migration layer for the new host-neutral z-harness runtime. The goal is precisely scoped: migrate all 28 existing `commands/z-*.md` bodies to the C1 runtime contract using a template-then-bulk pattern; freeze the three per-host Python exporter scripts plus their shared library under the C6-D1-resolved one-minor-version deprecation cadence; and refactor `install.sh`, `commands/z-update.md`, and `scripts/audit-tarball.sh` to package and maintain the runtime binary + trees alongside the frozen exporters during the transition window. This cluster does not implement the runtime or drivers — it gates on them.

## Decisions

| ID | Question | Chosen option | Rationale |
|----|----------|---------------|-----------|
| C6-D1 | Deprecation/removal cadence for export-*.py and pre-migration commands | one-minor-version | export-*.py and pre-migration commands print a deprecation warning for one minor version then are removed in the following release; audit-tarball.sh keeps legacy paths in allowlist for that one minor version; install.sh keeps a --legacy flag scoped to one minor version, removed thereafter; z-update emits a one-time migration nudge when it detects legacy install layout |

## Non-goals (v1)

- Runtime implementation (C1)
- Driver implementations (C2/C3/C4)
- Conformance harness implementation (C5)
- Public release CDN / tarball hosting setup
- Inline update of `docs/llm/multi-ide-exports.json` (deferred to follow-up `/z-maintain-docs` call)
- Per-command-per-driver compatibility matrix (conformance harness gates this; C6 just invokes it)

## Approved shortcuts

- The bulk migration task (T002) uses the validated template from T001 without re-reviewing each command body individually. Commands that already comply with the runtime contract require only mechanical header/footer changes.
- `install.sh` `--legacy` flag is a simple boolean; no complex mode-negotiation is needed.

## Phases

### Phase A — Command migration (T001, T002, T003)

Establish the migration template from one representative command, bulk-migrate all 28 commands, then run conformance acceptance.

### Phase B — Exporter freeze (T004, T005)

Add dated deprecation warnings to the four export scripts and update `commands/z-export.md` to print a deprecation warning phase. Schedule the deferred `docs/llm/multi-ide-exports.json` update.

### Phase C — Install + update refactor (T006, T007)

Refactor `install.sh` to package runtime binary + trees + frozen exporters; add `--legacy` flag. Extend `commands/z-update.md` with runtime-mode detection, legacy-layout nudge, atomic-swap for binary + trees, and `migration_nudge` telemetry event.

### Phase D — Audit tarball allowlist update (T008)

Update `scripts/audit-tarball.sh` to add new runtime and drivers paths to the allowlist while keeping legacy export paths in place for one minor version.

## Risks

- **Conformance harness availability (C5 dependency).** If C5 is not complete when T003 runs, acceptance is blocked. Mitigation: T003 explicitly depends on C5 conformance gates being green on at least one driver.
- **Runtime contract drift (C1 dependency).** If C1 changes the runtime contract after T001 produces the template, T002 bulk migration may need a re-pass. Mitigation: T001 must produce a template signed off against the final C1 spec, not a draft.
- **Bulk migration scope creep.** 28 commands contain diverse patterns (subagent dispatch, AskUserQuestion, skill invocations). The template must handle all variants or explicitly gate non-supportable patterns. Mitigation: T001 documents unresolved patterns; T002 flags individual commands that require special treatment.
- **audit-tarball.sh removal timing.** Legacy paths must stay in the allowlist for exactly one minor version and then be removed. Mitigation: use a dated `# REMOVE-AT: vX.Y` comment pattern in T008.

## DRY / KISS / SOLID applied

- **DRY:** migration template (T001) is the single authoritative pattern; bulk migration (T002) applies it mechanically without re-deriving.
- **KISS:** `--legacy` flag in install.sh is a one-line guard, not a full alternate code path.
- **SOLID / single responsibility:** `z-update.md` handles update orchestration; detecting legacy layout and emitting a nudge is a single added detection step, not a refactored sub-command.
