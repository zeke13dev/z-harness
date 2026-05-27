# Phase 3 — Decisions final (after Gemini + Codex consult)

## Consensus
- **D2** SCOPE.json — both endorse (c) both live + archived + namespaced.
- **D4** axis discovery — both endorse (c) hybrid; both add "fail loud if no axis evidence supports taxonomy"; surface axis confidence.
- **D7** calibration replay — both endorse (a) full LLM replay; Codex adds "tag replays with calibration epoch."
- **D8** ground-truth rubric — both endorse (c) combined; both note "document rubric in versioned file."

## Disagreement
- **D1** output contract:
  - Gemini: (b) JSON-only — "z-harness binary standard"; use `jq`.
  - Codex: (c) hybrid — line-prefix for routing fields, JSON for chunks.

## Per-decision final calls + "one reason it might be wrong"

### D1: Output contract → (c) HYBRID (Codex wins)
- **Reason this might be wrong (Codex pick):** the codebase isn't actually binary — review-agent uses JSON, planning-router uses line-prefix. The "established pattern" line-prefix supposedly enforces is mixed already. Going JSON-only (Gemini) would simplify future agents.
- **Why I keep hybrid anyway:** scope-probe's *routing-class* fields (MODE/AXIS/CONFIDENCE) are conceptually identical to planning-router's (RECOMMENDED/ROUTE_CLASS/CONFIDENCE). Diverging here would create exactly the cross-agent contract confusion Codex flagged. Chunks ARE structured arbitrary-length data — JSON is right for those. Hybrid honors both established patterns.

### D2: SCOPE.json → (c) BOTH + NAMESPACED + add `last_updated` + `last_run_id`
- **Reason this might be wrong:** dual-write is a coupling source — orchestrator must update both in the same step; if it crashes between writes, live and archive diverge.
- **Mitigation:** write archive copy FIRST (atomic via tmp+rename per existing convention), then overwrite live. Crash → live stale by one run, archive correct. Readers detect via `last_run_id` ≠ current `$RUN`. Codex's `last_updated` + `last_run_id` fields land in both copies.

### D4: Axis discovery → (c) HYBRID + runtime taxonomy parameter + fail-loud + surface confidence
- **Reason this might be wrong:** if scope-probe always fails-loud when taxonomy doesn't match, edge-case topics ("audit the whole repo") may force users to manually override every time. Brittle UX.
- **Mitigation:** fail-loud only when ZERO taxonomy options have any structural evidence. Otherwise return the best-supported axis with `CONFIDENCE: low` and surface to user via host command's AskUserQuestion. Three-state: high-confidence pick / low-confidence pick / no-match-refuse.

### D7: Calibration replay → (a) LLM-REPLAY ALL + calibration epoch tag
- **Reason this might be wrong:** Haiku non-determinism means a single replay run may produce a different classification than a re-replay on the same input — calibration accuracy depends on sample-of-one per historical run.
- **Mitigation:** replay each historical run 3× (triple-sample); record per-replay classification; majority-vote wins as the "Haiku classification" for that historical run. 18 Haiku calls total for 6 historical runs. Still cheap.

### D8: Ground-truth rubric → (c) COMBINED RUBRIC + document in scripts/CALIBRATION.md + tie-break prefers escalation events
- **Reason this might be wrong:** rubric implicitly encodes the team's current understanding of "what HEAVY means." If that understanding changes (e.g. we decide tasks_complexity matters more than tasks_total), the rubric is wrong but tripwires continue to fire on the old definition.
- **Mitigation:** version the rubric in CALIBRATION.md frontmatter (`rubric_version: 1`); each calibration epoch records which rubric version was used so we can replay old data against a new rubric if needed.

## Shortcuts being taken
**None for v1a.** The "split into v1a + v1b" itself defers the aggressive refactor; within v1a everything is the robust path:
- Hybrid contract (not "simpler" JSON-only).
- Triple-sample replay (not single-sample).
- Combined rubric (not simpler task-count-only).
- Dual-write SCOPE.json (not "live-only is simpler").
- Per-host reconcilers (not generic).
- Fail-loud axis discovery with three-state graceful degradation (not simple yes/no).

## Cross-cutting concerns from consultants
1. **JSON parsing in bash:** Codex's note that the JSON-chunks-block must be `jq`-parseable from bash. Mitigation: use the same fenced-JSON convention review-agent uses (one and only one fenced block per return, no surrounding prose). The host-command parser strips line-prefix headers, then extracts the fenced JSON via the same pattern review-agent's parser uses.
2. **Live SCOPE-*.json garbage collection:** Codex flagged that abandoned slugs leave stale files. v1a deferral: no GC mechanism; track with a TODO in SPEC. v1b can add a `/z-stats` warning when live SCOPE files reference runs that don't exist in archive.
3. **D7→D8 coupling:** rubric must be a programmatic scoring function so the harness can auto-score replays. CALIBRATION.md ships with both the human-readable rubric AND a Python `classify_ground_truth(manifest, events) → LIGHT|MEDIUM|HEAVY` function in scripts/scope-probe-calibrate.py.
