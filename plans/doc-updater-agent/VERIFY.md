---
artifact: verify
slug: docs-maintenance
run_id: 20260612T181032Z-verify-docs-maintenance
generated_at: 2026-06-12T18:10:32Z
subject: z-harness docs maintenance system
phase: understanding
---

# VERIFY.md — z-harness docs maintenance system

## Reconstructed model

**Subject:** The z-harness docs maintenance system — the full pipeline for keeping `docs/human/` (Markdown prose) and `docs/llm/` (token-compacted JSON) in sync with source code.

**Declared intent:** From agent specs (`agents/doc-updater.md`, `agents/tier1-doc-updater.md`) and command/skill specs (`commands/z-maintain-docs.md`, `skills/z-maintain-docs/SKILL.md`, `skills/z-implement-all/SKILL.md`, `skills/z-plan/SKILL.md`, `skills/z-review-all/SKILL.md`) — a two-tier documentation system with (a) manual structural refresh via `/z-maintain-docs`, (b) automatic per-task mechanical sync via Tier 1 during `/z-implement-all`, (c) narrative design docs via Tier 2 `/z-doc-rationale`, (d) an optional `--glossary` phase to refresh CONTEXT.md, and (e) a memory authoring layer via `/z-suggest-memory`.

**Actual behavior:** The two-tier system is bootstrapped (48 human docs, 34 LLM JSONs, 34 concepts in INDEX.json) but partially synced. The structural refresh path and automatic Tier 1 sync are wired in skills but show no recent execution evidence. The memory system is effectively empty (2 memories across 34 concepts). INDEX.json is 2 days stale. 3 concept docs with `## Key entry points` sections are missing AUTO-START markers, making them invisible to Tier 1 mechanical sync.

### Surface

- `commands/z-maintain-docs.md` — Command spec: structural refresh with `--scope`, `--glossary`, `--dry-run`, `--audit` flags; runtime contract conformance table
- `skills/z-maintain-docs/SKILL.md` — Operational playbook: 5 phases + compaction breakpoint + audit + glossary
- `skills/z-implement-all/SKILL.md:793-822,977-985` — Tier 1 per-task sync + Finalize reconciliation (auto)
- `agents/doc-updater.md` — Sonnet subagent: refreshes one concept's human + LLM tier; dry-run default; preserves memories verbatim; tag dedup pass when `dedup_tags: true`
- `agents/tier1-doc-updater.md` — Flash subagent: diff-only surgical updates to AUTO-START/AUTO-END sections; stages to `tier1-staged/`
- `scripts/regenerate-memories-flat.py:1` — Builds MEMORIES-FLAT.md from all concept JSONs; atomic write via tmpfile+os.replace; exit codes 0/1/2
- `scripts/reconcile-tier1-staged.py:1` — Merges staged Tier 1 updates into live docs; updates INDEX.json; regenerates MEMORIES-FLAT.md
- `scripts/add-doc-markers.py:1` — Idempotent: wraps `## Key entry points`, `## Public API`/`## Exports`, `## Configuration` in AUTO-START/AUTO-END markers
- `scripts/append-tier2-context.py:1` — Accumulates tier2-context.json across pipeline phases; validates against per-field schema; atomic write
- `skills/z-plan/SKILL.md:763` — Phase 8: appends `**DOCS:** <concept-slug>` to tasks touching public surfaces
- `skills/z-review-all/SKILL.md:813` — Push-notifies `/z-maintain-docs` recommendation after review
- `skills/z-suggest-memory/SKILL.md` — Memory authoring command; append/edit/delete; cancel is default
- `docs/llm/INDEX.json` — Central registry: 34 concepts, generated 2026-06-10

### Internals

Four update mechanisms, each with a distinct trigger. An optional fifth (glossary refresh) runs within `/z-maintain-docs --glossary`.

