# Phase 1 — Context

No `docs/llm/INDEX.json` exists in z-harness itself; no RESEARCH.md. Exploration is direct reads of touched plugin files (small contained surface — no Explore subagent needed).

## Surface area to modify

| File | Why |
|------|-----|
| `agents/doc-fetcher.md` | Add second-phase ripgrep over `docs/llm/MEMORIES-FLAT.md` after the existing INDEX.json substring match. Substring fallback when `rg` missing. Cap memory hits at 3 concept slugs. Output stays ≤2 KB. |
| `agents/doc-updater.md` | Extend LLM-tier JSON contract with `memories: []` array. Extend human-tier markdown contract with `## Memories` section. Memory-candidate detection during init/refresh. |
| `skills/z-init-docs/SKILL.md` | Phase 4 — initialize empty `docs/llm/MEMORIES-FLAT.md`. |
| `skills/z-maintain-docs/SKILL.md` | New Phase 4.5 — regenerate `MEMORIES-FLAT.md` from all `docs/llm/<slug>.json` after the apply phase. New staleness flag: memories with `date` older than 18 months → surface in dry-run preview for human review. |
| `skills/z-debug/SKILL.md` | Phase 7 (post-mortem) — mandatory `/z-suggest-memory` call before the action-items prompt. The call may emit zero memories. |
| `skills/z-improve/SKILL.md` | Phase 6/7 — mandatory `/z-suggest-memory` call after accepted-edit application. |
| `skills/z-suggest-memory/SKILL.md` | **NEW.** The skill body — collect candidate memory, target concept slug, validate against schema, write to `docs/llm/<slug>.json`, optionally regenerate MEMORIES-FLAT.md. |
| `commands/z-suggest-memory.md` | **NEW.** Command router pointing to the new skill. |
| `README.md` | Add `/z-suggest-memory` to the skills table. |
| `agents/auditor.md`, `agents/cluster-planner.md`, etc. | Out of scope — no edits. |

## Key contracts that must be preserved

- **doc-fetcher cap:** 8 Reads total, ≤2 KB synthesis output. New ripgrep step is a local subprocess (Bash), not a Read; counts as free against the budget.
- **Two-tier sync (load-bearing):** `docs/llm/<slug>.json` `memories[]` MUST be reflected verbatim (or near-verbatim summary) in `docs/human/<slug>.md`'s `## Memories` section. doc-updater enforces this.
- **Backward compatibility:** existing `docs/llm/<slug>.json` files without `memories` field stay valid. Default `memories: []`. `invariants` and `gotchas` short-string fields preserved.
- **Mandatory /z-suggest-memory in retros:** the *call* is mandatory; the *result* may be zero memories. This is the authoring forcing function.

## Decisions surface (preview for Phase 2)

- Tag taxonomy — controlled set vs free-form? Where defined?
- Memory `type` enum — exact list from BRAINSTORM, but is `open_question` in or out?
- MEMORIES-FLAT.md regeneration cost — every `/z-maintain-docs` run is fine; do we also auto-regen during `/z-suggest-memory`?
- doc-fetcher query for memories — does the caller pass a separate `memory_query` parameter, or reuse the existing `query`? Reuse keeps the contract simple.
- Ripgrep availability — runtime check + substring fallback, or hard requirement?
- 18-month staleness threshold — env-overridable or hardcoded?
- Memory `source` field format — strict prefix taxonomy (`incident:` / `spec:` / `debug:` / `human_review:`) or free-form?
- How does `/z-suggest-memory` resolve the target concept slug from a `/z-debug` post-mortem? (User picks from a list? Inferred from PROBLEM.md's `relevant_concepts`? Both?)
