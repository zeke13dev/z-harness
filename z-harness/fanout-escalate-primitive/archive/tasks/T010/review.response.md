# Codex review of T010

## Findings

### Blockers

**1. Plan Route Check executes at wrong phase — spec conflict (line 203-206)**
The spec says Plan Route Check runs "after Phase 1 scaffolding is assembled," but the amended flow requires Phase 0 → Plan Route Check → Phase 1. This contradicts the prerequisite that Plan Route Check needs Phase 1's doc-fetcher signals. Either Phase 1 must run before Plan Route Check (reordering), or Plan Route Check must use only pre-scaffolding signals (signal list revision required).

**2. Sub-flows do NOT receive $Z_HARNESS_PARENT_RUN_ID environment variable (line 151-162)**
The sub-flow prompt mentions "Parent run id: <RUN>" in prose, but the Agent dispatch does not export `$Z_HARNESS_PARENT_RUN_ID=<RUN>` as an environment variable. Acceptance criterion 5 requires this to be passed so sub-flows can locate the parent's SCOPE.json. Without the exported env var, the sub-flow has no way to resolve a relative chunk spec when needed.

**3. refused/bad_input event logging is unreachable (line 197-199)**
The branch structure processes "LIGHT or MEDIUM" first (line 129), then branches on HEAVY vs refused/bad_input. But if scope-probe returns `STATUS: refused` with `MODE: MEDIUM`, the preceding LIGHT/MEDIUM handler already catches it, so the refused/bad_input branch never executes. Events `scope_probe_refused` and `scope_probe_bad_input` will never be logged, violating the spec requirement. Fix: branch on STATUS first, log the appropriate event, then proceed with MEDIUM pass-through.

**4. Ambiguous double-writer contract for unified BRAINSTORM.md (line 172-184)**
The dispatch to scope-reconciler-brainstorm says "output_path: $Z_HARNESS_PLAN_DIR/BRAINSTORM.md" (suggesting reconciler writes), but then step 5 says "Take the text returned by scope-reconciler-brainstorm and write it to BRAINSTORM.md" (suggesting parent writes). This creates ambiguity: does reconciler write the file or return text? Per reconciler-brainstorm agent spec, it returns text and the parent writes; the output_path field in the prompt is misleading.

## Summary

The implementation has Phase 0 positioned correctly and most scaffolding in place, but four correctness issues block acceptance: Plan Route Check is at the wrong execution point, sub-flows lack the required parent-run-id env var, refused/bad_input events are unreachable, and the reconciler writer contract is ambiguous.
