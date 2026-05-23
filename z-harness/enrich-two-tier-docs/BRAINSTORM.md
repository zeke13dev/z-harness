---
artifact: brainstorm
slug: enrich-two-tier-docs
generated_at: 2026-05-23T05:47:44Z
command: /z-brainstorm enrich-two-tier-docs
input_hash: ba9e1e2909e0422d
depends_on: []
ideators:
  - claude
  - codex:failed
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: pending
---

## Framing: claude

### Framing

The two-tier docs system conflates two distinct jobs: *locating* (where is the code that handles X?) and *remembering* (what did we learn the hard way about X?). The current JSON schema does the first job adequately, but `gotchas` and `invariants` are treated as structural annotations rather than episodic memories — they have no provenance, no authoring event, no decay signal. The lookup layer compounds this: substring match on slug/summary is a greedy approximation that works when you already know the concept name but fails completely for queries like "why can't we cache this" or "what broke last time we touched the batch pipeline." The real problem is that the system has no *institutional memory layer* — a place where time-stamped, event-sourced observations accumulate outside the code itself and can be retrieved by semantic intent, not keyword coincidence.

### Core hypothesis

The highest-leverage change is not better search — it is adding a `memories` array to the per-concept JSON schema where each entry carries `{text, kind, source_event, date, author}`. `kind` is one of `tried-and-dropped | anti-pattern | decision-rationale | performance-trap | open-question`. This turns the concept file from a static snapshot into a time-ordered journal. The lookup layer should then be a flat `docs/llm/SEARCH.txt` file — one line per memory, prefixed with slug and kind, ripgrep-able with no tooling beyond what already exists in the harness. doc-fetcher gets a second phase: after INDEX.json concept selection, it greps SEARCH.txt for the query terms and injects matching memory lines into its synthesis. No embeddings, no new agent type, no external service — just grep and structured JSON.

### Risks

- **Authoring burden is the primary failure mode.** Memories only accrue value if they are written at the moment of discovery — during `/z-debug` post-mortems, at `/z-improve` retros, in the `/z-plan` decisions log. If authoring is deferred to a "doc update pass", it will not happen. The pipeline must write memories automatically or they will not exist.
- **Staleness without provenance poisons the well.** A memory that says "don't use X approach" with no date or source event becomes indistinguishable from correct current advice vs. stale caution. Readers either trust everything (dangerous) or trust nothing (worthless).
- **2 KB synthesis cap.** If a concept accumulates 20 memories averaging 80 chars each, that is already 1.6 KB before the structural fields. doc-fetcher's current cap will be consumed by memories alone on hot concepts, leaving no room for file:line pointers.
- **SEARCH.txt fan-out.** A single flat file works fine at 50 concepts. At 500 concepts with 10 memories each, grep latency is still negligible but the file becomes editorially unmanageable for humans.
- **Human visibility.** If memories live only in `docs/llm/*.json`, the human tier (`docs/human/`) will not reflect them. Engineers reading docs/human/ get the structural picture but miss the institutional memory. Sync discipline between tiers will erode.

### Plan implications

- **Schema change is small and backward-compatible.** Add `memories: []` to the JSON shape; existing files with no memories remain valid.
- **Authoring hooks are the critical path.** Every pipeline that can generate a memory (z-debug, z-improve, z-plan) needs a "write memory" step before it exits. This is more work than the schema change.
- **SEARCH.txt must be regenerated** by doc-updater on every concept update — treat it as a derived artifact, not a hand-edited file.
- **doc-fetcher needs a second Read call**: after INDEX.json selection, grep SEARCH.txt (or Read it and filter in-prompt). This uses one more of its 8-Read budget but stays within cap.
- **Decay policy**: memories older than 180 days with no confirming re-occurrence should be downgraded to `confidence: low` in the parent concept. This is automatable in doc-updater.
- **Human tier sync**: doc-updater should emit a `docs/human/<concept>.md` section `## Memories` that lists memories in plain prose so engineers see them in normal file browsing.

### What would change my mind

- If the primary orchestrator failure mode turns out to be "doc-fetcher returns the right concept but the concept JSON lacks structural pointers" (not "wrong concept selected"), then lookup-layer investment outweighs memory enrichment.
- If grep over SEARCH.txt proves unreliable for natural-language queries (e.g., query "why did we stop using async writes" finds nothing because memories use different vocabulary), then embedding search becomes justified despite its tooling cost.
- If human engineers demonstrably read `docs/human/` regularly and want memories there, the sync burden is worth it. If nobody reads docs/human/ except LLMs anyway, the single-tier (LLM-only memories) approach is fine.
- If concept count stays below 30 and memory count stays below 5 per concept, the current gotchas/invariants fields with slightly richer text are sufficient and no schema change is needed.

---

## Framing: codex

`codex:failed` — Codex binary missing (spawn ENOENT at `/opt/homebrew/lib/node_modules/@openai/codex/vendor/aarch64-apple-darwin/codex/codex`). No response produced.

---

## Framing: gemini

### Framing

We are transitioning the `docs/llm/` layer from a static geographical map ("what is here and how does it connect") to an institutional memory bank ("why did we build it this way, and what failed"). Code can be read by any agent to understand current state, but code inherently erases the history of abandoned paths, hard-won invariants, and performance traps. By systematically capturing these "memories" and exposing them through a significantly enhanced lookup layer, we aim to replace expensive, token-heavy codebase exploration with high-fidelity, immediate context retrieval.

### Core hypothesis