**1. `/z-maintain-docs` (manual structural refresh)** — `commands/z-maintain-docs.md` + `skills/z-maintain-docs/SKILL.md`:
- Phase 0: Preflight — checks INDEX.json exists; resolves mode (apply vs dry-run vs glossary)
- Phase 1: Finds stale concepts by comparing `last_updated` against `git log -1 --format=%cI` per source file. Also checks for `task_done` events, `doc_drift` events, and INVARIANTS.json staleness (inline Python script checks invariant source files against git timestamps; dispatches doc-updater in `mode: invariants` for stale ones)
- Phase 1.5 (`--glossary` only): Re-extracts domain terms via Explore subagent, diffs against CONTEXT.md, proposes additions/edits. Additive only — never removes existing `### <Term>` entries. Writes directly in apply mode
- Phase 2: Captures baseline memory counts, then spawns doc-updater (Sonnet) subagents in `mode: dry-run` with `dedup_tags: true`, up to 3 parallel. Validates `MEMORIES_PRESERVED` against baseline
- Phase 2.3 (`--audit` only): Compaction breakpoint — recommends `/clear` before expensive cross-LLM audit. State file at `docs/llm/.maintain_docs_audit_state.json` enables fast-forward on re-invocation
- Phase 2.5 (`--audit` only): Parallel cross-LLM audit via consultant-primary + consultant-secondary per concept. Both flagging = rejected; disagreement = needs review; both agree = audit-passed
- Phase 3: Risk triage — classifies into deferred (not_enough_info), flagged (memories_lost, audit rejected/needs review), clean. Clean auto-applied. Flagged get per-concept AskUserQuestion (Apply anyway / Skip). Also handles stale memory review (Keep/Edit/Delete, atomic splice for deletes) and TAG_COLLISIONS advisory report (non-blocking)
- Phase 4: Writes accepted human + LLM tier files atomically per concept; updates INDEX.json
- Phase 4.5: Unconditionally regenerates MEMORIES-FLAT.md via `regenerate-memories-flat.py`
- Phase 5: Cleans up audit state file; logs `maintain_docs_end` with counts; recommends `git add docs/ CONTEXT.md && git commit`

Trigger patterns (from `commands/z-maintain-docs.md` trigger patterns section):
- After `/z-implement-all` finalizes, recommended-next push-notification lists `/z-maintain-docs`
- After `/z-review-all` accepts a plan, same
- Standalone: user runs whenever they suspect drift
- Could be wired into CI as `claude /z-maintain-docs` (applies by default)

**2. Tier 1 per-task mechanical sync (auto)** — `skills/z-implement-all/SKILL.md:793-822,977-985`:
- Step 7a.5: After reviewer passes (no blockers/majors), captures per-task diff, spawns tier1-doc-updater (Flash) subagent. Reverse-lookups changed files → concepts via INDEX.json. Applies surgical updates to AUTO-START/AUTO-END sections only. Stages to `$BASE/tier1-staged/<concept>/`. Logs `doc_drift` events for DRIFT_WARNINGS. Non-fatal on failure.
- Finalize step 0: `reconcile-tier1-staged.py` merges all staged updates into live docs, updates INDEX.json, regenerates MEMORIES-FLAT.md. Runs even with partial Tier 1 failures.

**3. Tier 2 narrative docs (manual, significance-gated)** — `scripts/append-tier2-context.py` + `/z-doc-rationale`:
- Context accumulates automatically across pipeline phases via `append-tier2-context.py` (validates per-field schema, supports upsert mode, atomic write)
- Generation fires only when three-signal OR is hit: cross-LLM consult, breaking changes, or plan deviations

**4. Memory authoring (manual)** — `/z-suggest-memory`:
- Append/edit/delete entries in `memories[]` within concept JSONs
- `doc-updater` copies memories verbatim but never mutates them
- Cancel is the default outcome
- Only path for memory mutation

### Dependencies

| Calls | File:line |
|---|---|
| `doc-updater` (Sonnet subagent) | `agents/doc-updater.md:1` |
| `tier1-doc-updater` (Flash subagent) | `agents/tier1-doc-updater.md:1` |
| `consultant-primary` (Gemini, for --audit) | `agents/consultant-primary.md:1` |
| `consultant-secondary` (Codex, for --audit) | `agents/consultant-secondary.md:1` |
| `explore` (Haiku, for --glossary term extraction) | `agents/explore.md` |
| `regenerate-memories-flat.py` | `scripts/regenerate-memories-flat.py:1` |
| `reconcile-tier1-staged.py` | `scripts/reconcile-tier1-staged.py:1` |
| `add-doc-markers.py` | `scripts/add-doc-markers.py:1` |
| `append-tier2-context.py` | `scripts/append-tier2-context.py:1` |

### Called by

