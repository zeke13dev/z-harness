# Fix: config-concept-merge

**Run:** 20260527T235100Z-config-concept-merge
**Status:** shipped
**Plugin version:** non-git

## Problem

docs/llm/INDEX.json registers two concepts (`config-design`, slice-1 4-layer loader; `config`, slice-2 workflow resolver) that both cover scripts/config.py + docs/human/config.md. doc-fetcher's source_file containment matching fires on both when the file is touched, returning duplicate synthesis blocks. BRAINSTORM (chosen_framing: claude) picked merging into one concept.

## Root cause

The split was implementation-slice-based (when each piece was written), not query-surface-based (what a doc-fetcher caller wants to know). The two concepts answer coupled questions; the split is artificial.

## Approach

Merge `config-design` into `config`. The merged concept lives at `docs/llm/config.json` + `docs/human/config.md`. Internal structure uses named section headers (`## Loader API` for slice-1 fundamentals; `## Workflow Resolver` for slice-2 additions). All metadata from config-design (entry_points, invariants, gotchas) folds into config. Cross-references in other concept files get updated from `config-design` → `config`.

## Files to change

1. `docs/llm/config.json` — fold in config-design's `entry_points[]`, `invariants[]`, `gotchas[]`, expand `source_file` to union (incl. scripts/config.sh), rewrite summary to mention both surfaces
2. `docs/llm/INDEX.json` — remove `config-design` entry; union source_file in `config` entry; bump `last_updated`
3. `docs/llm/config-design.json` — **delete**
4. `docs/human/config-design.md` — **delete** (fold any unique prose into config.md first)
5. `docs/human/config.md` — add `## Loader API` and `## Workflow Resolver` top-level section headers; absorb any unique content from config-design.md
6. `docs/llm/commands.json` — rename `config-design` → `config` in depends_on
7. `docs/llm/scripts.json` — rename `config-design` → `config` in consumed_by (or depends_on)
8. `docs/llm/z-fix.json` — rename `config-design` → `config` in depends_on
9. `docs/human/commands.md` — rewrite prose mentions of `config-design` → `config` (or just drop the qualifier if context-clear)
10. `docs/human/scripts.md` — same
11. `docs/human/z-fix.md` — same

11 files but they're a single coherent rename. Light-mode appropriate (no code, no risk).

## Acceptance

- [x] docs/llm/config-design.json and docs/human/config-design.md no longer exist
- [x] grep `config-design` across docs/ returns zero hits except in archived BRAINSTORM/SPEC files
- [x] docs/llm/INDEX.json validates (`python3 -m json.tool`) and contains no `config-design` slug entry
- [x] docs/llm/config.json validates and includes the merged metadata (entry_points/invariants/gotchas from both)
- [~] docs/human/config.md boundary documented (Overview rewrite explicitly names both surfaces + historical merge note); deferred the deeper restructure of 14 interleaved sections into two top-level groupings as a follow-up to keep this in light-mode scope
- [x] No dangling depends_on or consumed_by references to `config-design`
- [x] Codex review of cumulative diff passes (no blockers/majors)

## Cross-LLM consensus

- Gemini: validate plan with 3 expansions — merge entry_points/invariants/gotchas (not just summary), update markdown prose mentions, include config.sh in source_file. Plan otherwise sound.
- Codex: hung on permission prompt during BRAINSTORM Phase 2; not re-dispatched.
- Synthesized call: accept Gemini's 3 expansions verbatim. All findings are mechanical and obvious-in-hindsight. The expanded scope (11 files vs initial 3-4) doesn't change the risk profile — still doc-only.

## Approved shortcuts

None. Single-consultant flow is a known session-level oddity (Codex hung), not a shortcut.

## Docs touched

- `config` (this is the merge target; `/z-maintain-docs` will see config.json updated)
- `commands`, `scripts`, `z-fix` (each loses a depends_on reference)

After this fix lands, optionally run `/z-maintain-docs --audit --scope=config` to verify the merged shape is well-formed.
