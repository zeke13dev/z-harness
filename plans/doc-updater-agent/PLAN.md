# PLAN: doc-updater-agent — Two-Tier Automatic Doc Maintenance

> Generated: 2026-06-09
> Slug: doc-updater-agent
> Status: plan

---

## Goals

1. **Eliminate the "remember to run docs" friction** — Doc maintenance runs automatically during the pipeline, not as a separate step.
2. **Preserve warm pipeline context for narrative docs** — Capture design decisions, tried-and-failed approaches, and rationale while context is fresh.
3. **Keep mechanical doc sync cheap** — Flash subagent per task (~$0.02/plan) for machine-truth field updates.
4. **Produce narrative documentation from accumulated context** — ADRs, design rationale, tradeoff explanations, and migration guides from `tier2-context.json`.
5. **Maintain `/z-maintain-docs` as quarterly deep-clean fallback** — Not replaced; complemented.

---

## Decisions

### D1: Tier 1 — Flash subagent per task (not Python script)
- **Chosen:** Flash subagent (`tier1-doc-updater`) per task
- **Rejected:** Python regex script ($0 but handles fewer edge cases), inline orchestrator logic (burns main-thread context)
- **Rationale:** Real-world diffs have edge cases (complex renames, multi-hunk diffs spanning same function) that a small LLM handles better than regex. Start with Flash; benchmark cost after first 3 runs; add script fast-path if data supports it.
- **Risk:** Cost estimate untested. Mitigation: measure per-task Flash cost; add script fast-path if >$0.003/task.

### D2: New tier1-doc-updater agent type
- **Chosen:** New `tier1-doc-updater` agent (Flash-pinned)
- **Rejected:** Reuse existing `doc-updater` with model param (contract confusion), inline in orchestrator (context saturation)
- **Rationale:** Clean contract separation. Tier 1 (mechanical, Flash, per-task) is a different concern from existing doc-updater (narrative, Sonnet, quarterly) and Tier 2 (narrative, Pro, end-of-pipeline). Three distinct agents for three distinct concerns.
- **Risk:** Agent registry bloat. Mitigation: Tier 1 contract is 4 output fields — minimal maintenance burden.

### D3: tier2-context.json at plan dir root
- **Chosen:** `$Z_HARNESS_PLAN_DIR/tier2-context.json`
- **Rejected:** Per-run archive (harder to discover across multi-invocation pipeline), dedicated subdir (unnecessary nesting)
- **Rationale:** Plan dir is the shared namespace for the entire plan lifecycle. z-plan → z-implement-all → z-review-all share the same slug and plan dir. Single file, incrementally accumulated, finalized at z-review-all end.
- **Risk:** Plan dir already has SPEC/PLAN/TASKS — mutable JSON could confuse. Mitigation: clear naming, documented role.

### D4: Human override capture via "Why?" follow-up
- **Chosen:** AskUserQuestion "Why?" follow-up at each decision gate where human overrides
- **Rejected:** Deferred capture only (reasoning stale), structured prompt embedded in decision gate (users skip the field)
- **Rationale:** Reasoning is freshest at decision time. Skippable (Enter to skip). Captured overrides append to tier2-context.json.human_overrides[] immediately. Documents ship with honest gaps if skipped.
- **Risk:** Doubles interaction count at override gates. Mitigation: skippable; users who habitually skip get honest-gap documents.

### D5: No changes to existing doc-updater agent
- **Chosen:** Existing `doc-updater` (Sonnet, /z-maintain-docs) stays unchanged
- **Rejected:** Teach markers to doc-updater (adds complexity, regression risk), remove doc-updater entirely (loses quarterly deep-clean)
- **Rationale:** AUTO-START/AUTO-END markers are additive — they don't break existing behavior. /z-maintain-docs naturally regenerates content between markers. Zero regression risk to the quarterly deep-clean path.
- **Risk:** /z-maintain-docs might strip or conflict with markers. Mitigation: test before shipping — run /z-maintain-docs after Tier 1; verify marker survival.

---

## Non-Goals (MVP)

1. **Cross-workstream tradeoff synthesis** — Patterns across multiple independent plans. Out of scope.
2. **Language-aware parsers** — Visibility changes (pub→pub(crate)), docstring regeneration. v2.
3. **ADR numbering collision prevention** — Concurrent plans could collide on ADR N+1 allocation. Acceptable for MVP.
4. **`kind: rationale` in doc-fetcher** — Keyword-searchable ADR index. v2.
5. **README auto-update** — Tier 1 surfaces drift warnings only; never auto-updates README.
6. **Replacing /z-maintain-docs** — Explicitly preserved as quarterly deep-clean fallback.

---

## Approved Shortcuts