| Caller | File:line | Trigger |
|---|---|---|
| `/z-maintain-docs` skill | `skills/z-maintain-docs/SKILL.md` | Manual; recommended after `z-implement-all` and `z-review-all` |
| `/z-implement-all` step 7a.5 | `skills/z-implement-all/SKILL.md:793` | Auto — after each task reviewer passes |
| `/z-implement-all` Finalize step 0 | `skills/z-implement-all/SKILL.md:977` | Auto — reconciliation after all tasks |
| `/z-plan` Phase 8 | `skills/z-plan/SKILL.md:763` | Auto — DOCS: tagging on tasks touching public surfaces |
| `/z-review-all` Phase 6 | `skills/z-review-all/SKILL.md:813` | Manual — push notification recommends `/z-maintain-docs` |
| `/z-suggest-memory` skill | `skills/z-suggest-memory/SKILL.md` | Manual — post-mortems, retros, review-agent proposals |

### Invariants

| Invariant | Evidence | Enforced? |
|---|---|---|
| Human + LLM tiers must stay synced (same entry_points, same dependency graph) | `agents/doc-updater.md` step 3 | assumed — doc-updater produces both in one invocation |
| doc-updater NEVER writes memories; copies existing `memories[]` verbatim | `agents/doc-updater.md` hard rules | yes — enforced by agent spec; z-maintain-docs validates MEMORIES_PRESERVED against baseline |
| Only `/z-suggest-memory` mutates `memories[]` | `agents/doc-updater.md` hard rules | assumed — procedural, not mechanically enforced |
| Tier 1 NEVER writes to `docs/` directly — stages to `tier1-staged/` | `agents/tier1-doc-updater.md` step 3 | assumed — procedural |
| `reconcile-tier1-staged.py` is the ONLY path from staged → live | `scripts/reconcile-tier1-staged.py:1` | yes — single merge script |
| Atomic writes via tmpfile + os.replace | `regenerate-memories-flat.py:124-132`, `reconcile-tier1-staged.py:68-70`, `z-maintain-docs/SKILL.md` Phase 3 stale memory splice | yes — implemented in all write paths |
| Clean concepts auto-applied without prompt | `z-maintain-docs/SKILL.md` Phase 3, `commands/z-maintain-docs.md` hard rules | assumed — procedural |
| Default mode is apply (not dry-run) | `commands/z-maintain-docs.md` Phase 0, hard rules | assumed — procedural |
| `dedup_tags: true` passed to doc-updater by z-maintain-docs | `z-maintain-docs/SKILL.md` Phase 2, `commands/z-maintain-docs.md` Phase 2 | yes — always passed; agent spec defaults to `false` but command overrides |
| Glossary is additive — never removes existing `### <Term>` entries | `commands/z-maintain-docs.md` Phase 1.5, hard rules | assumed — procedural |
| No cron, no scheduled jobs, no timer-driven refresh | grep of entire codebase | yes — zero references |
| Deferred concepts (not_enough_info) never written | `z-maintain-docs/SKILL.md` Phase 3 | assumed — procedural |
| Stale memories never auto-deleted | `z-maintain-docs/SKILL.md` Phase 3, `commands/z-maintain-docs.md` Phase 3 | yes — every removal requires explicit human choice |

### Edge cases

