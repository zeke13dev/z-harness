# Phase 0 — Premise check

## Inputs
- BRAINSTORM.md (chosen_framing: codex), generated 2026-05-27T17:04:48Z

## Goal as understood
Ship the first slice of a layered TOML config system for z-harness:
1. `scripts/config.py` with `get | export-env | ensure-defaults | explain` subcommands.
2. Layered precedence: built-in defaults (Python) → `~/.config/z-harness/config.toml` → repo `.z-harness/config.toml` → env override.
3. Two migrated knobs: `notify.level` (replaces `Z_HARNESS_NOTIFY`) + `docs.always_apply` (gates doc-fetcher in optional flows).
4. Slim README to pitch + install + 3 quickstart commands + pointers (not abstract "less stuff").
5. Persist design as `docs/human/config.md` + `docs/llm/config-design.json` wired into INDEX.json.
6. Emit `config_resolved` events (precedent: providers.json `provider_shadowed`).

## Challenges considered, resolved
1. **Is notify.level the right MVP knob?** Yes, in combination with docs.always_apply. notify.level smoke-tests the loader plumbing end-to-end on a no-stakes migration (already env-driven); docs.always_apply proves the user-visible design pattern. Different purposes, not redundant.
2. **README-slim risk (Gemini).** Mitigated by defining the target shape concretely (pitch + install + 3 quickstart commands + pointers) rather than slimming abstractly. The cut content moves into docs/human/, which agents can already find via INDEX.json.

## Premise: accepted.

## Out of scope (deferred to slice 2/3)
- Prompt-fragment injection mechanism.
- Migration of consult prefs, escalation budgets, archive retention.
- Refactoring 21 skills.
- `notify` config beyond `level` (no per-event filtering yet).
