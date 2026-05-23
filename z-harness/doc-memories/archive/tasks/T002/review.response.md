# Codex Review: T002

(Note: Codex CLI unavailable in environment; review performed via static analysis)

## Acceptance Criteria Review

1. **doc-updater.md documents memories field in LLM JSON shape**
   - ✓ `"memories": []` added to JSON schema template (line 88)
   - ✓ Explanation: "`memories` defaults to `[]`. When the existing LLM-tier doc has a non-empty `memories[]`, those entries MUST be copied verbatim..." (post-schema)

2. **Human-tier template includes the section + DO-NOT-EDIT comment**
   - ✓ `## Memories` section added between Edge cases and Examples (line 60-66)
   - ✓ DO-NOT-EDIT comment present: "<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/<slug>.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->"
   - ✓ Format example provided with `<DATE> <TYPE>` markup and tags

3. **"Never invent memories" hard rule added**
   - ✓ New hard rule line 125: "**NEVER invent memories.** doc-updater is a structural refresh agent, not a memory authoring agent. Existing `memories[]` entries are copied verbatim; no new entries are created. All memory authoring goes through `/z-suggest-memory`."

4. **Return shape gains MEMORIES_PRESERVED**
   - ✓ Added to return template (line 102): `MEMORIES_PRESERVED: <N>`

## Spec Alignment

All four acceptance criteria met. The changes implement exactly what was requested in the task.

The spec mentions step 3.5 (TAG_COLLISIONS / dedup pass), but that is explicitly scoped to T003 per the spec ("T003 will extend with TAG_COLLISIONS"). T002 does not include it in its acceptance criteria, so its absence is correct.

## Static Analysis

No blockers or majors found:
- Memory preservation logic is clearly documented
- Comment structure prevents human overwrites
- Hard rule emphasizes non-authoring scope
- Return shape is specified unambiguously
- Human and LLM tier contracts stay in sync

No edge cases missed for T002 scope. The "omit section when memories: []" caveat is documented. The "copy verbatim" semantics are explicit.

