---
artifact: review-tasks
slug: tiered-quality-uplift
run_id: 20260526T055704Z-review
source_findings: archive/20260526T055704Z-review/findings.md
drift_findings: 7
spec_gap_findings: 2
escalations: 0
---

# Review Tasks — tiered-quality-uplift

Findings promoted from `/z-review-all`. Delete any candidate you do not want fixed, then run:

`/z-implement-all --tasks=z-harness/plans/tiered-quality-uplift/REVIEW-TASKS.md`

## Candidate fixup tasks

### [x] T-REV-001 — [blocker] Cross-cutting synthetic row never enters implement queue
- **Class:** implementation_drift
- **Source:** Prong A; Codex; verified by orchestrator. SPEC L139 + PLAN D6 require synthetic `-cross-cutting` to run FIRST in Phase 5; Phase 2 leaves it in `[ ] pending`; Phase 3 excludes `-cross-cutting` rows; Phase 5 Step 1 only queues `[a] audited` / `[i] implementing`. Net: synthetic row never queued.
- **Pushback:** maybe Phase 5 implicitly accepts `[ ] pending` for the synthetic row? Verified — Step 1 filter is strict (`actionable = '[a] audited' in state or '[i] implementing' in state`).
- **Files:** `commands/z-uplift.md` (Phase 2 Step 6 ~line 1543, OR Phase 5 Step 1 queue filter ~line 12 of Phase 5)
- **Depends on:** none
- **Acceptance:** After Phase 2 Step 6 inserts the synthetic row, MANIFEST shows it in state `[a] audited` (preferred fix), OR Phase 5 Step 1 queue includes `[ ] pending` rows whose slug ends in `-cross-cutting`. A dry run with global-task findings produces a queue whose first entry is the synthetic component.

### [x] T-REV-002 — [major] Phase 2 Step 6 MANIFEST insertion is non-atomic
- **Class:** implementation_drift
- **Source:** Prong A; Codex; verified. Direct `with open(...,"w") as f: f.write(content)` at commands/z-uplift.md:1545-1546 bypasses the `manifest_write` helper / tmpfile + os.replace pattern used everywhere else.
- **Pushback:** narrow interruption window for a single insert. Still violates the orchestrator-wide invariant.
- **Files:** `commands/z-uplift.md` (~line 1543-1547)
- **Depends on:** none
- **Acceptance:** Phase 2 Step 6 uses `manifest_write(path, content)` (or inlines tmpfile + os.replace) consistent with Phase 5 mutations.

### [x] T-REV-003 — [major] CRIT_HIGH_COUNT counts substrings, not distinct findings
- **Class:** implementation_drift
- **Source:** Prong A; Codex; verified. commands/z-uplift.md:~1892 uses `re.findall(r'\b(?:CRITICAL|HIGH)\b', text)` over the entire REPORT body, so descriptive prose containing the words inflates the count and can falsely trigger the >10 CRIT-HIGH auto-bail.
- **Pushback:** severity tags are typically one per finding. But prose use of the words is realistic.
- **Files:** `commands/z-uplift.md` (~line 1885-1895)
- **Depends on:** none
- **Acceptance:** REPORT is parsed structurally (per-finding bullet/header), then CRIT_HIGH_COUNT counts findings whose severity field equals CRITICAL or HIGH. Adjacent TOTAL_COUNT regex (line 1898) is reconciled with the same structural parse.

### [x] T-REV-004 — [major] Unguarded `git grep` searches whole repo when OTHER_COMP_PATHS is empty
- **Class:** implementation_drift (was T004 deferred Note — confirmed by both LLMs)
- **Source:** Prong A; both consultants.
- **Pushback:** rare in multi-component repos; common in single-component repos.
- **Files:** `commands/z-uplift.md` (~line 1957, Phase 3 Step 2g-3 bail logic)
- **Depends on:** none
- **Acceptance:** `if [ -n "$OTHER_COMP_PATHS" ]; then git grep -l ... -- $OTHER_COMP_PATHS; else DEPS_FOUND=""; fi`. Single-component repo dry run produces empty `DEPS_FOUND` instead of a full-repo grep dump.

