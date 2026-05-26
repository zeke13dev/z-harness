**Gaps**

- Hermes has more memory surfaces than `SessionDB + FTS5`: built-in `MEMORY.md` / `USER.md`, optional external memory providers, and the background memory review nudge. The draft maps session search well, but treats it as the long-term memory stack rather than one recall layer.
- The draft underplays Hermes’s foreground memory/skill guidance. The system prompt explicitly tells the agent to save durable facts with `memory`, use `session_search` for transcript recall, and save workflows as skills after complex/tricky work.
- The background review loop is not skill-only. There is also `_MEMORY_REVIEW_PROMPT`, `_COMBINED_REVIEW_PROMPT`, a turn-based memory nudge, and external provider sync/prefetch after completed turns.
- Skill lifecycle telemetry is broader than `view_count` / `use_count`: `.usage.json` also tracks patch/edit activity and timestamps such as `last_viewed_at`, `last_used_at`, and `last_patched_at`, which feed curator behavior.
- Skill curation is a separate subsystem worth mapping: curator prompts, stale/overlap handling, pin/archive semantics, backups, protected skill rules, and reports are not covered.
- Hermes skill loading includes optional preprocessing of template variables and inline shell snippets. Even if inline shell is config-gated and off by default, it is part of the terrain.
- The draft omits the distinction between session search and curated memory that Hermes docs state directly: memory is compact always-in-context facts; `session_search` is on-demand transcript recall.
- Atropos portability terrain should include the operational contract around subprocess execution, rollout task IDs, sandbox overrides, trajectory collection, and external scoring. The draft proves Hermes is not training in-process, but does not fully map what an external loop must supply.
- z-harness comparison is thin on retrieval-shape differences: Hermes returns raw neighboring transcript windows and bookends, while z-harness returns doc-fetcher syntheses from curated JSON plus a flat ripgrep index.

**Errors**

- “`maybe_auto_prune_and_vacuum(...)` runs at startup from CLI/gateway/cron” is misleading as stated. Startup calls a maintenance wrapper, but actual auto-pruning is opt-in via `sessions.auto_prune`; default is off.
- “No executable hooks in `SKILL.md` itself” is too absolute. `scripts/` are not auto-run, but `SKILL.md` can contain inline shell snippets that `skill_view` preprocessing may execute when `skills.inline_shell` is enabled.
- “The actual self-improvement loop” as only Skill Documents is mislabeled. Hermes’s actual self-improvement loop includes both memory review and skill review, sometimes combined in one background fork.
- “Three touch points” for Atropos is likely too narrow if interpreted as all RL-related integration surface. There are additional RL/benchmark assumptions in tool gating, sandbox comments, docs, and task-ID behavior, even if not direct `atroposlib` imports.
- “Memory utility / hit counter absent” is correct for `SessionDB`, but too broad if read as Hermes-wide. Skill usage and the holographic memory plugin both track retrieval/use/helpfulness-style counters.

**Missing constraints**

- Hermes’s Skill Documents depend on mutable local skill files being visible to the agent through prompt-index injection and `skill_view`; z-harness’s memory layer is deliberately mediated by `doc-fetcher`, with the main thread not reading `docs/llm/*.json`.
- Hermes background review can write memory/skills automatically after a cadence trigger; z-harness’s authoring path is explicitly opt-in through `/z-suggest-memory`, with Cancel as the default.
- Hermes FTS5 stores and searches raw session transcripts, tool names, and tool-call JSON. z-harness stores curated memory entries with controlled schema/tags, so privacy, staleness, and noise characteristics differ.
- Hermes’s FTS5/trigram path introduces a SQLite dependency and DB maintenance concerns; z-harness’s current lookup path is file-native JSON plus `MEMORIES-FLAT.md` and `rg`.
- Hermes skill dispatch spends prompt budget on an available-skills index every eligible session. z-harness currently pays retrieval cost only through subagent lookup and flat-index search.
- Atropos-style RL portability is bounded by z-harness being Claude-API-only with no weights, GPU, trainer, or fine-tuning pipeline; only logging/evaluation/data-export analogues are portable without external infrastructure.
- Hermes trajectory output lacks reward semantics; any z-harness analogue would need a separate scorer/evaluator boundary if comparing to Atropos, not just event logging.
- Hermes learned skills cohabit with bundled/hub skills under one directory with sidecars and guardrails; z-harness memories live inside repo docs and are subject to git/worktree review and atomic file-update constraints.
tokens used
118,566
**Gaps**

