**Findings**

1. [commands/z-debug.md:202](</Users/zeke/dev/z-harness/commands/z-debug.md:202>) - Round 2 NEW-row dedup only checks against the existing pool, not against other NEW rows returned by Codex/Gemini. The acceptance criterion says to “drop dup NEW rows”; as written, if both consultants surface the same missing failure mode, it can be appended twice with two `H<NNN>` IDs. This also corrupts `overlap_count` / `proposed_by` for Round 2 additions.

2. [commands/z-debug.md:214](</Users/zeke/dev/z-harness/commands/z-debug.md:214>) - Duplicate critique handling says to “sum `overlap_count`”. That can produce impossible values above 3, while Phase 4 defines overlap as `1-3` and maps only `3→high, 2→med, 1→low` at [commands/z-debug.md:225](</Users/zeke/dev/z-harness/commands/z-debug.md:225>). Merge should recompute `overlap_count` from the union of unique `proposed_by` models, capped by the three Round-1 sources, rather than blindly summing.

3. [commands/z-debug.md:191](</Users/zeke/dev/z-harness/commands/z-debug.md:191>) - The Round 2 dispatch prompt asks for “two markdown tables” but does not specify the locked NEW/CRITIQUES column schemas, `critique_type` enum, `orthogonality_to`, `merge_with_id` rule, or `schema_version`. The consultant agent files contain this contract, but the `/z-debug` command itself is supposed to be the orchestration source and the task plan calls out “Round 2 table schemas” for this file. This makes malformed consultant output more likely and weakens the post-process filters.

**Residual Risk**

I did not find violations of the big artifact rewrite: `DEBUG.md` is unified, Phase 0 exists, EVID/H IDs are covered, posterior table matches the spec text I found, fix-gate and mandatory post-mortem are present, and the old `>5 files` auto-bail trigger is dropped.
