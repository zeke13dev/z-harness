---
artifact: research
slug: memory-self-improve-loop
generated_at: 2026-05-25T21:37:20Z
command: /z-research "Map Nous Research Hermes Agent (Atropos RL + FTS5 memory + Skill Documents) and assess portability into z-harness memory stack" --slug=memory-self-improve-loop
input_hash: d5be5bc0e95da0a8
depends_on: []
explore_calls: 3
status: complete
---

# Research: Hermes Agent memory + RL — portability to z-harness

Target repo: Nous Research `hermes-agent` cloned at `/tmp/hermes-agent` (depth=1, May 2026).

## Findings

### Atropos RL data flow

- Hermes itself does **no in-process RL training**: zero `import atropos`, `from atropos`, no `gradient`/`backward`/`optimizer`/`LoRA`/`grpo`/`ppo`/`reward` calls in `run_agent.py`, `batch_runner.py`, `agent/conversation_loop.py`, `agent/agent_runtime_helpers.py`, `model_tools.py`, or `tools/terminal_tool.py`. Only `optional-skills/mlops/training/trl-fine-tuning/templates/basic_grpo_training.py` contains trainer code and is an inert user template not invoked by any code path.
- Atropos is an **external orchestrator** that drives Hermes as a subprocess. Its three touch points are: a hook to register per-task sandbox overrides (`tools/terminal_tool.py:939-955`, `register_task_env_overrides`), a defensive async-bridging comment (`model_tools.py:88`), and a dependency pin (`CONTRIBUTING.md:810` lists `atroposlib` as a Git URL pinned by full commit SHA).
- The trajectory schema is **ShareGPT JSONL**: `agent/trajectory.py:30-56` defines `save_trajectory(trajectory, model, completed, filename)`. One JSONL line per call, appended to `trajectory_samples.jsonl` (if `completed=True`) or `failed_trajectories.jsonl` (`completed=False`). Each line: `{conversations: [...], timestamp, model, completed}`.
- ShareGPT conversion lives at `agent/agent_runtime_helpers.py:58-` (`convert_to_trajectory_format`). Synthesizes a `"system"` entry with full tool schema, then alternates `"human"` / `"gpt"` (with `<tool_call>` XML and optional `<think>` reasoning) / `"tool"` (responses wrapped in `<tool_response>` XML). Images stripped to `text_summary` to avoid base64 blobs (`agent_runtime_helpers.py:73`).
- `save_trajectory` is called **per-task, once at end of conversation loop** (`agent/conversation_loop.py:4055`), gated by `if not self.save_trajectories: return` (`run_agent.py:1412`). Default off; opt-in via `--save_trajectories` flag or constructor arg (`run_agent.py:365`). Batch runner returns trajectory as data without writing (`batch_runner.py:358`); CLI `--save_sample` writes one pretty-printed JSON per run (`run_agent.py:4383`).
- The `completed` flag is a **liveness signal**. Set at `agent/conversation_loop.py:4047-4051` as `final_response is not None and api_call_count < agent.max_iterations and not failed`. `failed` itself is `False` initially and flipped `True` only in the Ollama context-too-small path (`conversation_loop.py:606`, `:972`). **Hermes itself does not embed external scores** (test pass, diff check) into the JSONL output — whether atroposlib enriches the trajectory post-hoc with external rewards is outside the scope of this read (lives in the [atroposlib repo](https://github.com/NousResearch/atropos), not investigated here).

### Long-term memory (three surfaces: foreground MEMORY.md/USER.md, SessionDB+FTS5, optional plugin)

**Foreground always-in-context memory (built-in, separate from SessionDB).** `tools/memory_tool.py:6-8` exposes two flat Markdown files under `~/.hermes/`:
- `MEMORY.md` — agent's personal notes and observations (environment facts, project context).
- `USER.md` — what the agent knows about the user (preferences, communication style).

Both are loaded into the system prompt every session (`tools/memory_tool.py:202-207`). The `memory` tool reads and appends via path resolution at `:260-261`. The skill manager docstring (`tools/skill_manager_tool.py:11`) explicitly contrasts these against skills: *"General memory (MEMORY.md, USER.md) is...[for facts]"*, while skills capture *"workflows for a specific type of task based on proven experience."* The CLI confirms (`hermes_cli/main.py:12711`): *"Built-in memory (MEMORY.md/USER.md) is always active."* The original draft missed this surface entirely; it is the closest analog to z-harness's auto-memory MEMORY.md (orthogonal global memory in `~/.claude/projects/<slug>/memory/`).

**SessionDB + FTS5 (on-demand transcript recall):**

- Two FTS5 virtual tables in `state.db`: `messages_fts` with unicode61 tokenizer (`hermes_state.py:256`) and `messages_fts_trigram` with trigram tokenizer for CJK (`hermes_state.py:285`). Both single-column (`content`).
- Indexed payload is a **concatenation of raw message text + tool_name + tool_calls JSON** (`hermes_state.py:260`): `INSERT INTO messages_fts(rowid, content) VALUES (new.id, COALESCE(new.content,'') || ' ' || COALESCE(new.tool_name,'') || ' ' || COALESCE(new.tool_calls,''))`. No summaries, no structured fact extraction in this path.
- Underlying `messages` table (`hermes_state.py:224`) stores full content + tool metadata + reasoning fields + token_count. Sessions table (`hermes_state.py:190`) carries source/user_id/model/system_prompt/parent_session_id and timestamps + cost counters.
- `tools/session_search_tool.py:378` exposes one `session_search()` function with three modes: **discovery** (FTS5 MATCH, BM25 rank by default, see `hermes_state.py:2198`), **scroll** (±window around an anchor message, no FTS5, `session_search_tool.py:153`), **browse** (recent sessions chronologically, `:110`). CJK queries with ≥3 CJK chars routed to trigram table (`hermes_state.py:2218`); 1-2 chars fall back to `LIKE`.
- Discovery returns FTS5-highlighted `snippet`, plus bookends (first 3 + last 3 messages of session) and ±5 messages around the match (`session_search_tool.py:347-365`).
- **Eviction** is session-level only: `prune_sessions(older_than_days=90)` hard-deletes ended sessions and cascades to their messages (`hermes_state.py:2578`). Active sessions never pruned. The startup hook is **opt-in via `sessions.auto_prune` config** (`cli.py:1281` — `if not cfg.get("auto_prune", False): return`); default off in the generic profile (`hermes_cli/config.py:1677`), default on in the curated profile (`:748`). When enabled, `maybe_auto_prune_and_vacuum(retention_days=90, min_interval_hours=24)` runs (`hermes_state.py:3107`); VACUUM only fires if rows were pruned (`:3155`). Tracking via `state_meta["last_auto_prune"]`. **No per-message TTL, no archival tier.**
- **Memory utility / hit counter — absent in main store.** No `hit_count`, `access_count`, `last_used`, or `usefulness` columns on `messages` or `sessions`. The main FTS5 path is append-on-write with zero retrieval feedback.
- The **only** subsystem with utility tracking is the `holographic` memory plugin (`plugins/memory/holographic/store.py:16-76`): a separate `memory_store.db` with a `facts` table carrying `retrieval_count INTEGER DEFAULT 0` (bumped on every successful `search_facts`, `store.py:233`), `helpful_count INTEGER DEFAULT 0` (bumped by an explicit `fact_feedback(action='helpful')` tool call, `store.py:374`), and `trust_score REAL DEFAULT 0.5` adjusted asymmetrically (+0.05 helpful, -0.10 unhelpful, `store.py:79`, `:371`). Trust acts as a retrieval-rank multiplier (`retrieval.py:97`), and `min_trust` defaults to 0.3 as a filter floor.
- The `fact_feedback` tool is the user-of-memory signaling mechanism (`plugins/memory/holographic/__init__.py:76`). It is **agent-initiated**, not automatic — there is no implicit "you retrieved this fact and then succeeded, +1" credit assignment.
- The plugin loader enforces **a single active provider** via `memory.provider` config key (`plugins/memory/__init__.py:14-16`) — runtime exclusivity, **not schema exclusivity**: nothing prevents porting the holographic schema (trust_score + retrieval_count) into a different stack. Eight bundled providers (byterover, hindsight, holographic, honcho, mem0, openviking, retaindb, supermemory); bundled wins on name collision (`:83`). Six of the eight delegate to external APIs and have no local store of their own.

### Auto-distillation + Skill Documents (the actual self-improvement loop)

**Note on scope.** Hermes's self-improvement loop covers **both memory and skills**, not just skills. Background-review fork dispatches one of three prompts depending on which nudges fire (`agent/background_review.py:572-578`):
- `_MEMORY_REVIEW_PROMPT` (`background_review.py:34`) — memory-only review.
- `_SKILL_REVIEW_PROMPT` (`background_review.py:45`) — skill-only review.
- `_COMBINED_REVIEW_PROMPT` (`background_review.py:150`) — both nudges fired same turn.

This means the auto-distillation loop targets two surfaces: durable facts (MEMORY.md/USER.md or active memory provider) **and** procedural skills. The original draft framed it as skill-only; both apply.

**Skills specifics:**

- Skill format is YAML frontmatter + Markdown body in `SKILL.md`, organized as a directory: `SKILL.md` plus optional `references/`, `templates/`, `scripts/`, `assets/` subdirs. Frontmatter has `name`, `description`, optional `version`, `platforms`, `metadata.hermes.{tags, related_skills}` (`tools/skills_tool.py:28-66` docstring, `tools/skill_manager_tool.py:217-253` validation).
- **Limited executable hooks in SKILL.md.** `scripts/` files are invoked by agent tool calls, not auto-run. `platforms:` is a declarative filter (`tools/skills_tool.py:152`). Inline `!`cmd`` shell snippets in SKILL.md bodies CAN be executed at `skill_view` time, but this is gated by `skills.inline_shell` config (`hermes_cli/config.py:1300-1302`) — **default off** (`tests/agent/test_skill_commands.py:725` test name `test_inline_shell_is_off_by_default`), with a per-snippet timeout (`inline_shell_timeout`, default 10s).
- **Dispatch is three-tier:**
  - Tier 1 — passive index. `build_skills_system_prompt()` (`agent/prompt_builder.py:997`) scans `~/.hermes/skills/` and builds an `<available_skills>` block of `category: name: description` entries, injected into the **stable** tier of the system prompt (`agent/system_prompt.py:169-185`). Prompt explicitly instructs: *"Before replying, scan the skills below. If a skill matches or is even partially relevant to your task, you MUST load it with skill_view(name)."*
  - Tier 2 — on-demand. Agent calls `skill_view(name)` (`tools/skills_tool.py:850`) to read the full SKILL.md body. `.usage.json` (`tools/skill_usage.py:312-315`) tracks the full lifecycle: `view_count`, `use_count`, `patch_count`, plus timestamps `last_viewed_at`, `last_used_at`, `last_patched_at` (bumped by `record_view`, `record_use`, `record_patch` at `:409-429`). Curator stale timer keys off `last_used_at` (`skills_tool.py:1553`).
  - Tier 3 — CLI preload. `--skills` flag injects full body of selected skills above the conversation (`cli.py:14869-14881`, `agent/skill_commands.py:475`, `:508-521`).
- **Cache** is two-layer: in-process LRU keyed by `(skills_dir, tools, toolsets, platform, disabled_set)` (`prompt_builder.py:1031-1043`) + disk snapshot at `~/.hermes/.skills_prompt_snapshot.json` validated by mtime/size manifest (`:876-910`). Cold path: full `rglob("SKILL.md")` (`:1079-1118`). Invalidated on every successful `skill_manage` write via `clear_skills_system_prompt_cache(clear_snapshot=True)` (`skill_manager_tool.py:871-873`).
- **Auto-distillation via background-review fork** — this is the *actual* self-improvement loop:
  - Every conversation turn increments `_iters_since_skill` (`agent/conversation_loop.py:732-734`). When `_iters_since_skill >= _skill_nudge_interval` at turn end (`:4247-4252`), `_should_review_skills = True`. Fires only on non-interrupted turns with non-empty response (`:4263`).
  - `agent._spawn_background_review(messages_snapshot=..., review_memory=..., review_skills=True)` (`run_agent.py:1174`, `conversation_loop.py:4265`) forks a daemon `AIAgent` on a background thread, inheriting parent credentials/model/cached system prompt verbatim for prefix-cache reuse.
  - The fork receives `_SKILL_REVIEW_PROMPT` (`agent/background_review.py:45-148`) plus the full conversation snapshot. Prompt is prescriptive: signals to watch for (user frustration, workflow corrections, techniques discovered, outdated skills used), preference order (patch loaded skill > patch existing umbrella > add support file > create new umbrella), explicit bans (PR-number names, library-alone names, session-specific names, negative capability claims).
  - **Tool whitelist** locks the fork to `memory` + `skills` toolsets only (`background_review.py:459-484`).
  - When both memory and skill nudges fire same turn, `_COMBINED_REVIEW_PROMPT` is used (`background_review.py:150-233`, `:573-578`).
- **Provenance** via `ContextVar` (`tools/skill_provenance.py:37` `_write_origin`). `is_background_review()` (`:75`) is queried inside `skill_manage`. When a background fork calls `skill_manage(action='create')`, it triggers `mark_agent_created(name)` (`skill_manager_tool.py:883-885`). Security scan via `skills_guard.scan_skill()` on every write (`:512-516`).
- **Built-in vs. learned skills cohabitate** in `~/.hermes/skills/`. Distinguished by sidecar files: `.bundled_manifest` (per-skill MD5 origin hashes, `tools/skills_sync.py:21`, `:39` — modified bundled skills are detected by hash divergence and excluded from re-sync, `:17`), `.usage.json` `created_by: "agent"` flag (`skill_usage.py:290-300`), `.hub/lock.json` for hub-installed (`:182-213`). Curator auto-archive/consolidation skips anything in the bundled or hub lists (`:292`, `:182-213`).

### Mapping onto z-harness

| Dimension | Hermes | z-harness analog | Gap |
|---|---|---|---|
| Memory authoring | Background fork writes via `skill_manage`; agent-initiated `memory_*` tool calls; `fact_feedback` for trust | `/z-suggest-memory` is sole authoring path, schema-validated, atomic, user-approved (default Cancel) | z-harness has no automatic writer; Hermes has both auto (fork) + user-mediated paths |
| Memory index | `<available_skills>` block in stable system-prompt tier (cached two-layer) | `MEMORIES-FLAT.md` ripgrep index, retrieved via `doc-fetcher` subagent on demand | Hermes auto-injects index every session; z-harness uses pull model via doc-fetcher |
| Full-text search | SQLite FTS5 (BM25 default, no time decay in main path) + holographic trust-weighted rerank | ripgrep over `MEMORIES-FLAT.md`, no BM25, no decay | Same retrieval primitive (text match); Hermes adds trust scoring via holographic only |
| Utility tracking | None in main store; holographic plugin has `retrieval_count`, `helpful_count`, `trust_score` with explicit `fact_feedback` | None | Same gap on both sides; holographic is closest model |
| Self-improvement trigger | N-turn nudge in conversation loop → background fork on daemon thread | `/z-improve` opt-in, user-fired only | Hermes has automatic trigger; z-harness is fully manual |
| Distillation prompt | `_SKILL_REVIEW_PROMPT` densely prescriptive about signals + preference order + bans | None (closest is `/z-improve` analysis phase, but it's opt-in and human-mediated) | Direct port candidate |
| Trajectory persistence | ShareGPT JSONL via `save_trajectory`, opt-in, per-task | `events.jsonl` per-run via `scripts/log-event.sh`, always-on | Different schemas; events.jsonl is structured-events, not ShareGPT-format |
| RL training | External (atroposlib consumes JSONL to fine-tune model weights) | None; Claude-API-only stack | Not portable without model ownership + GPU + training pipeline |

## Constraints discovered

- **Hermes does not fine-tune in-process.** Any "Hermes RL" claim refers to *training data production*, not model updates. Importing the RL part requires atroposlib + a model we control (e.g. an open weights Hermes/Llama derivative) + training compute. None of this exists in the z-harness setup, which is Claude-API-only (`run_agent.py:1412` save-trajectories gate, `CONTRIBUTING.md:810` atroposlib pin).
- **The `completed` flag carries no semantic reward signal.** Even if we wanted to mimic Atropos's reward shaping locally, the source signal Hermes emits is liveness-only (`agent/conversation_loop.py:4047-4051`). Real reward signals (test pass, review accepted, no retries) would need to be reconstructed from our own `events.jsonl` independently.
- **Memory providers in Hermes are mutually exclusive.** The plugin loader enforces a single active `memory.provider` (`plugins/memory/__init__.py:14-16`). z-harness's flat `docs/llm/<slug>.json` array structure is closer to Hermes's `holographic` plugin (local SQLite + utility scoring) than to the remote-API providers (mem0, supermemory, etc.).
- **Skill prompt cache invalidation is mandatory after every write** (`skill_manager_tool.py:871-873`). If we port the auto-distillation pattern, any analogous z-harness mechanism that writes to `docs/llm/` mid-session must invalidate whatever cache `doc-fetcher` builds, or future retrievals serve stale state.
- **Hermes auto-distillation runs on a daemon thread inheriting parent credentials + cached system prompt.** That works because Hermes is a long-running process with shared in-memory state. z-harness commands are short-lived shell invocations — porting "background fork" literally would require either a persistent harness daemon or a subagent dispatch at fixed loop boundaries (e.g. after each task in `/z-implement-all`).
- **Trust score is asymmetric in holographic** (+0.05 helpful, -0.10 unhelpful, `store.py:79`, `:371`). Penalties twice the reward — a deliberate "negative evidence outweighs positive" bias. Any z-harness scoring scheme should consider the same asymmetry.
- **The skill review prompt explicitly bans certain naming patterns** (PR numbers, library-alone, session-specific, negative capability). These bans were learned from production; ignoring them risks the same anti-patterns surfacing in z-harness memories.

## Open questions

- **What actually happens to `trajectory_samples.jsonl` once written?** The repo proves Hermes produces the file; what atroposlib does with it (rollout selection, reward annotation, training schedule) is in the [atroposlib repo](https://github.com/NousResearch/atropos) and not investigated here. Worth a follow-up read if we want to mimic any of the reward-shaping logic.
- **Background-review fork cost economics.** How often does it fire in practice? `_skill_nudge_interval` default value not captured here — finding it would tell us the empirical write rate. Also unknown: prefix-cache hit rate on the fork (the comment claims it inherits cached system prompt, but cache eligibility under Anthropic API depends on token-prefix exactness).
- **Cache invalidation race.** If background fork writes a skill mid-session, what happens to in-flight requests that referenced the stale `<available_skills>` block? Repo says cache is cleared (`skill_manager_tool.py:871-873`); doesn't say how the next prompt build sees the new state if the fork's write commits after the parent thread's stable-tier was already built for the current turn.
- **Does `fact_feedback` get called in practice?** The holographic plugin has the schema and tool, but we did not check if any built-in agent path actually invokes `fact_feedback` automatically vs. requiring the LLM to choose to call it. If it's purely LLM-discretion, the trust score is also "user-mediated" in the same sense `/z-suggest-memory` is — not a real RL signal. Related: `retrieval_count` is bumped on every `search_facts` hit (`holographic/store.py:233`) regardless of whether the agent acted on the fact, so it's a "this fact was surfaced" counter, not a utility signal — Gemini's gap on this is now answered: it's the weak interpretation.
- **Background-review cost economics under Claude API.** Hermes claims the fork "inherits cached system prompt" for prefix-cache reuse — that's a true in-memory inheritance for a local-model agent, but Anthropic's prefix cache requires exact token-prefix matching AND has TTL constraints. The cost of background reviews under Claude API may be substantially higher than the Hermes self-reported pattern suggests. `_skill_nudge_interval` default not captured here; it determines the empirical write rate and per-session cost amplifier.
- **Curator subsystem (auto-archive, consolidation, pin/protect, backups).** Mentioned in `skill_usage.py:182-213` (hub lock) and Codex critique. Not investigated here. Relevant if porting auto-distillation, because without a curator the skill/memory store grows unbounded.
- **What signal would Hermes use to detect "this memory was useful"?** The closest mechanism (holographic `helpful_count`) requires explicit agent tool call. There is no implicit credit assignment ("you retrieved fact F, then completed the task → +reward to F"). Whether Atropos infers this externally from the trajectory + outcome is unknown without reading atroposlib.
- **Skill collision policy** when an auto-distilled skill overlaps with a bundled one. Bundled wins on the index side (`plugins/memory/__init__.py:83` for memory providers, `tools/skills_sync.py:17` for skill manifest), but in-fork the prompt prefers "patch existing umbrella" over "create new" — so the fork is supposed to avoid collisions, not resolve them post-hoc. Risk: prompt compliance is statistical.

## Cross-LLM review notes

**Gemini critique (filled vs unfilled):**
- **Filled:** Softened the "no test-pass / no diff check / no external scorer" claim — atroposlib may enrich post-hoc; that path is out of scope here, flagged explicitly in Findings. Softened "mutually exclusive" to "runtime exclusivity, not schema exclusivity."
- **Unfilled:** (a) What reward signals atroposlib actually derives from JSONL — requires reading the atroposlib repo, listed in Open questions. (b) Holographic plugin adoption in practice — not determinable from this repo read; flagged. (c) Background-fork cost economics (token, latency, prefix-cache hit rate under Anthropic API) — flagged in Constraints + Open questions. (d) Skill collision policy when prompt compliance fails — flagged. (e) `retrieval_count` semantics (all retrievals vs. acted-on only): verified — `holographic/store.py:233` bumps on every `search_facts` hit regardless of subsequent use, so it's a weak "this fact was even surfaced" counter rather than a utility signal.
- **Unfilled (asymmetric-trust significance):** Gemini correctly notes we don't have the base rate of `fact_feedback` calls to know if the +0.05/-0.10 asymmetry actually matters in practice. Telemetry would have to come from a deployed Hermes instance; not in the repo.

**Codex critique (filled vs unfilled):**
- **Filled:** Added MEMORY.md / USER.md foreground memory surface (verified `tools/memory_tool.py:6-8, 202-207, 260-261`; `skill_manager_tool.py:11`; `hermes_cli/main.py:12711`). Corrected auto-prune statement — opt-in via `sessions.auto_prune`, default off in generic profile (`cli.py:1281`, `config.py:1677` vs `:748`). Corrected "no executable hooks" — inline shell config-gated, default off (`config.py:1300`, `test_skill_commands.py:725`). Added full `.usage.json` field set (`skill_usage.py:312-315, 409-429`). Reframed self-improvement loop as covering both memory and skills via three review prompts (`background_review.py:34, 45, 150, 572-578`).
- **Unfilled:** (a) Curator subsystem (stale/overlap handling, pin/archive, backups, protected-skill rules) — separate read, deferred. (b) Atropos external-scoring contract beyond what's already cited — same as Gemini's (a) above. (c) Hermes documentation framing of memory vs. session_search distinction — not pursued; the code-level distinction is captured.

This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