| Case | Handled? | Evidence |
|---|---|---|
| Concept doc missing AUTO-START markers → Tier 1 skips it | yes | `agents/tier1-doc-updater.md` edge cases |
| No concepts match changed files → `STATUS: nothing_to_update` | yes | `agents/tier1-doc-updater.md` edge cases |
| Staging dir already has content for concept → overwrite (latest wins) | yes | `agents/tier1-doc-updater.md` edge cases |
| `not_enough_info` from doc-updater → deferred, never written | yes | `z-maintain-docs/SKILL.md` Phase 3 |
| `MEMORIES_PRESERVED` mismatch → flagged as memories_lost | yes | `z-maintain-docs/SKILL.md` Phase 2/3 |
| Stale memories (>547 days or expired) → surfaced for Keep/Edit/Delete | yes | `z-maintain-docs/SKILL.md` Phase 3; atomic splice for deletes |
| TAG_COLLISIONS from doc-updater → non-blocking advisory report | yes | `z-maintain-docs/SKILL.md` Phase 3 |
| `regenerate-memories-flat.py` called with missing docs/llm/ → exit 1 | yes | `scripts/regenerate-memories-flat.py:38-40` |
| `reconcile-tier1-staged.py` called with no staged content → prints "No staged updates" | yes | `scripts/reconcile-tier1-staged.py:120` |
| Tier 1 reconciliation merge conflict → halt reconciliation, surface conflict | yes | `z-implement-all/SKILL.md:984-985` |
| `--audit` state file exists with matching stale set → fast-forward | yes | `commands/z-maintain-docs.md` Phase 2.3 |
| `--glossary` with no CONTEXT.md → recommend `/z-init-docs`, skip glossary phase | yes | `commands/z-maintain-docs.md` Phase 1.5 |
| `amend_events` field in tier2-context.json not in SCHEMA_SKELETON | not handled | `append-tier2-context.py:16-28` — skeleton doesn't declare it, added dynamically |
| Human doc exists without LLM JSON (or vice versa) | not handled | 6 INDEX.json concepts missing human doc, 2 missing LLM JSON, 20 human docs not in INDEX.json |
| Concepts with `## Key entry points` but no AUTO-START markers | not handled | `capabilities-matrix.md`, `multi-ide-exports.md`, `pi-export.md` — invisible to Tier 1 |
| INVARIANTS.json missing → Phase 1 stale invariant scan skipped silently | yes | `commands/z-maintain-docs.md` Phase 1: `sys.exit(0)` on missing file |

### Config

| Key | Default | Defined at |
|---|---|---|
| `Z_HARNESS_MEMORY_STALE_DAYS` | 547 | `z-maintain-docs/SKILL.md` Phase 3 |
| `Z_HARNESS_TIER1_DRY_RUN` | 0 (unset = apply) | `z-implement-all/SKILL.md:978` |
| `Z_HARNESS_PARALLEL` | 3 | `z-maintain-docs/SKILL.md` Phase 2 |

### Current on-disk state (2026-06-12)

| Metric | Value |
|---|---|
| `docs/human/*.md` files | 48 |
| `docs/llm/*.json` files | 34 (plus INDEX.json, TAGS.txt, MEMORIES-FLAT.md) |
| INDEX.json concepts | 34 |
| AUTO-START markers present | 22 of 48 human docs |
| INDEX.json concepts missing human doc | 6 (`handoff-protocol`, `invariants`, `personas-and-roles`, `plan-layout-migration`, `setup`, `z-reality`) |
| INDEX.json concepts missing LLM JSON | 2 (`handoff-protocol`, `invariants`) |
| Human docs not in INDEX.json | 20 (meta-docs, review artifacts, telemetry, etc.) |
| Total memories across all concepts | 2 (both `pi-export`, both 2026-06-08) |
| MEMORIES-FLAT.md lines | 4 (2 header + 2 memory) |
| Concepts with >0 memories | 1 of 34 |
| tier1-staged/ content | Zero — no pending staged updates anywhere |
| TAGS.txt aliases (section 2) | Empty — no canonical aliases defined |
| INDEX.json freshness | 2 days stale (generated 2026-06-10; git commit `536bfc7` touched docs more recently) |

## Cross-reference results