None. All decisions proceed with their robust implementations. The only deferred optimization is Tier 1 script fast-path (D1 risk mitigation), which is explicitly a post-implementation measurement, not a shortcut.

---

## Ordered Implementation Phases

### Phase A: Foundation — Scripts + Agent Definitions
1. `scripts/append-tier2-context.py` — Incremental context accumulation script
2. `scripts/reconcile-tier1-staged.py` — Tier 1 reconciliation script
3. `agents/tier1-doc-updater.md` — Flash subagent definition
4. `commands/z-doc-rationale.md` — Tier 2 command

### Phase B: Implementer + Reviewer Contract Extensions
5. `agents/implementer.md` — Add RATIONALE/TRIED/DEVIATIONS fields
6. `agents/reviewer.md` — Add DEVIATIONS validation + RATIONALE plausibility + TRIED consistency

### Phase C: Orchestrator Integration — z-implement-all
7. `skills/z-implement-all/SKILL.md` — Tier 1 dispatch + tier2-context.json accumulation + reconciliation

### Phase D: Orchestrator Integration — z-plan
8. `skills/z-plan/SKILL.md` — Tier 2 context init + human override capture

### Phase E: Orchestrator Integration — z-review-all
9. `commands/z-review-all.md` — Review patterns accumulation + Tier 2 significance gate

### Phase F: Docs + Bootstrap
10. Add AUTO-START/AUTO-END markers to existing `docs/human/*.md` files
11. Update `docs/llm/INDEX.json` with new concepts
12. End-to-end test: run full pipeline (z-plan → z-implement-all → z-review-all → /z-doc-rationale)

---

## DRY / KISS / SOLID

- **DRY:** Single writer per artifact — `append-tier2-context.py` writes tier2-context.json; `reconcile-tier1-staged.py` writes docs; `regenerate-memories-flat.py` writes MEMORIES-FLAT.md. No duplicate update logic.
- **KISS:** Two tiers, two agents, two scripts. Tier 1: diff → pattern-match → update (mechanical). Tier 2: JSON → narrative docs (generative). Clean separation, no cross-tier coupling.
- **Single Responsibility:** `tier1-doc-updater` syncs machine-truth fields only. `z-doc-rationale` writes narrative docs only. Implementer reports what happened; reviewer validates it; neither writes docs.
- **Open/Closed:** New machine-truth doc sections can be added by adding new AUTO-START/AUTO-END marker pairs. Tier 1 auto-discovers these. New tier2-context.json fields can be added to the schema without changing the append script (schema validation is additive). Orchestrator hooks are explicit insertion points, not rewritten phases.
- **Interface Segregation:** Implementer adds 3 optional, backward-compatible fields. Reviewer adds 3 checks within existing severity buckets. No new subagent interfaces — tier1-doc-updater follows the same subagent pattern as all others.
- **Dependency Inversion:** Tier 1 depends on INDEX.json (data), not on doc-updater (agent). Tier 2 depends on tier2-context.json (data), not on any orchestrator. Both tiers consume structured data, not direct agent-to-agent coupling.

---

## Cost Model

| Component | Frequency | Cost/unit | Total per significant plan |
|---|---|---|---|
| Tier 1 Flash subagent | ~20 tasks | ~$0.001/task | ~$0.02 |
| Tier 1 reconciliation | Once | $0 (script) | $0 |
| Tier 2 context accumulation | Incremental across phases | $0 (warm context, script append) | $0 |
| Tier 2 Pro subagent | Once (if gated) | ~$0.05 | $0-0.05 |
| Tier 2 human conversation | Once (if gated) | 10-30 sec human time | 0-30 sec |
| **Total (significant)** | | | **~$0.07 + 10-30 sec** |
| **Total (non-significant)** | | | **~$0.02 + 0 sec** |

Comparison: One cold `/z-maintain-docs` invocation costs ~$0.03-0.05 and provides structural refresh only (no narrative docs). Tier 1+2 is cost-neutral for structural docs and adds narrative documentation for ~$0.02-0.05 marginal cost.

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Flash subagent cost exceeds estimate | Medium | Low | Measure after 3 runs; add script fast-path |
| Implementer fabricates TRIED entries | Medium | Low | Caveat banner + source attribution; reviewer flags gross inconsistencies |
| AUTO-START markers stripped by existing tooling | Low | Medium | Test /z-maintain-docs flow before shipping |
| tier2-context.json grows too large across long pipelines | Low | Low | Schema fixed; ~3-5K tokens; arrays bounded by task count (max ~25 entries each) |
| Human override capture friction leads to skipping | Medium | Low | "Why?" prompt is skippable; documents ship with honest gaps |
| Tier 1 reconciliation merge conflicts | Low | Medium | Latest-wins strategy; docs outside delimiters unchanged by Tier 1 |
