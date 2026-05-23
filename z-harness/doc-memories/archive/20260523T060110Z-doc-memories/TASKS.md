# TASKS: doc-memories

12 tasks. Phases 1–3 of PLAN.md are sequential (T001 → T002 → T006). T003, T004, T005, T007–T012 parallelize after that.

---

## T001 — Python regen helper

**Files:** `scripts/regenerate-memories-flat.py` (NEW)

**Depends on:** none

**Description:** Implement the shared MEMORIES-FLAT.md regeneration helper per SPEC.md "MEMORIES-FLAT.md regeneration — shared helper" section. Reads every `<repo-root>/docs/llm/*.json` except `INDEX.json`, extracts `memories[]`, emits the line format `[<slug>] [<TYPE> <DATE>] [<source>] <text> (tags: t1, t2)` sorted lex by slug + date desc, writes via tmpfile + `os.replace()`. Header lines preserved. Exit codes 0/1/2. `--dry-run` prints to stdout. No external deps beyond stdlib.

**Acceptance:**
- [ ] `python3 scripts/regenerate-memories-flat.py --repo-root <tmp>` produces a well-formed file when given fixture JSONs.
- [ ] `--dry-run` does not write.
- [ ] Atomic: an in-flight `kill -9` during write leaves the canonical file at its prior state (no truncation).
- [ ] Concept JSONs without `memories` field are treated as empty (skip, no crash).

**Complexity:** low

## T002 — doc-updater contract: `memories[]` + human-tier `## Memories` section

**Files:** `agents/doc-updater.md`

**Depends on:** T001

**Description:** Update doc-updater's documented LLM-tier JSON shape to include `memories: []` field. Update its human-tier markdown template to include the `## Memories` section (after `## Edge cases / gotchas`, before `## Examples`) with the literal HTML "DO NOT EDIT" comment immediately under the heading. Section is omitted entirely when `memories` is empty. Update procedure step 3 to preserve existing `memories[]` verbatim across refreshes — doc-updater never invents memories. Return shape gains `MEMORIES_PRESERVED: <N>` line.

**Acceptance:**
- [ ] doc-updater.md documents the memories field in the LLM JSON shape.
- [ ] Human-tier template includes the section + DO-NOT-EDIT comment.
- [ ] "Never invent memories" hard rule added.
- [ ] Return shape gains MEMORIES_PRESERVED.

**DOCS:** doc-updater
**Complexity:** low

## T003 — doc-updater TAG_COLLISIONS dedup pass

**Files:** `agents/doc-updater.md`

**Depends on:** T002

**Description:** Add procedure step 3.5 — tag dedup pass, invoked when caller passes `dedup_tags: true`. Heuristic: shared prefix ≥4 chars + Levenshtein ≤2. Emit TAG_COLLISIONS block in return per the spec'd JSON shape. Never auto-merge.

**Acceptance:**
- [ ] doc-updater.md documents step 3.5 and TAG_COLLISIONS return.
- [ ] Format matches `[{"concept", "tag_a", "tag_b", "count_a", "count_b"}, ...]` verbatim.

**Complexity:** low

## T004 — z-init-docs: initialize empty MEMORIES-FLAT.md

**Files:** `skills/z-init-docs/SKILL.md`

**Depends on:** T001

**Description:** In Phase 4 (after writing `docs/human/INDEX.md`), shell out to `python3 scripts/regenerate-memories-flat.py --repo-root <root>` to create the file with just the header lines (no memories exist at init). Phase 6 summary mentions the new file.

**Acceptance:**
- [ ] Phase 4 invokes the helper.
- [ ] Phase 6 summary lists `docs/llm/MEMORIES-FLAT.md`.

**Complexity:** medium

## T005 — z-maintain-docs: Phase 4.5 regen + Phase 3 stale UX

**Files:** `skills/z-maintain-docs/SKILL.md`

**Depends on:** T001, T002

**Description:**
- Insert Phase 4.5 (after Phase 4 Apply): unconditional `python3 scripts/regenerate-memories-flat.py` invocation.
- Phase 3 (Present diffs) gains **Stale memories** section listing memories where `expires < today` OR `date < today - $Z_HARNESS_MEMORY_STALE_DAYS` (default 547). Per-entry inline AskUserQuestion: **Keep** / **Edit** (handoff to `/z-suggest-memory --edit <concept> <index>`) / **Delete** (splice + regen).
- Phase 3 also surfaces TAG_COLLISIONS from T003's doc-updater return.
- Log `memory_deleted` event on every delete.

**Acceptance:**
- [ ] Phase 4.5 documented.
- [ ] Phase 3 stale-memories UX documented including Keep/Edit/Delete and the memory_deleted event.
- [ ] TAG_COLLISIONS surfaced.

**Complexity:** medium

## T006 — doc-fetcher: ripgrep second-phase + tags + fallback + memory synthesis

**Files:** `agents/doc-fetcher.md`

**Depends on:** T001, T002

**Description:**
- Add optional `tags` input (kebab-case list; validated against the controlled seed set + free-form; unknown tags drop with `unknown_tag` log).
- Insert step 2.5 between step 2 (pick concepts from INDEX.json) and step 3 (read per-concept JSONs): ripgrep over `docs/llm/MEMORIES-FLAT.md`. Build query regex from sanitized tokens plus optional tag constraints. On exit 127 (rg missing), fall back to Python `\b`-bounded substring scan preserving file order. Cap merged slugs at 3.
- Concept synthesis gains a `**Memories:**` subsection (max 3 per concept, highest-date-first), with truncation to ≤120 chars + `…` when total synthesis would exceed 1500 bytes. Emit `synthesis_truncated` log line. Structural content never truncated.
- Hard rules updated: ripgrep is soft dep.

