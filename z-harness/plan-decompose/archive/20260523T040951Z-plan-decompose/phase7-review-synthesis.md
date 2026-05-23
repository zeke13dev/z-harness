# Phase 7 — plan-review synthesis

Codex returned 6 majors + 4 minors. Gemini returned 1 blocker + 8 majors + 1 minor. Consensus on 5 items, unique on several others.

## Apply (folds into SPEC amendments)

### Consensus

1. **FILES_TOUCHED format + canonicality.** SPEC §"cluster-planner Phase 6" claims FILES_TOUCHED is "the reconciliation hook" while SPEC §"Phase 4" says main thread parses Files: from TASKS.md. Resolve: **TASKS.md is canonical.** FILES_TOUCHED is a JSON array of workspace-relative file paths returned by cluster-planner as a fast-path summary; main thread validates it against TASKS.md and fails the cluster if they disagree.

2. **Conservative-flagging rubric.** "Borderline non-obvious" is currently subjective. Add explicit escalation triggers to cluster-planner Phase 3 (and T001 acceptance): escalate iff decision involves (a) public API / interface change, (b) new external dependency, (c) modifying shared config / migration / schema (`*.toml`, `*.json`, `*.sql`, `*.yaml`, `*.yml`, `*.proto`), (d) structural changes outside the cluster's declared file set, (e) irreversible data migration, (f) algorithm with materially different perf/correctness characteristics. Anything else can be resolved unilaterally.

3. **Decision-gate re-spawn payload format.** When main thread resolves an escalated decision, the re-spawn prompt must contain a structured resolution block: `decision_id` (assigned by cluster-planner), `question`, `options`, `chosen_option`, `rationale`, `affected_files`. cluster-planner's re-invocation resumes from Phase 4 (skip Phase 0-3 since premise + exploration + decisions are settled).

4. **Path normalization for overlap detection.** Before applying severity heuristics, normalize: workspace-relative (strip any leading `/`, `./`), collapse `.` and `..` segments, normalize separator to `/`, reject paths escaping repo root. Apply across both FILES_TOUCHED summaries and TASKS.md-parsed paths.

5. **Nested MANIFEST definition.** "Nested MANIFEST" = `MANIFEST.md` found via recursive glob `**/MANIFEST.md` starting from any cluster directory listed in the root MANIFEST. `/z-implement-all` validates this before walking.

### Gemini-only

6. **Partial-tree ack-gate.** SHARED-CONCERNS.md frontmatter gains `partial_tree: true` field when any cluster failed (status != ready). `/z-implement-all` halts on a partial tree unless `--force-partial` flag is passed. Reasoning: overlap detection on incomplete cluster data is unreliable — clusters that failed before producing TASKS.md don't contribute to overlap detection, so detected overlaps are a lower bound, not authoritative.

7. **Severity precedence + minimum-touch rule.** Apply heuristics in cascading precedence (high > medium > low). Files touched by exactly 1 cluster are severity `none` and excluded from SHARED-CONCERNS.md entirely. Files matching multiple severity criteria pick the highest match.

8. **Telemetry event field schemas.** SPEC lists event kinds but not required fields. Add: `cluster_decision_escalated` requires `cluster_id, decision_id, decision_summary, flagged_reason`; `overlap_detected` requires `file_path, cluster_ids, severity`; `shared_concerns_acknowledged` requires `total_overlaps, highest_severity, acknowledged_by`.

9. **Doc-fetcher dispatch condition (clarification).** Already conditional on `docs/llm/INDEX.json` per existing global memory; SPEC clarifies cluster-planner Phase 1 dispatches `doc-fetcher` **only if** INDEX.json exists AND cluster-planner judges that one cluster-relevant concept might be in scope. Cluster-planner does NOT main-thread-Read INDEX.json (memory rule).

### Codex-only

10. **Cluster attempt lifecycle in MANIFEST.** Each cluster row in MANIFEST gains `attempts: <N>` and `final_status_at: <UTC ISO>`. Reconciliation reads only the final accepted return; if a cluster was re-spawned after `decision_needed`, MANIFEST records `attempts: 2` (or N) and reconciliation uses the final TASKS.md.

11. **Anti-self-nesting guard in cluster-planner.** cluster-planner Phase 0 checks: if its output path is itself nested inside a parent MANIFEST (i.e., walk up the slug-dir ancestors looking for MANIFEST.md), refuse to write and return `STATUS: anti_nesting_violation`. Prevents accidental tree-of-trees if user manually invokes /z-plan-split with a slug like `<existing-root>/cluster-X`.

## Push back

These are flagged but the spec position holds:

- **Codex Major 6 — "Overlapping clusters during /z-implement-all execution."** Sequential MANIFEST order IS the guarantee. Cluster 2 starts after cluster 1's tasks finish; there is no concurrent write to `utils.ts`. Codex's concern is real for *implementations* that ignore the sequential rule; not a spec gap. Adding extra clarification text in SPEC, not changing the design.

- **Gemini Major 1 — "Premise re-evaluation Phase 1.5."** The cluster-planner already escalates on `STATUS: premise_invalid` (which we'll formalize as the rubric in finding #2). A separate Phase 1.5 is overkill — premise check at Phase 0 reading the same files exploration reads gives the same coverage with less ceremony.

- **Gemini Minor 5 — "MANIFEST run-order stability across re-runs."** Already covered by D10 (overwrite/abort re-run rule). Re-run is destructive; new MANIFEST is fresh. No SPEC change needed.

## SPEC patch list

Concrete edits to SPEC.md:
1. §"FILES_TOUCHED" — add canonicality rule + JSON-array schema + validation against TASKS.md.
2. §"cluster-planner Phase 3" — add conservative-flagging rubric.
3. §"Phase 3 — Collect leaf returns" — add re-spawn payload format.
4. §"Phase 4 — Reconciliation" — add path normalization rules.
5. §"`/z-implement-all` extension" — add nested-MANIFEST recursive glob check.
6. §"SHARED-CONCERNS.md schema" — add `partial_tree` frontmatter field.
7. §"SHARED-CONCERNS.md schema, severity heuristics" — add cascading precedence + 2+ minimum rule.
8. §"Telemetry events" — add per-event required field schemas.
9. §"cluster-planner Phase 0" — add anti-self-nesting check returning `STATUS: anti_nesting_violation`.
10. §"MANIFEST.md schema" — add `attempts: <N>` and `final_status_at: <UTC ISO>` per cluster row.

Estimated SPEC delta: ~80 lines added/modified, no structural rewrites.
