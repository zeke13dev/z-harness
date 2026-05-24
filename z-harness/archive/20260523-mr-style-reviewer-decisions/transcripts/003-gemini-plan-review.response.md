Error executing tool list_directory: Error: Failed to list directory.
Here is a critique of the SPEC and PLAN, directly addressing your questions and highlighting what needs to be fixed before implementation.

### 1. Agent input contract gaps
- **Missing frontmatter variables:** The SPEC requires `base` and `diff_stat` in the `MR-REVIEW.md` output frontmatter, but these are **missing from the `mr-reviewer` input contract** (SPEC lines 156-176). The orchestrator must pass them.
- **Format ambiguity:** Is `recent_archives` passed as a JSON array string or a comma-separated list? If `diff_path` is chunked, does it become a directory path? The prompt contract needs exact string formats.

### 2. Fragile or under-defined mechanics
- **Chunking vs. Abstraction Pass (D12):** This is highly fragile. If the orchestrator passes a chunked directory, how does the agent process it? If the agent loops over chunks and runs the abstraction pass (Grep/Glob) *per chunk*, it will do massive, redundant whole-repo searches. The abstraction pass must be deferred until chunk findings are merged, or chunking needs a clearer fan-out/reduce architecture.
- **Deduplication Signature:** `(file, line-range, category, normalized-text)` is extremely fragile. `line-range` breaks immediately upon any file edit. Change the signature to `(file, category, normalized-text)`.
- **Dismissal Tagging:** Demoting by exactly one tier (`P0` → `P1`) means a stubbornly dismissed finding never drops off the radar (it just stays P1 forever). You need progressive decay (e.g., `demote by $N$ tiers` where $N$ is the number of historical dismissals) so it eventually falls to P4 or is dropped.

### 3. Ordered phases (1–12)
- **Phase 3 before 4 is backwards:** The orchestrator (Phase 4) handles complex data prep: diff generation, byte-size chunking logic, and archive resolution. If you build the agent (Phase 3) first, you are guessing the shape of the chunked diff directory and the archive list format. The orchestrator should be built (or at least stubbed) first to solidify the input contract.

### 4. Missing tasks
- **Diff-size heuristic (Phase 4):** The orchestrator is a bash script; it has no tokenizer to enforce `Z_MR_DIFF_CHUNK_TOKENS` (80k). You need a byte-size heuristic (e.g., `80,000 tokens ≈ 320KB`) or a lightweight Python/Node script to handle the chunking natively.
- **Voice availability pre-check (D14):** How does the system know a voice is missing? If the agent tries and fails, it wastes time and tokens. The orchestrator (Phase 4) should perform a pre-check (e.g., `which codex`) and pass an `available_voices: [claude, gemini]` array to the agent.
- **Dismissal extraction script:** Both `--amend` and `mr-reviewer` need to parse archives and compute dismissal signatures. There is no task to extract this into a shared utility (e.g., `scripts/extract-dismissals.py`), which will result in duplicated, divergent parsing logic in bash and the agent.

### 5. DRY/KISS/SOLID violations
- **Archive Scope Mismatch:** `mr-reviewer` looks at the last 5 runs *for the current slug* (branch-local), while `--amend` looks at the last 10 *across all slugs* (global repo context). This is a good design, but it's implicit. It must be explicitly documented as intentional so an implementer doesn't "DRY it up" into a single broken query.
- **Missing Shared Utility:** As noted above, parsing `MR-REVIEW.md` files to compute dismissals in two different places is a DRY violation waiting to happen.

### 6. `/z-debug` post-mortem hook (D15)
- **Missing from scope:** You are correct. `commands/z-debug.md` is modified by this feature but is missing from the "Files & paths" table in the SPEC. It must be added to the official file list.