If we enrich LLM-tier JSON with structured, timestamped memories (`abandoned_paths`, `anti_patterns`, `decision_rationale`) and replace the naive substring matching in `doc-fetcher` with a flat, ripgrep-optimized reverse index (or a rich `tags/keywords` array in `INDEX.json`), orchestrators will skip redundant exploration phases, avoid past mistakes, and reliably fetch the exact historical context they need. This will drastically reduce context bloat and execution failures, provided memories carry strict provenance (who/when) to mitigate context rot.

### Risks

- **The 2 KB Synthesis Cap:** `doc-fetcher` currently has a hard 2 KB synthesis limit. Rich memories, incident descriptions, and rationales will explode the size of these JSONs, either breaking the `doc-fetcher` context window or forcing it to violently truncate the very nuances we are trying to preserve.
- **The "Ghost Town" of Stale Context:** Without an automated or highly disciplined garbage collection mechanism, memories will decay. An "abandoned path" from 2024 might be perfectly viable in 2026 due to underlying dependency updates. Stale memories act as false constraints, paralyzing agents.
- **Human-LLM Divergence:** If rich historical context lives exclusively in `docs/llm/`, human engineers lose out on critical operational memory. The two-tier system risks becoming a split-brain system where agents know the "why" and humans only have the "what."
- **Search Latency/Complexity:** Moving from a fast JSON index read to embedding-based search or spawning a dedicated `docs-search` subagent introduces latency and points of failure into what must be a lightning-fast retrieval step.

### Plan implications

- **Schema Overhaul:** `doc-updater` must be updated to emit and manage new arrays in the concept JSON schema: `abandoned_paths[]`, `anti_patterns[]`, `rationales[]`. Each must require `date` and `provenance` (e.g., "From /z-debug session on 2026-05-22").
- **Index Re-architecture:** `INDEX.json` must be expanded to include a `keywords[]` taxonomy, or alternatively, `doc-updater` must compile a flat `search_index.md` containing all summaries, tags, and memory snippets designed specifically for ripgrep.
- **Authoring Pipeline:** We must define the ingestion route. Commands like `/z-improve`, `/z-debug`, or post-mortems need a mandatory step to draft "memory updates" and push them to `doc-updater`. It cannot just be an afterthought.
- **Doc-Fetcher Redesign:** The `doc-fetcher` agent prompt must be rewritten to handle the new memory fields. Its 2 KB output cap must either be raised, or it must be taught how to concisely summarize historical context without losing the "gotchas".

### What would change my mind

- **Context Window Economics:** If native context windows become so large and cheap (paired with flawless native prompt caching) that we can just feed the orchestrator the entire git history, PR descriptions, and issue tracker without curating discrete "memories."
- **Telemetry Proving Low ROI:** If metrics show that orchestrators rarely fall into the exact same traps twice, meaning the "abandoned paths" feature is a solution looking for a problem, and the real bottleneck is just finding the right file.
- **Maintenance Overhead:** If the token cost and time required to constantly curate, summarize, and update these memories via `doc-updater` eclipses the cost of the orchestrator just exploring the codebase and making an occasional mistake.

---

## Anti-bias check

**Framing:** Both ideators frame this identically — static map → institutional memory. Gemini's version is more concise and quotable; Claude's is more diagnostic. **Gemini wins on Framing** — no Claude-favoring pick here; Gemini's economy is genuine.

**Core hypothesis:** Claude proposes a specific minimal mechanism (memories array + SEARCH.txt flat file + grep second phase in doc-fetcher). Gemini proposes the same structural fields but hedges between ripgrep and richer INDEX.json keywords without committing to either. **Claude wins on Core hypothesis** — justified: Claude's hypothesis names the exact artifact (SEARCH.txt) and mechanism (second-phase grep in doc-fetcher) while Gemini stays at the level of "we should replace substring match" without specifying how. This is a concrete implementation advantage, not home-team bias.

**Risks:** Both surface the 2 KB cap, staleness, and human-LLM divergence. Claude adds the **authoring-burden-as-primary-failure-mode** insight (missed entirely by Gemini) and SEARCH.txt fan-out at scale. Gemini adds **search latency/complexity** as a distinct risk (missed by Claude). These are genuinely additive. **Split win** — Claude wins for authoring-burden; Gemini wins for latency/complexity. Neither ideator has a full monopoly on the risk surface.

**Plan implications:** Claude gives a sequenced list with the "authoring hooks are critical path" insight, concrete decay policy (180-day rule), and SEARCH.txt-as-derived-artifact framing. Gemini identifies the same top-line items at lower resolution. **Claude wins on Plan implications** — justified: Claude produces the specific sequencing insight and a concrete automatable decay policy that Gemini lacks. This is substance, not affinity.

**What would change my mind:** Gemini's "context window economics" counter-argument (if windows become so large/cheap that curation cost > exploration cost, skip the whole system) is a genuinely macro-level falsifier that Claude did not produce. Claude's conditions are narrower and more technical. **Gemini wins on What would change my mind** — important macro falsifier absent from Claude's response.

**Summary:** Claude wins 2 sections outright (Core hypothesis, Plan implications), Gemini wins 2 sections outright (Framing, What would change my mind), Risks is a shared split. No Claude-favoring pick lacks explicit justification.

## Orchestrator recommendation

**Claude framing** — it produces the most actionable, minimal-tooling hypothesis (memories array + SEARCH.txt flat file + grep second phase) while correctly identifying authoring-burden as the critical-path failure mode most likely to sink the real implementation; Gemini's framing is diagnostically cleaner but leaves the implementation open-ended.
