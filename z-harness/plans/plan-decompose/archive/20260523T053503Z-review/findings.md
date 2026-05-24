# Final review — plan-decompose
Run: 20260523T053503Z-review
Base: per-task captured diffs T001–T004 (repo has accumulated changes from prior plans — scoped review to this plan's files only)
Diff stats: 6 files, ~1493 insertions, 14 deletions

## Prong A — Implementation drift

### blocker
- [gemini] **MANIFEST `status` enum drift between SPEC and implementation.** SPEC §"MANIFEST.md schema" line 52 declares `status: planning | ready | partial`, but the implementation (commands/z-plan-split.md line 355) and the cross-task consumer (`/z-implement-all` Setup 2b.6, which halts on `status: planning OR failed` per SPEC line 288) actually use `ready | partial | failed`. SPEC is internally inconsistent on its own enum.
  - *One reason it might be wrong:* The `planning` value may have been intended as a transient state during cluster-planner execution, never written to MANIFEST.md (because MANIFEST is written only after all planners return). If so, the implementation's `ready | partial | failed` is the correct realized enum and SPEC line 52 is stale. The fix is in SPEC, not code.

### major
- [both] **Namespace inconsistency: `<cluster-id>` vs `<cluster_slug>` in SPEC filesystem paths.** SPEC line 68 establishes the rule (`cluster_id` = telemetry handle like `C1`; `cluster_slug` = directory name in kebab-case). But SPEC Phase 2 dispatch template line 197 still writes `output-path: z-harness/<root-slug>/<cluster-id>/` and Phase 3 line 226 writes `z-harness/.../<cluster-id>/archive/...`. Codex notes: implementation follows intent, but a literal reading produces wrong directories.
- [both] **`shared_concerns_acknowledged` event declared but never emitted.** SPEC line 328 lists this event with required fields `total_overlaps, highest_severity, acknowledged_by`, but neither `/z-plan-split` nor `/z-implement-all` emits it. The override path emits `shared_concerns_ack_override` (T003 cycle-2 addition); the halt path emits `shared_concerns_unacknowledged`. There is no positive-confirmation event for the "user actually edited frontmatter to true" path.
- [both] **`cluster_decision_escalated` payload under-documented in cluster-planner.** SPEC line 323 requires fields `cluster_id, decision_id, decision_summary, flagged_reason`. agents/cluster-planner.md Phase 3 only mentions `flagged_reason` — `decision_summary` isn't documented as a required payload field at the emit site.

### minor
- [gemini] SPEC severity-heuristic regexes lack `$` anchors (line 124-126 form), while the implementation includes them. Implementation is right; SPEC text is loose. Below blocker bar.
- [gemini] Path-normalization escape rejection reuses `precontext_freshness_check_failed` (a `/z-plan` event name) for a `/z-plan-split` scenario. Cosmetic.
- [codex] `doc-fetcher` failure-mode fallback (timeout, malformed INDEX.json) not specified in either command or agent. Implementation will degrade gracefully but SPEC should be explicit.

## Prong B — Spec gaps

### blocker
None.

### major
- [gemini] **Partial-tree definition references legacy `planning` state.** SPEC says `partial_tree: true` iff any cluster has `status != ready`, which textually includes `planning`. But `planning` doesn't exist in MANIFEST (see Prong-A blocker). Tied to the same fix.
- [gemini] **Ack-gate state machine under-specified.** SHARED-CONCERNS.md frontmatter has `acknowledged_at` and `acknowledged_by` fields but SPEC doesn't say who populates them: orchestrator or user? Implementation has to guess. Probably user-set (manual edit) but worth nailing down.
- [codex] **No spec guidance for malformed cluster TASKS.md during Phase 4 validation.** SPEC says "parse each cluster's TASKS.md" but doesn't say what happens on YAML/format errors. Reasonable interpretation: mark cluster failed with `cluster_files_inconsistent` and continue.
- [codex] **`/z-implement-all` doesn't validate MANIFEST `Path` column points to an existing directory** before using it as BASE. Trivial check missing; corrupted MANIFEST would produce confusing downstream errors.

### minor
- [gemini] Re-spawn `DECISIONS_RESOLVED` counting semantics ambiguous on multi-escalation clusters.
- [gemini] No file-read budget (≤10) for cluster-planner Phase 1 enumerated in SPEC; only in agent prose.
- [codex] No quantitative cost model for `/z-plan-split` breakeven N (when is it cheaper than single `/z-plan`?). Currently qualitative.
- [codex] Severity heuristic flags `package.json` as `high` regardless of monorepo context; documented v1 limitation, but README v1-limitations could call out monorepo false alarms.
- [codex] One-level recursion invariant scattered across multiple SPEC sections; consolidating the two complementary checks (cluster-planner anti-nesting + /z-implement-all tree_depth_exceeded) into one explicit statement would help.

## Consensus vs disagreement

**Both LLMs flagged (high confidence):**
1. `<cluster-id>` vs `<cluster_slug>` filesystem-path inconsistency in SPEC (Prong A major)
2. `shared_concerns_acknowledged` event declared-but-unimplemented (Prong A major)
3. `cluster_decision_escalated` payload `decision_summary` field undocumented in cluster-planner (Prong A major)

**Gemini-only:**
- MANIFEST `status` enum drift (Prong A **blocker** — the only blocker in the review)
- partial-tree definition references stale `planning` state (related to blocker)
- ack-gate state machine ambiguity (`acknowledged_at`, `acknowledged_by`)

**Codex-only:**
- doc-fetcher failure fallback unspecified
- `/z-implement-all` doesn't validate MANIFEST Path exists on disk
- Malformed TASKS.md handling in Phase 4
- Monorepo false-alarm on package.json (v1 limitation worth documenting)

## Pushback applied

Pushed back on / down-weighted:
- Gemini's "moderate" path-normalization conflict-with-FILES_TOUCHED-check finding — the intent is clear in context, just verbose prose.
- Gemini's "re-spawn doesn't reset decision counter" finding — implementation behavior is sane; spec ambiguity is theoretical.
- Codex's mirror-pair tolerance finding — explicitly within the documented tolerance; not a finding.
- Codex's scope-too-broad-needs-examples — UX nicety, not a correctness gap.

## Recommendation

The blocker is **spec-side only** — SPEC line 52 needs to be updated to match what the implementation actually does (`ready | partial | failed`). No code changes required for the blocker.

The 3 consensus majors are all minor edits to SPEC.md + one missing event emission. Estimated 1–2 small fixup tasks if pursued; or accept as v1 known gaps.
