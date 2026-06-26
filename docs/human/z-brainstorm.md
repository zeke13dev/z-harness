# z-brainstorm

> Last updated: 2026-06-26
> Covers source: skills/z-brainstorm/SKILL.md, skills/z-sharpen/SKILL.md, agents/ideator-clusterer.md

## Overview

`/z-brainstorm` is cheap, opt-in pre-planning ideation. It produces `BRAINSTORM.md` as a seed for `/z-plan`; it does not produce SPEC/PLAN/TASKS. The pipeline derives a slug, initializes a run brief, runs Artifact Scout preflight, then Phase 0 runs the shared `z-sharpen` reusable inline component when no `GRILL.md` exists, parses natural-language ideator count, probes scope, builds shared scaffolding, dispatches vendor-diverse ideators, performs an anti-bias synthesis pass, and enters a natural-language discussion loop where the user can ask questions, combine directions, request re-spins/refinements, restart, abandon, or lock in a choice.

Current Phase 0 behavior is intentionally conversational but no longer a wrapper auto-invocation or a vague-topic heuristic. If `GRILL.md` is absent, `/z-brainstorm` references the shared `z-sharpen` component inline in its own orchestrator thread; the `/z-sharpen` slash-command wrapper is not invoked. A reply of `skip` or `go` uses the raw topic unchanged. A `proceed` recommendation is advisory context only, while `route_to_brainstorm` confirms this command should continue; neither result auto-dispatches another command.

## Key entry points

- `skills/z-brainstorm/SKILL.md:26` — setup: derive slug, create run/archive dirs, emit `brainstorm_run_start`, initialize Run Brief, and handle existing `BRAINSTORM.md` overwrite/archive.
- `skills/z-brainstorm/SKILL.md:76` — Artifact Scout preflight — deterministic inventory plus optional scout classifier; warning-only findings never route.
- `skills/z-brainstorm/SKILL.md:134` — Phase 0 shared sharpen + scope probe — sharpen runs before scope-probe and before Phase 1 scaffolding.
- `skills/z-brainstorm/SKILL.md:138` — `0-sharpen` — if `GRILL.md` is absent, use the shared `z-sharpen` reusable component inline; do not invoke the `/z-sharpen` wrapper or auto-dispatch `/z-plan`.
- `skills/z-brainstorm/SKILL.md:187` — `0-count`: infer `WIDE_N` from natural-language count signals; default 3, prose-many default 6, cap 20 before later wide overflow caps.
- `skills/z-brainstorm/SKILL.md:483` — Phase 1 scaffolding: doc-fetcher synthesis, optional Explore, MAP.md or legacy terrain ingestion, GRILL.md seed, `input_hash`, and archived scaffolding checkpoint.
- `skills/z-brainstorm/SKILL.md:586` — Phase 2 ideator dispatch: persona draw, three parallel ideators (Claude/general-purpose, Codex consultant-secondary, Gemini consultant-primary), five-section schema, and failure policy.
- `skills/z-brainstorm/SKILL.md:693` — Phase 2c wide mode: resolves overflow model, presents a conversational cost gate and ends the turn, dispatches overflow re-spin waves after user confirmation, then clusters N framings.
- `skills/z-brainstorm/SKILL.md:945` — `ideator-clusterer` dispatch: after all wide waves, clusters ideator IDs from `BRAINSTORM.md` into K directions; failure falls back to raw framings.
- `skills/z-brainstorm/SKILL.md:982` — Phase 3 synthesis: writes `BRAINSTORM.md`, records ideator personas, runs mandatory anti-bias check, presents ranked briefing, and hard-stops for user reply.
- `skills/z-brainstorm/SKILL.md:1149` — Phase 4 finalize: HEAVY branch ranks `(chunk, framing)` pairs and writes `chosen_pair` only on unambiguous lock-in; LIGHT/MEDIUM branch writes `chosen_framing` or handles combine/re-spin/refine/restart/abandon.
- `skills/z-brainstorm/SKILL.md:1335` — re-spin machinery: shared helper for discussion re-spins and wide overflow; supports `diverge` and `refine` modes with optional cap enforcement.
- `agents/ideator-clusterer.md:1` — Haiku read-only clustering agent used only by wide mode.

## How it interacts with others

- `doc-fetcher` — Phase 1 uses docs before Explore so ideators share current, compact repo context.
- `z-sharpen`/`GRILL.md` — Phase 0 reuses the shared z-sharpen component when `GRILL.md` is absent; prior or newly written sharpening context is included in scaffolding and in `input_hash`.
- `z-map`/`z-research` — MAP.md is the canonical terrain artifact; legacy RESEARCH.md is accepted only when it is terrain-like, not approach synthesis.
- `scope-probe` and `scope-reconciler-brainstorm` — non-fast-path scope classification and HEAVY chunk reconciliation.
- `personas-and-roles` — `brainstorm.personas` controls ideator persona draws; underflow slots run vanilla and are recorded as `<none>`.
- `cost-estimation` — wide mode uses an inline conversational cost estimate and waits for explicit user confirmation before extra ideators dispatch.
- `active-plan-registry` and Run Brief — setup registers the session and finalization records outcome/next steps.

## Edge cases / gotchas

- Phase 0 sharpening is not a specificity heuristic or wrapper auto-invocation anymore: absent `GRILL.md` means run the shared component inline, possibly ask bounded questions, and end the turn before scope probe.
- Phase 3 has a hard end-turn invariant: after writing `BRAINSTORM.md` and presenting the ranked briefing, no further tool call is allowed until the user replies.
- Wide mode's cost gate is conversational, not `AskUserQuestion`; no ideators dispatch until the user replies yes/go/proceed or adjusts N.
- A shared-component `proceed` recommendation does not launch `/z-plan`; it can be surfaced as advisory context, but `/z-brainstorm` either continues after the user's choice or stops at its own gates.
- `cheap-mixed` overflow model is gated/no-op; it logs a warning and falls back to Haiku because Codex/Antigravity model override paths are not verified.
- Wide overflow is capped at three overflow waves (maximum 9 total ideators); requests beyond the cap are explicitly reported to the user.
- HEAVY abandon writes `chosen_framing: abandoned` and omits `chosen_pair`; successful HEAVY lock-in removes `chosen_framing` and writes `chosen_pair` atomically.
- Discussion re-spins are uncapped when `RESPIN_CAP` is empty; wide overflow passes `RESPIN_CAP=3`.
- Refine mode is distinct from divergence mode: it deepens liked framing(s) and forbids switching axes.
- `ideator_personas` is always written in frontmatter, including `<none>` and failed slots.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-brainstorm.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

- `/z-brainstorm improve performance` -> asks sharpening questions first if no `GRILL.md`; after the reply, scope probe and ideation proceed.
- `/z-brainstorm give me 6 approaches to the auth redesign` -> parses `WIDE_N=6`, shows the wide cost gate, then on confirmation runs base ideators, overflow ideators, and clusterer.
- In Phase 4, `combine Codex and Gemini` drafts a synthesized five-section framing and waits for confirmation before writing `chosen_framing: synthesized`.