**Acceptance:**
- [ ] Step 2.5 documented.
- [ ] Fallback uses `\b` word boundaries.
- [ ] Truncation rule explicit.
- [ ] `unknown_tag` and `rg_missing_fallback` log lines documented.
- [ ] Existing 8-Read / 2-KB cap preserved.

**DOCS:** doc-fetcher
**Complexity:** high

## T007 — /z-suggest-memory skill

**Files:** `skills/z-suggest-memory/SKILL.md` (NEW)

**Depends on:** T001, T002, T006

**Description:** Implement the skill body per SPEC.md `/z-suggest-memory` section: preflight (no-docs guard), resolve-target (concept_hints + create-new-concept stub-write + Cancel-as-default), collect (type chips + text validation + tags chips + source resolution), validate (schema + length + regex), write (three mutually-exclusive modes: append default / `--edit <slug> <index>` / `--delete <slug> <index>`), regen via T001 helper, optional human-tier refresh via doc-updater. Hard rules: one mutation per invocation, no newlines/emojis in text, reject text >200 chars. Return shape includes STATUS / CONCEPT / MEMORIES_WRITTEN / WROTE list.

**Acceptance:**
- [ ] All four AskUserQuestion options for target resolution.
- [ ] Create-new-concept writes minimal stubs + adds INDEX.json entry (`confidence: low`).
- [ ] Append/edit/delete modes mutually exclusive.
- [ ] `--dry-run` skips write in all modes.
- [ ] STATUS / CONCEPT / MEMORIES_WRITTEN / WROTE return shape.

**Complexity:** medium

## T008 — commands/z-suggest-memory.md router

**Files:** `commands/z-suggest-memory.md` (NEW)

**Depends on:** T007

**Description:** Thin command router mirroring `commands/z-brainstorm.md` shape — invokes the skill, passes argv through. No business logic.

**Acceptance:**
- [ ] File present, command-name front-matter correct.
- [ ] Forwards args to the skill.

**Complexity:** low

## T009 — z-debug Phase 7 hook + PROBLEM.md template

**Files:** `skills/z-debug/SKILL.md`

**Depends on:** T007

**Description:**
- Insert mandatory `/z-suggest-memory` invocation in Phase 7 (post-mortem), **after** POSTMORTEM.md is written but **before** the action-items AskUserQuestion. `concept_hints` derived from POSTMORTEM.md "Root cause" Doc-gap mention + PROBLEM.md `Relevant concepts:` line.
- Update PROBLEM.md template (Phase 1) to include a `Relevant concepts: <slug>, <slug>` line.
- Add salience guidance: "**Default to Cancel** unless a genuinely novel anti-pattern / abandoned path / decision rationale surfaced during root-cause investigation. Cancel is a first-class outcome."
- Log `suggest_memory_called` event with `{memories_written, concept}`.

**Acceptance:**
- [ ] Phase 7 hook documented, salience guidance prominent.
- [ ] PROBLEM.md template includes Relevant concepts line.
- [ ] Event logged.

**Complexity:** medium

## T010 — z-improve Phase 7 hook

**Files:** `skills/z-improve/SKILL.md`

**Depends on:** T007

**Description:** Insert mandatory `/z-suggest-memory` invocation at the end of Phase 7 (apply accepted edits), after diffs are written. `concept_hints` derived from touched z-harness file paths. Same salience guidance as T009 (default to Cancel). Log `suggest_memory_called`.

**Acceptance:**
- [ ] Phase 7 hook documented.
- [ ] Salience guidance present.
- [ ] Event logged.

**Complexity:** low

## T011 — Test fixtures + 7 unit tests

**Files:** `z-harness/doc-memories/test-fixtures/` (NEW), `z-harness/doc-memories/tests/` (NEW)

**Depends on:** T001, T002, T006, T007

**Description:** Create synthetic INDEX.json + 3 concept JSONs (one with memories, one without, one with regex-adversarial slug `weird-[brackets]`) + a golden MEMORIES-FLAT.md. Add bash-driven tests (no pytest dependency) covering:

1. doc-updater fixture: feed concept JSON with 3 memories → assert refresh round-trips them and human markdown contains the `## Memories` block with DO-NOT-EDIT comment.
2. doc-fetcher fixture: query "stale spreads" → assert ripgrep step returns the expected slug.
3. doc-fetcher ripgrep-missing fallback: invoke via `env -i PATH=/usr/bin` → assert substring fallback returns the same slug.
4. /z-suggest-memory schema rejection: text >200 chars → STATUS: bad_input, no write.
5. MEMORIES-FLAT.md format golden-file.
6. **Adversarial regex.** Slugs `weird-[brackets]`, text with `* \ $`, unicode tags → both ripgrep and fallback return correct results without crash.
7. **Concurrent regen.** Two `regenerate-memories-flat.py &` in parallel → assert resulting file well-formed (either run's full output, never partial).

**Acceptance:**
- [ ] All 7 tests present and pass under `bash z-harness/doc-memories/tests/run-all.sh`.
- [ ] No network, no external services.

**Complexity:** medium

## T012 — README.md + cross-references

**Files:** `README.md`, `agents/doc-fetcher.md`, `agents/doc-updater.md`

**Depends on:** T006, T007, T008

**Description:** Add `/z-suggest-memory` row to the skills table in README.md with one-line description. Add cross-references in `agents/doc-fetcher.md` (point to /z-suggest-memory as the authoring path) and `agents/doc-updater.md` (point to /z-suggest-memory as the only memory-mutating path).

**Acceptance:**
- [ ] README skills table includes /z-suggest-memory.
- [ ] doc-fetcher.md + doc-updater.md mention /z-suggest-memory by name.

**Complexity:** low
