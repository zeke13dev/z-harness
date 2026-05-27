# PLAN — askuser-prefs-hook

## Goal

Ship a pre-AskUserQuestion preference resolver + a human-in-the-loop elevation proposer so repeated routing-class user prompts get progressively reduced. v1 covers two patterns (~9 sites): `workflow.audit_to_amend` (the user's named "almost always amend after audit" case) and `workflow.slug_confirm` (the highest-pattern-count leverage site).

## Decisions (with rationale)

See [phase3-decisions-final.md](archive/20260527T212839Z-askuser-prefs-hook/phase3-decisions-final.md). Headline:

- **D1** — Resolver lives in `scripts/config.py resolve-question`. Reuses 4-layer precedence. Strict stdout JSON discipline.
- **D2** — `[workflow]` TOML section, **underscore-only** keys (`workflow.audit_to_amend`, `workflow.slug_confirm`). Codex correctly flagged the existing `_KEY_RE` rejects hyphens; SPEC adopts underscores.
- **D3** — Memory schema: new `type: "routing-preference"` with `{question_id, value, scope, strength, reason, date}`. Resolver parses `docs/llm/*.json` directly (NOT MEMORIES-FLAT.md — Gemini correctly flagged grep-on-derived-artifact is brittle).
- **D5** — Return contract: full JSON envelope `{result, default, source, rule_id, strength, reason, sources[]}`. Exit codes 0/2/3/4.
- **D7** — Explicit `strength` field on memory entries, picked at write-time. Full 5-tier resolver per Path X (user's pick).
- **Single QUESTION_IDS registry** in `config.py` is the source of truth for: config validation, /z-suggest-memory write validation, resolver lookup. Codex's recommendation.
- **Elevation proposer** (added Phase 4 user expansion): `scripts/propose-prefs.py` walks `metrics.jsonl` for repeated command-pair patterns; at threshold offers AskUserQuestion to elevate to config or memory.

## Non-goals

- Auto-pinning `/z-amend` slug from audit context (separate plumbing).
- Halt-class bypass.
- Multi-IDE export precheck (Cursor/Codex/agy).
- Memory-strength inference from text (always explicit).
- Retrofitting all 30 distinct AskUserQuestion patterns. v1 is exactly two.

## Approved shortcuts

**None.** User explicitly picked Path X (full 5-tier) over the Codex-trimmed alternative at Phase 5. The plan ships the full memory-skip resolver, not memory-prefill-only.

## Phase 7 review amendments (post-consult fixes baked into SPEC)

Both Gemini and Codex reviewed the full SPEC+PLAN. The following amendments were applied to SPEC.md before TASKS generation:

1. **G CRIT #1** — `workflow.slug_confirm` value-domain renamed (`auto_accept`/`recommend_derived`/`ask`) to avoid colliding with resolver result-domain. Added explicit `RESULT_MAP` table for question_id-specific value→result translation.
2. **G CRIT #2** — Removed slug-confirm auto-proposal pattern from v1 (metrics.jsonl doesn't record AskUser responses). Slug-confirm pref is still settable manually via `config.py set` or `/z-suggest-memory --kind routing-preference`. v2 prerequisite: AskUser-response telemetry.
3. **G CRIT #3** — Slug-confirm retrofit split from audit-amend retrofit. Slug-confirm sites have TWO gates: hard collision check (always runs) + soft non-obvious-slug confirmation (resolver-controlled). SPEC spells this out.
4. **G MAJOR #4** — Retrofit prose captures exit code separately and never silences stderr. Error fallback always sends user to `ask`.
5. **G MAJOR #5** — Conflict-tier UX includes a follow-up write-back AskUserQuestion ("record your answer as new pref?") to prevent the conflict from persisting on every subsequent run.
6. **C CRIT #2** — Startup guard validates `RESULT_MAP` values are subset of `QUESTION_IDS[qid]["choices"]`. Catches stale registry entries at module load.
7. **C MAJOR #3** — Exit code 4 explicitly handled in retrofit prose (fall through to ask).
8. **C MAJOR #4** — Proposer suppression file scoped to `(project_root, question_id)`, not global.

**Deferred to v2 (documented in SPEC §"Known v2 hygiene items"):** Codex CRIT #1 (stale-memory hygiene), MAJOR #5 (dry-run/rollback), MAJOR #6 (async memory-write telemetry honesty), MINOR #7 (tier-naming asymmetry), MINOR #8 (memory schema_version).

## Phases

### Phase A — Resolver core (D1, D2, D5)
Extend `scripts/config.py`:
- Add `[workflow]` to `DEFAULTS`/`VALIDATORS`.
- Add `QUESTION_IDS` registry + startup assertion.
- Implement `resolve-question` subcommand: parse args, consult config (4-layer), consult memories (JSON walk), apply tier-mapping rules from SPEC §`scripts/config.py:resolve-question`, emit JSON to stdout.
- Add `set` subcommand for atomic config writes.
- Stdout-discipline test: `python3 -m json.tool` validator over the resolver output.
- Honor `Z_HARNESS_ASK_ALL=1` and `Z_HARNESS_EXPLAIN_RESOLUTION=1`.

### Phase B — Memory routing-preference schema (D3, D7)
- Extend `skills/z-suggest-memory/SKILL.md`:
  - Add Phase 3a detection of routing-flavored candidate text → one-shot AskUserQuestion redirect.
  - Add `--kind routing-preference` flow with `--question-id`, `--value`, `--strength`, `--scope` flags. Validates against `QUESTION_IDS` registry via `python3 scripts/config.py list-question-ids`.
  - Write target: `docs/llm/workflow.json` (or per-slug if scope=project — slug = `workflow-<project-slug>`).
- Implement the JSON memory walk in the resolver (Phase A consumes this schema).

### Phase C — Skill prose retrofits (D6, D10)
Update each of the 9 callsites per SPEC §retrofit. Pattern is identical (resolver call → branch on result). Two flavors:
- Audit→amend (2 sites: z-audit-plan.md, z-audit-plan-style.md).
- Slug-confirm (7 sites: z-plan.md, z-fix.md, z-debug/SKILL.md, z-brainstorm/SKILL.md, z-research/SKILL.md, z-plan-light/SKILL.md, z-uplift.md).
- Spell out the collision-check survives-skip invariant in the slug-confirm sites.

### Phase D — Elevation proposer (user's Phase 4 expansion)
- `scripts/propose-prefs.py`: pattern detection from `metrics.jsonl`. Hardcoded watched patterns in v1.
- Retrofit Phase 9/finalize of `z-audit-plan.md`, `z-audit-plan-style.md`, `z-amend.md` to call the proposer and surface the one-shot AskUserQuestion if a proposal lands.
- Suppression file at `~/.config/z-harness/.propose-suppress`. 30-day expiry per question_id.
- Configurable thresholds via env (`Z_HARNESS_PROPOSE_WINDOW_S`, `Z_HARNESS_PROPOSE_THRESHOLD`).

### Phase E — Stats consumer
- `skills/z-stats/SKILL.md` Phase 4c: read `askuser_resolved` events from metrics.jsonl. Aggregate by result/source/question_id. Conflict-rate as proxy for user surprise. Read-only.

### Phase F — Docs (D12)
- Update `docs/human/config.md` + `docs/llm/config.json`: `[workflow]` section, `resolve-question`, `set`, env overrides.
- Document `routing-preference` memory type in the same concept (or in commands/skills if more natural).
- Note the v2 deferrals: multi-IDE, halt-class bypass.

### Phase G — Verification
- End-to-end smoke test: set `workflow.audit_to_amend = "amend"` in `.z-harness/config.toml`. Run `/z-audit-plan`. Confirm Phase 5 skips its AskUserQuestion and proceeds as "amend". Confirm `askuser_resolved` event emitted with `source: config`.
- Conflict-tier test: set config = "amend", write memory routing-preference for same question_id with value = "stop". Run `/z-audit-plan`. Confirm Phase 5 surfaces the AskUser with sources clearly listed.
- Elevation-proposer test: simulate 3 runs of `/z-audit-plan → /z-amend` in metrics.jsonl; run `propose-prefs.py --check z-audit-plan`. Confirm proposal returned with the right question_id and `proposed_value: "amend"`.
- /z-suggest-memory routing-preference write test: invoke with `--kind routing-preference --question-id workflow.audit_to_amend --value amend --strength very_strong`. Confirm memory lands in `docs/llm/workflow.json` with the right shape, MEMORIES-FLAT.md is regenerated.

## Phase ordering and dependencies

```
A (resolver core) ─┐
                   ├─→ C (retrofits) ─→ G (verify)
B (memory schema) ─┘
                   ├─→ D (proposer)
A + telemetry ─────┘
                   ├─→ E (stats)
                   ├─→ F (docs)
```

A and B parallel where they don't touch the same file. C depends on both. D depends on A (uses config.py for proposed-value validation). E depends on A's telemetry emission. F can lag (defer to /z-maintain-docs).

## DRY / KISS / SOLID

- **DRY:** Single `QUESTION_IDS` registry. Single resolver entry. Single shared retrofit pattern across all 9 sites. Single memory-schema definition.
- **KISS:** v1 has exactly 2 question_ids. JSON return envelope is flat. Memory schema is 6 fields. No fancy strength inference, no fancy conflict-resolution policy (just "ask, show both").
- **SOLID:** Resolver owns "should we ask?"; collision/safety checks stay in skill prose. Proposer owns "is the pattern worth elevating?"; the write itself is delegated to `config.py set` or `/z-suggest-memory`. `/z-suggest-memory` owns all memory mutations. /z-stats owns aggregation.

## Risk register (carried from consult + premise)

| Risk | Mitigation | Where addressed |
|---|---|---|
| Stdout JSON pollution from debug prints in config.py | Strict stderr-routing for all non-JSON; jq.json test gate | SPEC §`scripts/config.py:resolve-question` |
| question_id typos silently degrade to "none" tier | Single QUESTION_IDS registry; /z-suggest-memory validates against it | SPEC §registry |
| User confusion when config overrides memory | `conflict` tier always asks + shows sources; `--explain` flag | SPEC §resolver tier-mapping |
| Slug-confirm skip bypasses collision check | Retrofit prose makes collision check survive skip explicitly | SPEC §retrofit; invariants |
| Proposer fires for unrelated repeated runs | Group by command-pair + same slug + consistent user choice | SPEC §propose-prefs |
| Resolver fails on missing memory dir | Treat as "no memory match"; no crash | SPEC §edge cases |
| Memory-flat regen lag | /z-suggest-memory already handles regen; routing-preference write reuses path | SPEC §B |
