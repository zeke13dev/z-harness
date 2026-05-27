# Phase 1 Scaffolding — askuser-prefs-hook

## Topic

Explicit memory handling and a human-in-the-loop hook before AskUserQuestion that tries to resolve the question from stored preferences before asking. Concrete example: "I almost always amend after audit." Should it live in human-readable config, in memories, or both? Per-project or global? How does the hook decide if a stored signal is strong enough to skip the prompt?

## Existing Infrastructure (from doc-fetcher)

### config-design

Config-design covers TOML-style dotted keys shaped as `section.key`, with env transliteration to `Z_HARNESS_<SECTION>_<KEY>`. Resolution is 4-layer: built-in defaults, global user config, repo config, environment overrides. Known keys include `schema_version`, `notify.level` (`off|approval_only|all`), and `docs.always_apply` (`always|never`). Invalid repo/env values hard-fail; invalid global values warn and fall back.

### commands

Commands covers Markdown procedure specs and routing/phase contracts. `AskUserQuestion` is used for route decisions, route-chain breaks, provider binding prompts, memory-candidate gates, uplift slug collisions, and brainstorm HEAVY selection. Skill phase patterns include Setup exporting config, doc-fetcher/doc-staleness gates, deterministic route checks before advisory routing, subagent fan-out, review gates, notification checks via `scripts/config.py should-notify`, and soft auto-memory-review phases.

No matching memory entries.

## User Pain Point (Scaffolded)

After running `/z-audit-plan` or `/z-audit-plan-style`, the user almost always immediately runs `/z-amend`. No bridge exists today; user must manually invoke `/z-amend`, answer slug-discovery questions, etc.

## Key Design Axes

1. **Storage location**: human-readable TOML config (.z-harness/config.toml) vs LLM memory (docs/llm/<slug>.json memories[]) vs both
2. **Scope**: per-project (.z-harness/) vs global (~/.config/z-harness/)
3. **Signal strength threshold**: when does a stored preference skip the prompt vs. surface with a pre-filled default
4. **Hook mechanism**: where in the skill flow does preference-resolution run

## Memory Infrastructure

- Per-concept `memories[]` arrays in `docs/llm/<slug>.json`
- Flat aggregate `docs/llm/MEMORIES-FLAT.md`
- Authored exclusively via `/z-suggest-memory`
- Fields: date, type, text, tags

## Config Infrastructure

- 4-layer TOML: built-in defaults → `~/.config/z-harness/config.toml` → `.z-harness/config.toml` → env vars
- Resolved via `scripts/config.py export-env`
- Current keys: `notify.level`, `docs.always_apply`

## Input Hash

381e0cbdd6e2a1ce
