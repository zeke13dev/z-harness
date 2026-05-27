# Phase 1 — Scaffolding

## Topic

explicit memory handling and a human-in-the-loop hook before AskUserQuestion that tries to resolve the question from stored preferences before asking. Example: "I almost always amend after audit." Should it live in human-readable config, in memories, or both? Per-project or global? How does the hook decide if a stored signal is strong enough to skip the prompt?

## Doc-fetcher synthesis (key findings)

### AskUserQuestion usage today
- Plan amendment (`/z-amend` slug discovery, impact-analysis approval)
- Memory review loops (Phase 9/7/10 — sequential candidate accept/skip)
- Brainstorm HEAVY Phase 4 (chunk × framing matrix selection)
- Plan-router contextual route confirmation
- Final-review action gate, /z-maintain-docs apply gate, /z-uplift component gate, etc.

### Existing config infrastructure (already shipped, slice 1)
- 4-layer TOML resolution: built-in defaults → `~/.config/z-harness/config.toml` → `.z-harness/config.toml` → `Z_HARNESS_<SECTION>_<KEY>` env vars
- Resolved via `scripts/config.py export-env`
- Slice 1 keys: `notify.level`, `docs.always_apply`
- File: `scripts/config.py:238-389`, docs at `docs/human/config.md`

### Memory storage
- Per-concept `memories[]` arrays in `docs/llm/<slug>.json`
- Flat aggregate at `docs/llm/MEMORIES-FLAT.md` (auto-regenerated)
- Fields: `date`, `type`, `text`, `tags`
- Authoring path is exclusively `/z-suggest-memory`

### No pre-AskUser hook exists today
- Commands invoke AskUserQuestion directly
- Some "skip-if-single-candidate" defaults (e.g., /z-amend with one slug)
- No mechanism to consult stored preferences before prompting
- `/z-amend` does NOT auto-trigger after audit; user must invoke manually

### Audit → amend flow specifically
- `/z-audit-plan-style` produces `PLAN_STYLE_AUDIT.md` (read-only)
- `/z-amend` applies findings (mutation-focused; user invokes)
- No bridge between them — this is the friction the user is naming
