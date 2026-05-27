---
artifact: shared-concerns
slug: harness-distribution-strategy
generated_at: 2026-05-27T05:05:49Z
acknowledged: true
acknowledged_at: 2026-05-27T05:05:49Z
acknowledged_by: orchestrator-auto (overlap_count: 0)
overlap_count: 0
partial_tree: false
---

# Shared concerns — harness-distribution-strategy

No file-path overlaps detected across clusters.

## Cross-cluster awareness items (informational, beyond strict file-overlap)

These are not file-path collisions, so they do not gate `/z-implement-all`'s ack-check. They are dependencies and shared assumptions the implementer should be aware of when working on the affected clusters.

### A1. `runtime/drivers/__init__.py` ownership
- **Listed in:** C4 (driver-claude-cursor) FILES_TOUCHED only.
- **Concern:** This package init file lives in a directory where C2 (driver-codex) and C3 (driver-antigravity) also place their drivers. If the file performs side-effect registration (e.g. populating a registry of available drivers), C2 and C3 should NOT have to edit it; if it doesn't (just a marker), the implementer should keep it minimal so additions from other clusters don't conflict.
- **Recommended posture:** Treat `runtime/drivers/__init__.py` as a *passive* package marker. Driver registration lives in `runtime/contract/` (C1) — drivers register themselves at import time via a decorator C1 exposes.

### A2. `runtime/TEMPLATE-command.md` directory-ownership
- **Listed in:** C6 (shipping) FILES_TOUCHED only.
- **Concern:** This file lives under `runtime/` which C1 (runtime-core) owns as a tree. C6 placing a migration template there is fine but should be coordinated so C1's structure expectations aren't violated.
- **Recommended posture:** Either move to `commands/TEMPLATE-command.md` (under the dir C6 owns) or to `runtime/contract/TEMPLATE-command.md` (so it sits beside the schemas it instantiates). Implementer's call; surface during /z-audit-plan if uncertain.

### A3. `scripts/install.sh` vs `install.sh` path discrepancy
- **Listed in:** C6 (shipping) FILES_TOUCHED as `scripts/install.sh`.
- **Concern:** The actual file in the repo is at the top-level `install.sh` (per the RESEARCH.md doc-fetcher synthesis citing `install.sh:102`, `install.sh:149`). C6's SPEC should reference `install.sh`, not `scripts/install.sh`. This is a spec-drift; the implementer will hit it on day one.
- **Recommended posture:** Treat this as a known C6 SPEC bug. Either /z-amend the C6 plan to fix the path before implementation, or have the implementer normalize when it surfaces.

### A4. `HostDriver` interface dependency (C1 → C2/C3/C4)
- **Source:** C2-T006 and C4 structural notes from cluster-planner returns.
- **Concern:** C2's T006 (driver integration tests) is blocked on C1 finalizing the `HostDriver` abstract interface. C4's `SelfHostDriver` specifically requires C1's `HostDriver` to expose a "tool-call injection point" so in-process primitives (Read/Edit/Bash/Agent) can be bound at init time. If C1's interface as planned doesn't accommodate this, C4-T002 will expose the gap.
- **Recommended posture:** C1 lands FIRST in run order (C1 → C2 → C5 → C3 → C4 → C6). C4 implementer should validate the `HostDriver` ABC against the `SelfHostDriver` need on first task; if mismatch, escalate via /z-amend on C1 rather than working around it locally.

### A5. Conformance harness fixture sequencing (C5 → C1/C2)
- **Source:** C5 plan, Phase B notes.
- **Concern:** C5 tasks T001-T004 and T008-T010 can be implemented immediately; T005-T007 (recorded fixtures) are placeholders marked `xfail` in pytest until C1 + at least one driver (C2) land and a `--record` run can capture real fixtures.
- **Recommended posture:** /z-implement-all should run C5 in parallel with C2 per the run order, but C5-T005-T007 acceptance criteria will only flip to passing AFTER C2 is complete. This is encoded in C5's PLAN.md risks section.

### A6. `commands/z-*.md` migration scope (C6)
- **Source:** C6 plan; FILES_TOUCHED enumerates all 28 commands.
- **Concern:** This list IS the full inventory of z-harness slash commands. C6's T001 (template) + T002 (bulk migrate) + T003 (conformance acceptance) compress the work, but the bulk-migration in T002 is the largest single task in the entire 6-cluster plan by line-count. If T002 reviewer feedback fires, the retry cost is high.
- **Recommended posture:** /z-implement-all should run C6-T002 with extra care — consider /z-test on C6 before T002 to draft acceptance tests per migrated command.
