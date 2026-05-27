# Amendment: Fix 5 SPEC defects from /z-implement-all batch-3 reviews

**Run:** see archive path
**Mode:** full
**Requested change:** 5 SPEC defects + 1 TASKS.md note (T006 trivial blocker).

## Design calls (locked in)

- **Issue 1 (Phase 0 ordering in /z-brainstorm):** scope-probe runs as **literal first action after Setup**, BEFORE Plan Route Check, BEFORE Phase 1 scaffolding. scope-probe internally dispatches doc-fetcher as needed (step 4 of its own protocol). Plan Route Check stays where it is. They're independent.
- **Issue 2 (HEAVY sub-flow artifact):** sub-flows run through Phase 3 (synthesis), producing per-chunk BRAINSTORM.md. Reconciler reads N chunk BRAINSTORM.md files (matches T003's existing contract — no T003 churn).
- **Issue 3 (Phase 4 chunk selection):** Phase 4 gets a new HEAVY-mode selection branch. User picks ONE `(chunk_id, framing)` pair (e.g. "C1: codex"). Single-run (LIGHT/MEDIUM) Phase 4 stays unchanged. T003's chunk-major reconciler output preserved.
- **Issue 4 (--scope-from parse ordering):** `--scope-from` parsed at the TOP of /z-audit (BEFORE Setup). Takes a bare chunk ID (e.g. `C1`) resolved against parent run's SCOPE.json via `$Z_HARNESS_PARENT_RUN_ID` env var passed from parent. Also supports absolute path to a chunk's scope_hint for out-of-band use.
- **Issue 5 (anti-sprawl contradiction):** Resolve in favor of SKIP_PHASE_0=true when --scope-from present. Remove the unreachable "when Phase 0 runs, it MUST skip HEAVY dispatch" directive. Anti-sprawl invariant becomes: --scope-from forces SKIP_PHASE_0, which makes recursive HEAVY structurally impossible. No event needed (anti-sprawl is enforced by skipping, not by detection-and-refusal).
- **Issue 6 (T006 trivial):** Add note in T006 task block. Not a SPEC change.

## What this affects

### SPEC.md
- **`agents/scope-probe.md`** section: clarify the agent dispatches doc-fetcher internally (it does this in its 5-step protocol step 4); host commands do NOT have to run doc-fetcher first.
- **`commands/z-brainstorm.md` (EDIT)** section: rewrite the Phase 0 insertion point — was "between Plan Route Check and Phase 1 scaffolding," now "literal first action after Setup, before Plan Route Check, before Phase 1 scaffolding." Document that scope-probe + Plan Route Check are independent gates serving different purposes.
- **`commands/z-brainstorm.md` (EDIT)** section, HEAVY branch: explicitly state sub-flows run through Phase 3 (synthesis) producing per-chunk BRAINSTORM.md. Phase 4 gets new HEAVY-mode chunk-selection branch.
- **`commands/z-audit.md` (EDIT)** section, `--scope-from` flag spec: clarify parse order ("BEFORE Setup"), input format (bare chunk ID resolved via `$Z_HARNESS_PARENT_RUN_ID`, OR absolute path), removal of unreachable anti-sprawl directive.

### PLAN.md
- D9 entry: clarify that Phase 0 unconditional applies to /z-audit; integration approach is the same MEDIUM-passthrough.
- D10 entry: update — `/z-brainstorm` Phase 0 is now literal first action, not "between Plan Route Check and Phase 1."
- Add `## Amendments` section at bottom recording this run.

### TASKS.md
- **New tasks:** T016 (add HEAVY-mode chunk-selection branch to /z-brainstorm Phase 4).
- **Modified tasks (`[ ]` only, deps may shift):**
  - **T006:** prepend a note in the acceptance criteria — "Remove unused `import os` from prior cycle-1 implementer attempt."
  - **T008:** acceptance criteria updated — flag parsed BEFORE Setup; `--scope-from` accepts bare chunk ID (resolved via parent run ID env) OR absolute path; anti-sprawl is enforced via SKIP_PHASE_0=true (no separate event).
  - **T010:** acceptance criteria updated — Phase 0 is literal first action after Setup (before Plan Route Check); HEAVY sub-flows run through Phase 3; HEAVY Phase 4 selection branch is T016's scope (not T010's).
  - **T012:** depends list adds T016 (docs refresh now waits for T016 too).
- **Removed tasks:** none.
- **Touched-but-completed tasks:** T001 (SPEC text about scope-probe-internal doc-fetcher clarified — but T001 already wrote scope-probe.md correctly; the SPEC clarification doesn't contradict T001's implementation). Treat as "leave alone — amendment doesn't contradict."

## Risk

Cross-LLM consult triggers (checking):
- New external dep? No.
- Public API change? Borderline — /z-brainstorm Phase 0 ordering is a user-visible pipeline change but it's internal to z-harness. Not external.
- Cross-module impact? No — confined to /z-brainstorm + commands/z-audit.md + SPEC.md + one new task T016.
- Algorithm swap? No.
- Persistence change? No.

**No consult needed.** The amendment is scoped to fixing SPEC defects the reviewer identified; the design calls are mechanical (one viable option each). Skip Phase 5.
