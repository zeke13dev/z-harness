# Z-harness retro: 20260601T183904Z-persona-rotation

**Run:** z-harness/archive/20260601T183904Z-persona-rotation
**Date:** 2026-06-02
**Status:** draft — under discussion

## Run summary
A `/z-plan` run for the persona-rotation feature with a multi-vendor consult panel. The premise was accepted with a blocker — one panel member was unbuildable because "cursor has no deepseek model" — and resolved by substituting `cursor@grok-4.3` for the deepseek slot. A gemini plan-consult ran (mode plan-consult, 2 consult phases) and the run completed with 13 tasks.

## Friction observed
- **Panel member unbuildable at runtime** — `premise_challenge {blocker: "cursor has no deepseek model; panel member unbuildable", verdict: accepted_with_blocker}` → `premise_resolved {deepseek: unavailable, substitute: cursor@grok-4.3}`. A configured persona/panel arm referenced a (provider, model) pair the provider doesn't offer, caught only manually during premise.
- **Repeat doc drift, re-prompted** — `doc_drift_acknowledged {stale_pct: 68, note: "user chose proceed-with-stale earlier this session"}`. Same staleness as the active-plan-coordination run; the user had already accepted it once this session. (Addressed by Proposal 2 in the active-plan-coordination retro — session-sticky acknowledgment; not duplicated here.)

## Proposed improvements

### Proposal 4: Validate persona-arm (provider, model) availability in `z-personas validate`
- **Symptom:** "cursor has no deepseek model; panel member unbuildable" surfaced as a premise blocker mid-run, forcing a manual substitute.
- **Root cause:** `scripts/resolve-persona.py validate` checks that bound personas exist and `compatible_roles` are known, but does not verify that each bound `model` is actually offered by its bound provider. Model is treated as a config axis (resolve-persona.py:372) with no availability check.
- **Edit target:** `scripts/resolve-persona.py` `validate` path (and its surfacing in `skills/z-personas/SKILL.md` / `commands/z-personas.md`).
- **Proposed change:** Extend `validate` to cross-check each bound (provider, model) against the provider capability source (`.z-harness/providers.json` model lists, or a documented known-models map). Report unbuildable arms as a validation failure with the offending pair, so the panel is fixed before a run rather than during premise.
- **Why this helps:** Moves "unbuildable arm" detection from mid-run premise friction to a cheap pre-run check.
- **Risk:** `providers.json` may not enumerate per-provider model lists; if no capability source exists, the check is a no-op or needs a curated map to avoid false "unavailable" reports. Confirm a capability source exists before implementing — otherwise this proposal reduces to "add model enumeration to providers.json first."

## Discussion log
- **Doc drift:** Same ~68% staleness as the active-plan-coordination run, same session. Addressed by P2 there (run-end auto doc-sync → own `/z-plan`).
- **P4 (persona-arm model validation):** User accepted at proposal time (with the flagged caveat "may be a no-op until providers.json enumerates models"). During implementation the caveat resolved against us: `.z-harness/providers.json` carries only a single `model_label` per provider, with no enumeration of available models — there is **no capability source** to validate a bound model against. Additionally the binding→provider→model resolution schema (TOML `model`/`runtime` fields, `provider@model` syntax) is not something to validate against without risking false-positive errors. Writing the check now would ship either a no-op that always passes or a guess that emits spurious failures. Per the "don't dress up a broken mechanism" principle, reclassified to Deferred.

## Decisions
- **P4 — DEFERRED (reclassified during implementation; was Accepted).** Reason: no model-capability source exists. Prerequisite before this can be implemented honestly:
  1. Add an optional `models: [..]` array to each provider entry in `providers.json` (the set of models that provider actually offers).
  2. Document the binding→(provider, model) resolution so `validate` can map a bound `model` to its provider deterministically.
  3. Then extend `scripts/resolve-persona.py:cmd_validate` to check each bound model against its provider's `models` list — firing only for providers that declare one (inert, with a surfaced notice, for those that don't).
  Suggested next action: a small `/z-plan-light` or `/z-fix` to add the `models` field + the validate check together.

**Status:** complete
