## 1. Framing

The codebase itself is the source of truth for the *current state*, but it suffers from survivor bias—it only shows what worked, not what failed. Institutional memory (anti-patterns, abandoned paths, incident context) is currently lost between sessions or buried in git history. The goal is to persist this "dark matter" of software engineering in a way that is instantly accessible to an orchestrator *before* it begins planning or exploring, preventing it from repeating historical mistakes. The lookup mechanism must be zero-latency and highly deterministic to serve as a viable precursor to `Explore`.

## 2. Core hypothesis

**Memories must be an append-only ledger, and search must be a flat, compiled text artifact.**
Instead of allowing LLMs to mutate and potentially degrade "gotchas" through repeated summarization, memories should be an append-only array of timestamped, immutable events (e.g., `[{ "date": "...", "type": "abandoned-path", "content": "..." }]`) attached to a concept. To solve the lookup problem without the operational complexity of vector databases, we should compile `INDEX.json` and all concept memories into a single, highly structured, flat text file (`SEARCH_INDEX.txt`). `doc-fetcher` is then upgraded to use `ripgrep` over this flat file, turning semantic discovery into a blindingly fast, regex-friendly filtering operation before it ever needs to parse a JSON file.

## 3. Risks

*   **Context Bloat:** Append-only ledgers grow indefinitely. Without an eviction, decay, or compaction strategy, `doc-fetcher` will easily breach its 2 KB synthesis cap when summarizing concepts with long, fraught histories.
*   **Ripgrep Noise:** A flat text index is prone to false positives. Searching for a generic term might yield dozens of hits across historical memories, confusing `doc-fetcher` about which concepts are actually architecturally relevant *now*.
*   **The "Two Brains" Problem:** If rich memories only live in the `docs/llm/` tier, human engineers will never see them, leading to a divergence where human developers repeat mistakes that the AI already "knows" to avoid.

## 4. Plan implications

*   **Schema Update:** Deprecate the simple `invariants` and `gotchas` strings. Introduce a `memories` array within the concept JSON, enforcing fields for `date`, `provenance` (e.g., run-id, incident, or human-authored), `type` (e.g., `anti-pattern`, `decision`, `abandoned-path`), and `content`.
*   **Index Compilation:** Add a post-processing step to the doc-updater that flattens the concept JSONs into `docs/llm/SEARCH_INDEX.txt`, formatting entries specifically for `grep` (e.g., `[CONCEPT: <slug>] [TAGS: ...] [MEMORY: ...]`).
*   **Agent Modification:** Rewrite `doc-fetcher`'s retrieval contract. Instead of reading `INDEX.json` and doing substring matches, it executes a `grep_search` against the flat text index, extracts the relevant concept slugs from the matched lines, and *then* reads the targeted JSON files.
*   **Authoring Workflow:** Hook `/z-debug` and `/z-improve` to automatically append a memory to relevant concepts upon successful completion, ensuring the system organically learns from its own runtime operations.

## 5. What would change my mind

If empirical testing shows that `ripgrep` against a compiled text file requires overly complex regexes to filter out noise, or if the sheer volume of "abandoned paths" makes keyword matching useless compared to the semantic accuracy of a cheap embedding search. Additionally, if the cost and latency of passing a massive `INDEX.json` directly to Haiku drops to near-zero, building a custom flat-file reverse index might be an unnecessary optimization.
