# Final review — compaction-cadence
Run: 20260525T081221Z-review
Base ref: 380aca6 (HEAD; all plan work is uncommitted)
Diff stats: 14 files, 885 insertions, 96 deletions (scoped to compaction-cadence-touched files; exports omitted from review diff but verified separately in T009)

## Prong A — Implementation drift

### Severity: blocker
- _none._ (Codex flagged two; both are false positives — verified below.)

### Severity: major
- _none._

### Severity: minor
- **[gemini] State file schema extras.** `/z-review-all` state file includes `run_id` and `cumulative_stat_path` fields beyond what SPEC.md specifies. Forward-compatible safety improvement (corrupt-state detection, stat round-trip).
  - **Evidence:** commands/z-review-all.md (Phase 3.7 state-file schema)
  - **Pushback:** Extending a JSON schema with optional fields is always safe for a single-writer artifact; the spec could legitimately remain a minimum-fields contract.
- **[gemini] No explicit acceptance for Finalize-skip on trigger.** Behavior is documented (lines 232–236 + 497) but T003's acceptance criteria don't require a test/probe confirming Finalize is NOT executed when condition (3) fires.
  - **Pushback:** The branch is enumerated in plain English at two places; a test asserting absence-of-behavior is hard to wire without runtime probes.

### False-positive findings (rejected after pushback)
- **[codex] A1: trigger check embedded as per-task sub-step (claimed blocker).** Rejected. Lines 175 and 495 both state the trigger check runs "once per batch, after all tracks finish, after the atomic TASKS.md write, after `batch_done`, after halt signals resolved." Codex misread the surface organization (the trigger check lives as a numbered sub-step inside step 8's documentation list) as semantic per-task placement; the substep body explicitly guards on batch-settle conditions.
- **[codex] A2: Finalize-skip not implemented (claimed blocker).** Rejected. Lines 232–236 enumerate three loop-exit conditions; (3) is "compaction trigger fired → emit, push-notify, exit without running Finalize." Line 497 reiterates "Finalize section is **skipped**." The skip is documented narratively because this is a prompt-driven orchestrator, not a code module — there's no `exit` statement to point at; the orchestrator is the LLM following the SKILL.
- **[codex] PENDING_REMAINING lacks pseudocode (claimed major).** Rejected. Line 192 says "count the remaining `[ ]` tasks in `$TASKS_FILE`" — that's adequate; the orchestrator reads TASKS.md as a string and counts a marker.

## Prong B — Spec gaps

### Severity: blocker (spec must be corrected before shipping)
- _none._

### Severity: major (spec should be amended; existing implementation may stand)
- **[both] Slug-scoping invariant violated for `/z-maintain-docs --audit`.** SPEC.md asserts state files are slug-scoped (`z-harness/plans/<slug>/.maintain_docs_audit_state.json`), but `/z-maintain-docs` has no slug. Implementer correctly overrode to `docs/llm/.maintain_docs_audit_state.json` (repo-wide); commands.json reflects the override. SPEC needs an amendment acknowledging that the maintain-docs path is the documented exception.
  - **Evidence:** SPEC.md (slug-scoping clause); commands/z-maintain-docs.md (actual path); TASKS.md T006 Note (already flagged during implementation)
  - **Pushback:** This was flagged at implementation time and the override is internally consistent; arguably the spec just needs a one-line erratum, not a structural amendment.
  - **Consequence:** Repo-wide path means two concurrent maintain-docs `--audit` runs on the same checkout would race on the state file. In practice nobody runs two `/z-maintain-docs --audit` concurrently; risk is acceptable.

### Severity: minor (worth noting for future plans)
- **[gemini] Tree-rooted plan behavior for pause counters undocumented.** SPEC silent on whether `tasks_since_pause` resets per-cluster or accumulates across clusters. Implementation appears to reset per-cluster (counters are bound at Setup step 5; tree-rooted iteration rebinds BASE per-cluster). Sensible default.
- **[gemini] Empty stale-concept set on `--audit`.** SPEC silent on what happens when the audit breakpoint fires with zero stale concepts. Current behavior: fires anyway. Reasonable.
- **[gemini] `--tasks` flag scope.** New `--tasks=<path>` flag on `/z-implement-all` for promoted-artifact iteration is outside compaction-cadence SPEC but well-designed; orthogonal scope creep.

## Consensus vs disagreement
- **Both flagged:** B1 (maintain-docs slug-scoping). High confidence — known + already documented in T006 Note during implementation.
- **Gemini-only:** A3 schema extras, A9 finalize-skip acceptance, B5 tree-rooted reset, B8 empty stale set, B9 `--tasks` flag.
- **Codex-only:** A1/A2 blockers — REJECTED after code verification. Codex appears to have over-indexed on surface document structure without tracing the documented invariants.

## Verdict

**Ship. No blockers, no majors that affect runtime behavior.** The only ship-relevant gap is B1 (SPEC amendment for maintain-docs slug-scoping exception), which is already documented in TASKS.md T006 Note and reflected correctly in the implementation + docs/llm/commands.json.
