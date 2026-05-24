## Codex review: task T005

### Blockers

1. **Phase 3 Delete vs Phase 4.5 regeneration conflict** (lines 129, 162-173): Phase 3 Delete explicitly calls regenerate-memories-flat.py inline, but Phase 4.5 says it "unconditionally" regenerates and runs "whenever a memory was deleted during Phase 3." This creates ambiguity: does regenerate-memories-flat.py run twice (redundant), or should Phase 3 skip it and defer to Phase 4.5? The phrase "This step runs in both --apply mode and whenever a memory was deleted" suggests Phase 4.5 is the sole regeneration point, making Phase 3's inline regenerate call incorrect.

2. **dedup_tags parameter not passed in Phase 2** (lines 141-150 vs Phase 2 Agent call): The new TAG_COLLISIONS section expects doc-updater to be invoked "with dedup_tags: true" from Phase 2, but Phase 2's Agent() call specification (line 47) never mentions the dedup_tags parameter. This is a contract gap: either Phase 2 must be updated to conditionally pass dedup_tags, or TAG_COLLISIONS is documenting behavior that won't occur.

### Major

1. **Error handling for memory splice incomplete** (line 129): When a user selects Delete, the spec says to "splice out memories[index]" with "atomic write" but provides no details on error handling if the JSON write fails after splicing. The regenerate-memories-flat.py call happens after, so if splicing corrupts the JSON, regenerate will fail but the memory is already deleted; consider wrapping the splice-and-regenerate in a transaction-like check.

No other blockers or majors found. Note: text_preview extraction (first 60 chars) should escape JSON-unsafe characters (newlines, quotes) before logging, but this is a minor implementation detail.