- Hermes has more memory surfaces than `SessionDB + FTS5`: built-in `MEMORY.md` / `USER.md`, optional external memory providers, and the background memory review nudge. The draft maps session search well, but treats it as the long-term memory stack rather than one recall layer.
- The draft underplays Hermes’s foreground memory/skill guidance. The system prompt explicitly tells the agent to save durable facts with `memory`, use `session_search` for transcript recall, and save workflows as skills after complex/tricky work.
- The background review loop is not skill-only. There is also `_MEMORY_REVIEW_PROMPT`, `_COMBINED_REVIEW_PROMPT`, a turn-based memory nudge, and external provider sync/prefetch after completed turns.
- Skill lifecycle telemetry is broader than `view_count` / `use_count`: `.usage.json` also tracks patch/edit activity and timestamps such as `last_viewed_at`, `last_used_at`, and `last_patched_at`, which feed curator behavior.
- Skill curation is a separate subsystem worth mapping: curator prompts, stale/overlap handling, pin/archive semantics, backups, protected skill rules, and reports are not covered.
- Hermes skill loading includes optional preprocessing of template variables and inline shell snippets. Even if inline shell is config-gated and off by default, it is part of the terrain.
- The draft omits the distinction between session search and curated memory that Hermes docs state directly: memory is compact always-in-context facts; `session_search` is on-demand transcript recall.
- Atropos portability terrain should include the operational contract around subprocess execution, rollout task IDs, sandbox overrides, trajectory collection, and external scoring. The draft proves Hermes is not training in-process, but does not fully map what an external loop must supply.
- z-harness comparison is thin on retrieval-shape differences: Hermes returns raw neighboring transcript windows and bookends, while z-harness returns doc-fetcher syntheses from curated JSON plus a flat ripgrep index.

**Errors**

- “`maybe_auto_prune_and_vacuum(...)` runs at startup from CLI/gateway/cron” is misleading as stated. Startup calls a maintenance wrapper, but actual auto-pruning is opt-in via `sessions.auto_prune`; default is off.
- “No executable hooks in `SKILL.md` itself” is too absolute. `scripts/` are not auto-run, but `SKILL.md` can contain inline shell snippets that `skill_view` preprocessing may execute when `skills.inline_shell` is enabled.
- “The actual self-improvement loop” as only Skill Documents is mislabeled. Hermes’s actual self-improvement loop includes both memory review and skill review, sometimes combined in one background fork.
- “Three touch points” for Atropos is likely too narrow if interpreted as all RL-related integration surface. There are additional RL/benchmark assumptions in tool gating, sandbox comments, docs, and task-ID behavior, even if not direct `atroposlib` imports.
- “Memory utility / hit counter absent” is correct for `SessionDB`, but too broad if read as Hermes-wide. Skill usage and the holographic memory plugin both track retrieval/use/helpfulness-style counters.

**Missing constraints**

- Hermes’s Skill Documents depend on mutable local skill files being visible to the agent through prompt-index injection and `skill_view`; z-harness’s memory layer is deliberately mediated by `doc-fetcher`, with the main thread not reading `docs/llm/*.json`.
- Hermes background review can write memory/skills automatically after a cadence trigger; z-harness’s authoring path is explicitly opt-in through `/z-suggest-memory`, with Cancel as the default.
- Hermes FTS5 stores and searches raw session transcripts, tool names, and tool-call JSON. z-harness stores curated memory entries with controlled schema/tags, so privacy, staleness, and noise characteristics differ.
- Hermes’s FTS5/trigram path introduces a SQLite dependency and DB maintenance concerns; z-harness’s current lookup path is file-native JSON plus `MEMORIES-FLAT.md` and `rg`.
- Hermes skill dispatch spends prompt budget on an available-skills index every eligible session. z-harness currently pays retrieval cost only through subagent lookup and flat-index search.
- Atropos-style RL portability is bounded by z-harness being Claude-API-only with no weights, GPU, trainer, or fine-tuning pipeline; only logging/evaluation/data-export analogues are portable without external infrastructure.
- Hermes trajectory output lacks reward semantics; any z-harness analogue would need a separate scorer/evaluator boundary if comparing to Atropos, not just event logging.
- Hermes learned skills cohabit with bundled/hub skills under one directory with sidecars and guardrails; z-harness memories live inside repo docs and are subject to git/worktree review and atomic file-update constraints.
