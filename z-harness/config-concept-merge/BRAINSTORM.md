---
artifact: brainstorm
slug: config-concept-merge
generated_at: 2026-05-27T23:25:00Z
command: /z-brainstorm --slug=config-concept-merge config-vs-config-design concept overlap
input_hash: c0nfigConcept01
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
chosen_framing: claude
note: codex consultant hung on permission prompt; proceeded with 2/3 ideators per 1/3-fail policy
---

## Framing: claude

### Framing
The overlap is a symptom of a mislabeled axis. The two concepts were split by *implementation slice* (when they were written), not by *query surface* (what a doc-fetcher caller actually wants to know). "config-design" and "config" are not natural query terms — nobody asks "what is the config-design?" — they ask "how does config loading work?" or "how do I resolve a workflow question?". The split exists for historical reasons, not semantic ones. The real tension: doc-fetcher's source_file matching is a blunt instrument; shared source_files cause both concepts to fire on any touch.

### Core hypothesis
Merge into one `config` concept, but restructure its internal sections so the two semantic surfaces are **named sub-sections** (`## Loader API` and `## Workflow Resolver`) rather than separate concept files. INDEX entry stays one record; future slices become new sub-sections in the same JSON, not new concepts. Source deduplication is automatic. The "umbrella concept" precedent (`skills` covering 20+ files) already validates this pattern. Concept granularity should track **caller intent granularity**: a doc-fetcher query about config will nearly always need both surfaces, since they're coupled.

### Risks
- **Concept bloat over time.** If slice-3 (cron prefs) and slice-4 (api keys) each add 300 lines, the merged concept JSON becomes unwieldy for the Haiku synthesis window.
- **False precision loss.** Current split lets a query specifically about "4-layer loader" get a tight return. Merging risks returning too much.
- **docs/human/config.md coupling.** If a future author splits config.md into two human-tier files while the LLM concept is merged, the merged concept's source_file list becomes stale.
- **Precedent pressure.** Merging here sets a norm — auditing all other split pairs in INDEX may follow.

### Plan implications
Small: delete `docs/llm/config-design.json`, expand `config.json` with section headers naming both surfaces, deduplicate `source_file`. Update INDEX.json to remove `config-design` entry. ~1 task, <30 min. No doc-fetcher matching-logic changes needed.

### What would change my mind
- Evidence doc-fetcher queries are never cross-surface (callers only ever want one) — would justify keeping the split + investing in line-range matching.
- A concrete future slice independent enough that merged-concept synthesis degrades measurably.
- Discovery that the `skills` umbrella is itself a known pain point.

---

## Framing: codex
*<missing — Codex consultant hung on permission prompt; not retried within cost budget>*

---

## Framing: gemini

### Framing
The current perspective treats overlapping concepts as a documentation routing bug caused by doc-fetcher's path-containment matching, concluding the concepts must merge to fit the physical file structure. **Reverse the relationship:** the LLM concept split is actually CORRECT, and it's acting as a canary in the coal mine for a **codebase boundary violation**. A pure 4-layer TOML loader and a stateful workflow preference resolver share the same physical files — that's a God Object anti-pattern. Don't degrade the conceptual model to match a messy physical reality; use the conceptual model as a blueprint to fix the physical architecture.

### Core hypothesis
`config-design` and `config` represent two architectural domains at different levels of abstraction: low-level generic primitive (pure I/O, parsing) vs high-level application logic (conflict resolution, memory scoping, integration with propose-prefs.py). Merging forces future agents to load deep behavioral logic just to understand a basic TOML read. **Defend the LLM split by structurally splitting the code and human docs:** extract resolver logic from `scripts/config.py` into `scripts/workflow_resolver.py`; split `docs/human/config.md` similarly. Overlap problem dissolves naturally.

### Risks
- **Tail wagging the dog.** Refactoring core system code purely to satisfy an LLM doc-fetcher's limitations is misaligned priority.
- **Refactoring blast radius.** scripts/config.py is deeply entangled — every command and skill imports it. Splitting requires updating dozens of import statements and resolving potential circular deps if the resolver needs the loader's internal data structures.
- **Context fragmentation.** An agent tracing a workflow end-to-end (decision tree → TOML write-back) now needs two separate fetches instead of one.

### Plan implications
- **Code split:** strip scripts/config.py to lines 38-592 + 1193-1285 (schema, load, get, set, export); move `cmd_resolve_question` and workflow logic to `scripts/workflow_resolver.py`.
- **Doc split:** docs/human/config.md keeps loader fundamentals; new `docs/human/workflow-resolver.md` holds decision tree + routing + proposer.
- **Concept mapping:** `config-design` points exclusively to scripts/config.py + config.md. Rename `config` to `workflow-resolver` mapping to scripts/workflow_resolver.py + scripts/propose-prefs.py + workflow-resolver.md. Overlap vanishes.

### What would change my mind
- TOML loading requires strict synchronous locking intrinsically bound to conflict-resolution, making clean decoupling impossible.
- Roadmap deprecates flat TOML for SQLite or external provider — refactoring would be wasted.
- Telemetry shows agents already struggle with multi-file discovery (God Docs actually outperform isolated docs).

---

## Anti-bias check

**Framing dimension.** Gemini's "concepts as a canary for code boundary violation" is genuinely non-obvious and reframes the problem at a deeper level (code architecture, not just doc layout). Claude's "split by slice-vs-query-surface" is sensible but a baseline observation about doc taxonomy. **Gemini wins on Framing for novelty.** Not picking Claude — Claude's framing accepts the code-shape as given; Gemini's challenges it.

**Core hypothesis dimension.** Claude advocates the cheap fix (merge JSON, no code change). Gemini advocates the root-cause fix (split the code, then docs follow naturally). These have materially different cost profiles and aren't comparable as "better/worse" — they answer different questions about how much investment is warranted. The user should choose, not the orchestrator.

**Risks dimension.** Gemini's "tail wagging the dog" + "refactoring blast radius" are sharper because they pre-acknowledge the strongest objection to its own proposal. Claude's "concept bloat over time" is also real but lower-stakes. **Gemini wins on risk surfacing** because it engaged with its own proposal's weakest point.

**Plan implications dimension.** Claude's ~30-min plan is concrete and shippable today. Gemini's plan is a real code refactor (multi-task, ~hours-day). Different leagues; user picks based on appetite for scope.

**What would change my mind dimension.** Both ideators surfaced useful kill-switches. Claude's "evidence about cross-surface queries" is a measurable signal. Gemini's "TOML→SQLite deprecation" is a strategic question. Different shapes, both useful.

## Orchestrator recommendation

**Claude framing** for v1 if the goal is to remove the doc-fetcher overlap NOW with minimum cost — it's a 30-minute fix that hurts nothing and can be reverted later. **Gemini framing** if the architectural concern is real (config.py as God Object) and the team has appetite to extract a workflow-resolver module separately. If unsure, take Claude's path first; the merged concept can later be re-split if/when the code splits. Reversing the order (refactor code first to justify keeping concepts split) is more work for no immediate user-visible benefit.

## User choice

**Chosen framing:** claude

Merge `config-design` and `config` into a single `config` concept with named sub-sections (`## Loader API` + `## Workflow Resolver`). Delete `docs/llm/config-design.json` and the `config-design` entry in `docs/llm/INDEX.json`. Deduplicate source_file. The merged concept JSON internally documents both surfaces but presents as one queryable record.

_Gemini's "structural code split" concern is acknowledged but deferred: track it as a follow-up to evaluate when adding slice-3+ (cron prefs / api keys) if synthesis quality degrades or if config.py shows more God-Object symptoms._
