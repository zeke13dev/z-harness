MODE: research-review

Original question: Map Nous Research's Hermes Agent (Atropos RL loop + FTS5 long-term memory + Skill Documents) and assess portability into z-harness's existing memory stack (which is Claude-API-only, no model training, has docs/llm/<slug>.json memories + MEMORIES-FLAT.md ripgrep index + doc-fetcher subagent + opt-in /z-improve + /z-suggest-memory authoring tool).

Scaffolding (already-known z-harness state, from prior doc-fetcher):
- /z-suggest-memory is sole authoring path; atomic writes; auto-regenerates MEMORIES-FLAT.md (ripgrep index); 15 controlled tags in TAGS.txt; default outcome Cancel.
- /z-implement-all and /z-review-all emit events.jsonl via scripts/log-event.sh. No auto-invocation of /z-improve after major runs.
- Main thread never reads docs/llm/*.json — always dispatches doc-fetcher subagent (Haiku) which does two-phase search: INDEX.json + MEMORIES-FLAT.md ripgrep.
- z-harness is Claude-API-only; no model weights, no GPU, no fine-tuning pipeline.

RESEARCH DRAFT TO CRITIQUE:

# Research: Hermes Agent memory + RL — portability to z-harness

Target repo: Nous Research `hermes-agent` cloned at `/tmp/hermes-agent` (depth=1, May 2026).

## Findings

### Atropos RL data flow

- Hermes itself does **no in-process RL training**: zero `import atropos`, `from atropos`, no `gradient`/`backward`/`optimizer`/`LoRA`/`grpo`/`ppo`/`reward` calls in `run_agent.py`, `batch_runner.py`, `agent/conversation_loop.py`, `agent/agent_runtime_helpers.py`, `model_tools.py`, or `tools/terminal_tool.py`. Only `optional-skills/mlops/training/trl-fine-tuning/templates/basic_grpo_training.py` contains trainer code and is an inert user template not invoked by any code path.
- Atropos is an **external orchestrator** that drives Hermes as a subprocess. Its three touch points are: a hook to register per-task sandbox overrides (`tools/terminal_tool.py:939-955`, `register_task_env_overrides`), a defensive async-bridging comment (`model_tools.py:88`), and a dependency pin (`CONTRIBUTING.md:810` lists `atroposlib` as a Git URL pinned by full commit SHA).
- The trajectory schema is **ShareGPT JSONL**: `agent/trajectory.py:30-56` defines `save_trajectory(trajectory, model, completed, filename)`. One JSONL line per call, appended to `trajectory_samples.jsonl` (if `completed=True`) or `failed_trajectories.jsonl` (`completed=False`). Each line: `{conversations: [...], timestamp, model, completed}`.
- ShareGPT conversion lives at `agent/agent_runtime_helpers.py:58-` (`convert_to_trajectory_format`). Synthesizes a `"system"` entry with full tool schema, then alternates `"human"` / `"gpt"` (with `<tool_call>` XML and optional `<think>` reasoning) / `"tool"` (responses wrapped in `<tool_response>` XML). Images stripped to `text_summary` to avoid base64 blobs (`agent_runtime_helpers.py:73`).
- `save_trajectory` is called **per-task, once at end of conversation loop** (`agent/conversation_loop.py:4055`), gated by `if not self.save_trajectories: return` (`run_agent.py:1412`). Default off; opt-in via `--save_trajectories` flag or constructor arg (`run_agent.py:365`). Batch runner returns trajectory as data without writing (`batch_runner.py:358`); CLI `--save_sample` writes one pretty-printed JSON per run (`run_agent.py:4383`).
- The `completed` flag is a **liveness signal, not a reward**. Set at `agent/conversation_loop.py:4047-4051` as `final_response is not None and api_call_count < agent.max_iterations and not failed`. `failed` itself is `False` initially and flipped `True` only in the Ollama context-too-small path (`conversation_loop.py:606`, `:972`). No test-pass, no diff check, no external scorer feeds back into the JSONL output. Reward shaping happens **outside** Hermes in atroposlib.

### Long-term memory (SessionDB + FTS5)

- Two FTS5 virtual tables in `state.db`: `messages_fts` with unicode61 tokenizer (`hermes_state.py:256`) and `messages_fts_trigram` with trigram tokenizer for CJK (`hermes_state.py:285`). Both single-column (`content`).
- Indexed payload is a **concatenation of raw message text + tool_name + tool_calls JSON** (`hermes_state.py:260`): `INSERT INTO messages_fts(rowid, content) VALUES (new.id, COALESCE(new.content,'') || ' ' || COALESCE(new.tool_name,'') || ' ' || COALESCE(new.tool_calls,''))`. No summaries, no structured fact extraction in this path.
- Underlying `messages` table (`hermes_state.py:224`) stores full content + tool metadata + reasoning fields + token_count. Sessions table (`hermes_state.py:190`) carries source/user_id/model/system_prompt/parent_session_id and timestamps + cost counters.
- `tools/session_search_tool.py:378` exposes one `session_search()` function with three modes: **discovery** (FTS5 MATCH, BM25 rank by default, see `hermes_state.py:2198`), **scroll** (±window around an anchor message, no FTS5, `session_search_tool.py:153`), **browse** (recent sessions chronologically, `:110`). CJK queries with ≥3 CJK chars routed to trigram table (`hermes_state.py:2218`); 1-2 chars fall back to `LIKE`.
- Discovery returns FTS5-highlighted `snippet`, plus bookends (first 3 + last 3 messages of session) and ±5 messages around the match (`session_search_tool.py:347-365`).
- **Eviction** is session-level only: `prune_sessions(older_than_days=90)` hard-deletes ended sessions and cascades to their messages (`hermes_state.py:2578`). Active sessions never pruned. `maybe_auto_prune_and_vacuum(retention_days=90, min_interval_hours=24)` runs at startup from CLI/gateway/cron (`hermes_state.py:3107`); VACUUM only fires if rows were pruned (`hermes_state.py:3155`). Tracking via `state_meta["last_auto_prune"]`. **No per-message TTL, no archival tier.**
- **Memory utility / hit counter — absent in main store.** No `hit_count`, `access_count`, `last_used`, or `usefulness` columns on `messages` or `sessions`. The main FTS5 path is append-on-write with zero retrieval feedback.
- The **only** subsystem with utility tracking is the `holographic` memory plugin (`plugins/memory/holographic/store.py:16-76`): a separate `memory_store.db` with a `facts` table carrying `retrieval_count INTEGER DEFAULT 0` (bumped on every successful `search_facts`, `store.py:233`), `helpful_count INTEGER DEFAULT 0` (bumped by an explicit `fact_feedback` tool call, `store.py:374`), and `trust_score REAL DEFAULT 0.5` adjusted asymmetrically (+0.05 helpful, -0.10 unhelpful, `store.py:79`, `:371`). Trust acts as a retrieval-rank multiplier (`retrieval.py:97`), and `min_trust` defaults to 0.3 as a filter floor.
- The `fact_feedback` tool is the user-of-memory signaling mechanism (`plugins/memory/holographic/__init__.py:76`). It is **agent-initiated**, not automatic — there is no implicit "you retrieved this fact and then succeeded, +1" credit assignment.

### Skill Documents (the actual self-improvement loop)

- Skill format is YAML frontmatter + Markdown body in `SKILL.md`, organized as a directory: `SKILL.md` plus optional `references/`, `templates/`, `scripts/`, `assets/` subdirs. Frontmatter has `name`, `description`, optional `version`, `platforms`, `metadata.hermes.{tags, related_skills}` (`tools/skills_tool.py:28-66` docstring, `tools/skill_manager_tool.py:217-253` validation).
- **No executable hooks in SKILL.md itself.** `scripts/` files are invoked by agent tool calls; the loader does not auto-run them. `platforms:` is a declarative filter at `skill_matches_platform()` (`tools/skills_tool.py:152`).
- **Dispatch is three-tier:**
  - Tier 1 — passive index. `build_skills_system_prompt()` (`agent/prompt_builder.py:997`) scans `~/.hermes/skills/` and builds an `<available_skills>` block of `category: name: description` entries, injected into the **stable** tier of the system prompt (`agent/system_prompt.py:169-185`). Prompt explicitly instructs: *"Before replying, scan the skills below. If a skill matches or is even partially relevant to your task, you MUST load it with skill_view(name)."*
  - Tier 2 — on-demand. Agent calls `skill_view(name)` (`tools/skills_tool.py:850`) to read the full SKILL.md body. Bumps `view_count` and `use_count` in `.usage.json` (`tools/skills_tool.py:1535-1557`).
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

Remainder of draft shows mapping table and constraints section.

TASK: Critique this research draft with exactly three sections: (1) **Gaps** — things the draft missed, (2) **Errors** — claims that appear wrong, (3) **Missing constraints** — constraints not captured.

Do NOT recommend an approach; research is terrain-mapping, not direction-picking. Your job is to surface what the terrain-map omits or mislabels.
