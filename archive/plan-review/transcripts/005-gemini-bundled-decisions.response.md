Loaded cached credentials.
### D1. Memory JSON schema
1. **Failure Mode:** Adding an `expires` date introduces a garbage collection problem. Without an active pruning process, expired memories will still appear in `ripgrep` results (unless the regex dynamically filters by date, which is brittle), leading to user confusion and polluting the LLM context. 
2. **Interaction:** Interacts with **D3 (MEMORIES-FLAT.md line format)**. If `expires` is included in the schema, it must be injected into the self-contained string format, further complicating the line structure.
3. **Recommendation:** **(a) Codex shape verbatim**. Keep it simple. Since memories are mutable, humans or agents can manually delete or update them if they become stale. Avoid building auto-expiring logic for a V1 blind ship.

### D2. Tag taxonomy
1. **Failure Mode:** CLI prompts for "hybrid" tagging often degrade. Agents or users will invent ad-hoc tags (`perf`, `performance`, `speed`, `fast`), causing tag fragmentation.
2. **Interaction:** Strongly interacts with **D4 (doc-fetcher contract)**. If tags are fragmented, offering a `tags` parameter to `doc-fetcher` will result in frequent zero-match returns because the agent guessed the wrong synonym.
3. **Recommendation:** **(a) Controlled set**. Strict enums are safer for blind shipping and ensure `ripgrep` predictability. You can easily expand the allowed list later, but you cannot easily un-fragment a messy taxonomy.

### D3. MEMORIES-FLAT.md line format
1. **Failure Mode:** The tentative format `[<slug>] [<TYPE> <DATE>] <text> (tags: ...)` drops the `source` field defined in D1. If `source` isn't serialized into the flat file, `ripgrep` results lose critical context (e.g., whether this memory came from a catastrophic `incident` or a casual `human_review`).
2. **Interaction:** Interacts directly with **D1 (Schema)**. The flat file must be a lossless (or near-lossless) string representation of the JSON fields.
3. **Recommendation:** **Modify (d)** to explicitly include the source: `[<slug>] [<TYPE>] [<DATE>] [<source>] <text> (tags: ...)`. Self-contained lines are still the correct architectural choice for the grep phase, but they must contain all high-signal metadata.

### D4. doc-fetcher second-phase contract
1. **Failure Mode:** If `doc-fetcher` exposes a specific `tags` parameter, LLMs will inevitably hallucinate tags to search for, over-constrain the query, get zero results, and falsely assume no memories exist for a concept.
2. **Interaction:** Interacts with **D2 (Tag taxonomy)** and **D3 (Line format)**. Search effectiveness relies entirely on the predictability of the flat file schema.
3. **Recommendation:** **(b) Add optional `memory_query` parameter.** Keep the standard lexical/semantic `query` separate from the memory grep phase. A dedicated `memory_query` allows the agent to pass a raw `ripgrep` pattern to search across text, tags, or types flexibly, without the brittleness of a strict structured `tags` field.

### D5. /z-suggest-memory target-concept resolution
1. **Failure Mode:** The user is diagnosing a systemic issue that spans multiple concepts or doesn't fit into any existing `slug`. If the multi-select strictly binds to existing concepts, the user is forced to miscategorize the memory or abandon authoring it.
2. **Interaction:** Interacts with **D3 (MEMORIES-FLAT.md line format)**, which requires a valid `[<slug>]` prefix to function.
3. **Recommendation:** **(d) with an escape hatch**. Pre-selecting `concept_hints` is the best UX, but the multi-select MUST include an explicit `"GLOBAL" / "Create New Concept"` option to handle cross-cutting memories or net-new architectural discoveries.