| # | Source | Plan says | Code does | Clarification | Verdict |
|---|---|---|---|---|---|
| 1 | `append-tier2-context.py:16` SCHEMA_SKELETON | Skeleton declares 12 fields as canonical shape | `amend_events` added dynamically via `setdefault()` at line 164 — not in skeleton | "Bootstrap template, not a schema" | INTENTIONAL — skeleton is for initialization |
| 2 | `z-review-all/SKILL.md:813` | Recommends `/z-maintain-docs` as "recommended next" after review | Push notification only — never auto-invokes | "Review is expensive; doc refresh is separate" | INTENTIONAL — manual trigger by design |
| 3 | `z-plan/SKILL.md:763` | `**DOCS:**` appended to tasks touching public surfaces | Tag is "a hint for /z-maintain-docs; not a rigid task on its own" | "Discoverability aid, not a tracking system" | INTENTIONAL — advisory by design |
| 4 | INDEX.json (34 concepts) vs on-disk docs | Two-tier system should have human + LLM per concept | 6 concepts missing human doc, 2 missing LLM JSON, 20 human docs not in INDEX.json | "INDEX.json tracks concepts, not all docs — meta-docs like INSTALL.md aren't concepts" | INTENTIONAL — INDEX.json is a concept registry |
| 5 | SPEC.md Task T015: marker migration | Wraps `## Key entry points` in AUTO-START/AUTO-END for ALL concept docs | `capabilities-matrix.md`, `multi-ide-exports.md`, `pi-export.md` have `## Key entry points` but no markers (22 of 25 entry-point docs done) | "Marker script hasn't been run on those 3 docs" | DIVERGENCE — missing markers; Tier 1 can't update those 3 concepts |
| 6 | Memory system: `/z-suggest-memory` | Full lifecycle: append/edit/delete memories per concept | 2 memories total (both pi-export, 2026-06-08) | "System is designed but unused — no post-mortems or retros have authored memories" | INTENTIONAL — gated on human decisions |
| 7 | INDEX.json timeliness | Tracks `last_updated` per concept | `generated_at: 2026-06-10` — 2 days stale; git commit `536bfc7` touched docs more recently | "Stale until next `z-maintain-docs` run" | INTENTIONAL — manual refresh cycle |
| 8 | `doc-updater.md` default `dedup_tags: false` vs command always passes `true` | Agent defaults to no dedup; command always enables it | Agent spec: "dedup_tags — true \| false (default false)". Command Phase 2 prompt includes `dedup_tags: true` | "Command always wants collision detection; agent defaults to off for other callers" | INTENTIONAL — command overrides agent default |
| 9 | Command spec (`commands/z-maintain-docs.md`) vs skill spec (`skills/z-maintain-docs/SKILL.md`) | Command and skill should be in sync | Read both in full — identical phase structure, identical code snippets, identical logic. Command adds runtime contract conformance table and RUNTIME-GATE annotations; skill adds operational presentation detail | "Duplicate specs by design — command is canonical, skill is playbook" | INTENTIONAL — z-harness convention |
| 10 | `plans/doc-updater-agent/TASKS.md` — 18 tasks all `[ ]` | Plan says 18 tasks (T001–T018) across 6 phases to implement the doc maintenance system | All deliverables exist on disk: `agents/tier1-doc-updater.md`, `scripts/reconcile-tier1-staged.py`, `scripts/append-tier2-context.py`, `scripts/add-doc-markers.py`, Tier 1 wiring in `z-implement-all/SKILL.md`, Tier 2 wiring in `z-review-all/SKILL.md`, INDEX.json entries for `tier1-doc-updater` and `tier2-doc-rationale`, human docs for both concepts, AUTO-START markers in 22 docs | "Implementation completed but TASKS.md was never updated — tasks still show `[ ]` despite files existing" | DIVERGENCE — stale task tracker; TASKS.md does not reflect reality |

## Verdict

- **Sources of intent cross-referenced:** 5 (agent specs — `doc-updater.md`, `tier1-doc-updater.md`; command spec — `z-maintain-docs.md`; skill specs — `z-maintain-docs/SKILL.md`, `z-implement-all/SKILL.md`, `z-plan/SKILL.md`, `z-review-all/SKILL.md`; script implementations — 4 Python scripts; doc-fetcher synthesis)
- **Intentional divergences:** 8 (skeleton-as-template, manual z-maintain-docs trigger, advisory DOCS: tags, INDEX.json concept scope, empty memories are valid, staleness is manual, dedup_tags command override, command/skill spec duplication)
- **Unintentional divergences (bugs / gaps):** 2
  - Missing AUTO-START markers on 3 entry-point docs (`capabilities-matrix.md`, `multi-ide-exports.md`, `pi-export.md`)
  - `plans/doc-updater-agent/TASKS.md` is stale — all 18 tasks show `[ ]` but deliverables exist on disk
- **Open questions (user deferred):** 0

## Next actions

- [ ] Fix: Run `python3 scripts/add-doc-markers.py` on `capabilities-matrix.md`, `multi-ide-exports.md`, `pi-export.md` so Tier 1 can update them mechanically
- [ ] Explore: Run `/z-maintain-docs --dry-run` to see how many concepts would be refreshed (INDEX.json is 2 days stale, MEMORIES-FLAT.md effectively empty)
- [ ] Fix: Mark completed tasks `[x]` in `plans/doc-updater-agent/TASKS.md` — T001–T017 are implemented and wired; T018 (E2E integration test) is the only unverified task
- [ ] Document: The 6 INDEX.json concepts missing human docs — decide whether to generate human-tier prose or waive
