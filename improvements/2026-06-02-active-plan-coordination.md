# Z-harness retro: 20260601T191549Z-active-plan-coordination

**Run:** z-harness/archive/20260601T191549Z-active-plan-coordination
**Date:** 2026-06-02
**Status:** draft — under discussion

## Run summary
A `/z-plan` run for the active-plan-coordination feature (premise → exploration → decisions → user_gate → consult → spec_plan → final_review). The premise was redirected from "registry-only(codex)" to "hybrid-worktree+thin-registry" after the user prioritized git-level robustness; planning completed with SPEC/PLAN/TASKS produced. Longest measured phases: consult (~284 s) and final_review (~262 s).

## Friction observed
- **Doc drift 68.4% vs 20% threshold** — `doc_drift_acknowledged {stale_pct: 68.4, threshold: 20, decision: proceed_weight_less}`. The freshness gate fired and the user proceeded, but at 3.4× the threshold the gate behaves identically to a 21% drift — no stronger signal that docs are *badly* out of date.
- **Gemini rate-limited, silent degradation** — `consult_done {gemini_status: "rate_limited_fallback"}`. The cross-LLM consult effectively ran codex-only, but the headline summary did not flag reduced confidence.
- **Phase timing logs `wall_ms: 0`** — premise, decisions, user_gate, and spec_plan all logged `wall_ms: 0` despite clearly consuming wall-clock time (e.g. ~24 min elapsed between consult-end and spec_plan-end). Only consult and final_review carried real values.

## Proposed improvements

### Proposal 1: Persist phase-start timestamp to disk, not a shell variable
- **Symptom:** Four phases logged `wall_ms: 0`; z-improve's own slow-phase analysis is blinded.
- **Root cause:** `commands/z-plan.md:233` instructs `T0=$(date +%s%3N)` at phase start and `WALL_MS=$(( $(date +%s%3N) - T0 ))` at phase end. But each `Bash` tool call is a fresh shell — `T0` set in one call is gone by the phase-end call in a later turn, so `WALL_MS` resolves against an empty/zero `T0`.
- **Edit target:** `commands/z-plan.md` ~lines 233–239, plus optionally a `scripts/log-phase.sh` helper (`phase_begin RUN N` writes `$RUN_DIR/.phase-<n>-start`; `phase_end RUN N` reads it back and computes the delta).
- **Proposed change:** Replace the shell-var pattern with a file-persisted start stamp under the run dir, read back at phase end. This makes wall_ms survive across tool-call boundaries.
- **Why this helps:** Restores the per-phase timing that the whole `/z-improve` friction analysis (and `/z-stats`) depends on.
- **Risk:** Adds small marker files to the run dir (cleanup on run end); the helper must fail-open if the start file is missing (emit no event rather than a bogus one).

### Proposal 2: Session-sticky doc-drift acknowledgment
- **Symptom:** This run and run 2 (persona-rotation) both hit ~68% drift in the same session; run 2 explicitly noted "user chose proceed-with-stale earlier this session" yet was re-prompted.
- **Edit target:** `commands/z-plan.md` step 9c freshness gate (and any shared freshness-gate logic).
- **Proposed change:** When the user selects "proceed with all stale," record a session-scoped marker keyed on the **content hash of `docs/llm/INDEX.json`**. On a later gate in the same session, if the hash is unchanged, downgrade the gate to a one-line notice instead of a blocking AskUserQuestion. A refresh (`/z-maintain-docs`) changes the hash and re-arms the gate.
- **Why this helps:** Removes repeated identical prompts within a session while staying correct if docs actually change.
- **Risk:** Stale acceptance could ride too long if keyed wrong — keying on INDEX.json content hash (not a boolean) bounds this.

### Proposal 3: Surface consultant degradation in the consult summary
- **Symptom:** Gemini rate-limited to a codex-only consult, but the user-facing headline did not say so.
- **Edit target:** `commands/z-plan.md` Phase 3 consult summary step.
- **Proposed change:** When any consultant `*_status != ok`, prepend a line to the user-facing summary: "Consult degraded — <provider> unavailable (<reason>); treated as single-LLM, lower confidence."
- **Why this helps:** The user can weight the consult appropriately and optionally re-run it.
- **Risk:** Minimal — surfacing only, no behavior change.

## Discussion log
- **P1 (phase timing):** User accepted. Applied. Root cause confirmed in code: `commands/z-plan.md:233` set `T0` in a shell variable that does not survive across `Bash` tool-call boundaries (`log-phase.sh`'s existing `start/end` token has the same carry problem). Added file-persisted `begin`/`finish` subcommands keyed on (run, phase).
- **P2 (doc drift):** User rejected the band-aid (session-sticky ack) in favor of a real solution — verbatim: *"the doc drift thing is a problem i think we need to always be maintaining docs or have that as a hook instead of this staleness like a real solution."* On refine, chose **run-end auto doc-sync (in-harness)**. Agreed this is a real feature, not a retro tweak — captured as direction, recommended its own `/z-plan`.
- **P3 (consult degradation):** User accepted. Applied.

## Decisions
- **P1 — ACCEPTED, applied.** `scripts/log-phase.sh` (+ `begin`/`finish`) and `commands/z-plan.md` Phase telemetry. Diffs: `improvement-1.diff`, `improvement-2.diff`.
- **P2 — ACCEPTED as direction; deferred to its own plan.** Mechanism: run-end auto doc-sync inside z-implement-all / z-do / z-fix. Not applied inline (too large for a retro edit). Next action: `/z-plan` "run-end auto doc-sync so docs stay fresh by construction; retire the staleness-gate friction."
- **P3 — ACCEPTED, applied.** `commands/z-plan.md` Phase 3 degraded-consult disclosure. Diff: `improvement-3.diff`.

**Status:** complete