### [x] T-REV-005 — [major] Slug-collision handling: N-way + custom-slug re-validation incomplete
- **Class:** implementation_drift (was T002 deferred Note — confirmed by both LLMs)
- **Source:** Prong A; both consultants.
- **Files:** `commands/z-uplift.md` (~lines 895-1157, Phase 1 Step 2 collision resolution)
- **Depends on:** none
- **Acceptance:** Collision resolution loops until no duplicate slugs remain (handles N>2 groups); user-supplied custom slugs are re-validated against the `to_slug()` regex AND re-checked for collisions before COMPONENTS.md is written; failure path surfaces clear error rather than silently writing a malformed MANIFEST.

### [x] T-REV-006 — [major] Cross-cutting findings parser drops bullets without G-/C-/R- prefix
- **Class:** implementation_drift (was T003 deferred Note — confirmed by both LLMs)
- **Source:** Prong A; both consultants. Real consultant output is variable; current parser silently drops anything without the strict prefix.
- **Files:** `commands/z-uplift.md` (~line 1271, Phase 2 Step 5 extract_findings); plus prompt at Phase 2 Step 2 (tighten cross-cutting MODE prompt to enforce the format consultants emit)
- **Depends on:** none
- **Acceptance:** Either (a) the cross-cutting consultant prompt explicitly requires `G-NNN`/`C-NNN`/`R-NNN` bullets and the parser logs a `cross_cutting_findings_dropped` event if any non-conforming lines are encountered, OR (b) parser tolerates a relaxed `**class:** ...` header. Either way, no silent drops.

### [x] T-REV-007 — [minor] Phase 4 summary doesn't surface cross-cutting-first ordering rule
- **Class:** implementation_drift
- **Source:** Prong B; Gemini.
- **Files:** `commands/z-uplift.md` (Phase 4 summary block, ~line 2333)
- **Depends on:** none
- **Acceptance:** Phase 4 informational summary includes a one-line callout when the MANIFEST contains a `-cross-cutting` row: "Note: `<slug>-cross-cutting` will be implemented first (per SPEC §Phase 5)."

## Amendment proposals

### [s] T-REV-008 — [minor] Amend SPEC: declare auditor finding-output format
- **Class:** spec_gap
- **Disposition:** amendment_proposal
- **Source:** Prong B; Gemini.
- **Pushback:** the auditor agent is referenced from /z-audit which already specifies this. But the cross-reference isn't explicit in this SPEC.
- **Files:** `z-harness/plans/tiered-quality-uplift/SPEC.md`, `PLAN.md`, `TASKS.md`
- **Depends on:** none
- **Acceptance:** Run `/z-amend` to add an "Auditor output contract" subsection to SPEC stating the F-NNN / C-NNN / P-NNN / D-NNN finding-ID convention and the severity-tag placement. PLAN gets a one-line decision note referencing /z-audit; TASKS does not need a new entry (existing T-REV-003 carries the implementation).

### [s] T-REV-009 — [minor] Amend SPEC: explicit cross-cutting parser format contract
- **Class:** spec_gap
- **Disposition:** amendment_proposal
- **Source:** Prong A/B intersection; both consultants.
- **Pushback:** could be folded into T-REV-008; keep distinct because the cross-cutting prompt is a separate consultant invocation.
- **Files:** `z-harness/plans/tiered-quality-uplift/SPEC.md`
- **Depends on:** T-REV-008 (apply in same /z-amend invocation if you choose)
- **Acceptance:** SPEC documents that Phase 2 consultants MUST emit `G-NNN` / `C-NNN` / `R-NNN` bullets and that any non-conforming output is reported via the `cross_cutting_findings_dropped` event (paired with T-REV-006).

## Superseding tasks

None — no `[x]` task is contradicted; all blockers/majors are on code paths authored in this plan that need refinement, not retraction.

## Escalations

None — no premise failure. The architecture and gate placement are correct; the gaps are localized.

## Report-only observations

- A-mi1 (export-collision fix is scope-limited to skill/command pairs; no agent/skill or agent/command collision handling). No actionable task — scope-limit is acceptable until such a collision exists.
