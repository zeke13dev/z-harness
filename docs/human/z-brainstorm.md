# z-brainstorm

> Last updated: 2026-07-09
> Covers source: skills/z-brainstorm/SKILL.md, agents/ideator-clusterer.md

## Overview

`/z-brainstorm` is cheap, opt-in pre-planning ideation. It produces `BRAINSTORM.md` as a seed for `/z-plan`; it does not produce SPEC/PLAN/TASKS. The pipeline derives a slug, initializes a run brief, runs Artifact Scout preflight, then Phase 0 runs the shared `z-sharpen` reusable inline component when no `GRILL.md` exists, parses natural-language ideator count, probes scope, builds shared scaffolding, dispatches vendor-diverse ideators, performs an anti-bias synthesis pass, and enters a natural-language discussion loop where the user can ask questions, combine directions, request re-spins/refinements, restart, abandon, or lock in a choice.

Current Phase 0 behavior is intentionally conversational but no longer a wrapper auto-invocation or a vague-topic heuristic. If `GRILL.md` is absent, `/z-brainstorm` references the shared `z-sharpen` component inline in its own orchestrator thread; the `/z-sharpen` slash-command wrapper is not invoked. A reply of `skip` or `go` uses the raw topic unchanged. A `proceed` recommendation is advisory context only, while `route_to_brainstorm` confirms this command should continue; neither result auto-dispatches another command. (`z-sharpen` is documented separately at `docs/human/z-sharpen.md` — it is no longer treated as a source file this doc covers, only as a dependency.)

## Key entry points

- `skills/z-brainstorm/SKILL.md:26` — setup: derive slug, create run/archive dirs, emit `brainstorm_run_start`, initialize Run Brief, and handle existing `BRAINSTORM.md` overwrite/archive.
- `skills/z-brainstorm/SKILL.md:76` — Artifact Scout preflight — deterministic inventory plus optional scout classifier; warning-only findings never route.
- `skills/z-brainstorm/SKILL.md:134` — Phase 0 — Scope probe — sharpen runs before scope-probe and before Phase 1 scaffolding (heading was renamed from "Shared sharpen + scope probe" to "Scope probe"; behavior unchanged).
- `skills/z-brainstorm/SKILL.md:138` — `0-sharpen` — if `GRILL.md` is absent, use the shared `z-sharpen` reusable component inline; do not invoke the `/z-sharpen` wrapper or auto-dispatch `/z-plan`.
- `skills/z-brainstorm/SKILL.md:187` — `0-count`: infer `WIDE_N` from natural-language count signals; default 3, prose-many default 6, cap 20 before later wide overflow caps.
- `skills/z-brainstorm/SKILL.md:483` — Plan Route Check — deterministic routing signals plus optional `planning-router` classifier; runs after Phase 1 scaffolding, before Phase 2 ideator dispatch.
- `skills/z-brainstorm/SKILL.md:526` — Phase 1 — Scaffolding: doc-fetcher synthesis, optional Explore-agent synthesis, ingestion of `/z-explore --depth=deep`-owned `MAP.md` or a legacy terrain artifact, GRILL.md seed, `input_hash`, and archived scaffolding checkpoint.
- `skills/z-brainstorm/SKILL.md:630` — Phase 2 — Parallel ideator dispatch: persona draw, three parallel ideators (Claude/general-purpose, Codex consultant-secondary, Gemini consultant-primary), five-section schema, and failure policy.
- `skills/z-brainstorm/SKILL.md:737` — Phase 2c wide mode: resolves overflow model, presents a conversational cost gate and ends the turn, dispatches overflow re-spin waves after user confirmation.
- `skills/z-brainstorm/SKILL.md:989` — Phase 2c-5 `ideator-clusterer` dispatch: after all wide waves, clusters ideator IDs from `BRAINSTORM.md` into K directions; failure falls back to raw framings.
- `skills/z-brainstorm/SKILL.md:1026` — Phase 3 — Synthesis + mandatory anti-bias check: writes `BRAINSTORM.md`, records ideator personas, runs mandatory anti-bias check, presents ranked briefing, and hard-stops for user reply.
- `skills/z-brainstorm/SKILL.md:1193` — Phase 4 — Finalize: HEAVY branch ranks `(chunk, framing)` pairs and writes `chosen_pair` only on unambiguous lock-in; LIGHT/MEDIUM branch writes `chosen_framing` or handles combine/re-spin/refine/restart/abandon.
- `skills/z-brainstorm/SKILL.md:1379` — Re-spin machinery: shared helper for discussion re-spins and wide overflow; supports `diverge` and `refine` modes with optional cap enforcement.
- `agents/ideator-clusterer.md:1` — Haiku read-only clustering agent used only by wide mode; clusters N peer framings into K distinct directions by core hypothesis, never picks a winner, never writes files.

## How it interacts with others

- `doc-fetcher` — Phase 1 uses docs before Explore so ideators share current, compact repo context.
- `z-sharpen`/`GRILL.md` — Phase 0 reuses the shared z-sharpen component when `GRILL.md` is absent; prior or newly written sharpening context is included in scaffolding and in `input_hash`. `z-sharpen` is now tracked as its own concept doc; this doc treats it purely as a dependency.
- `/z-explore --depth=deep`/`MAP.md` — current terrain/MAP.md production belongs to `/z-explore --depth=deep`; `/z-brainstorm` consumes that artifact as optional terrain context. `/z-research` composes terrain plus brainstorm outputs, and `/z-map` is legacy only. Legacy `RESEARCH.md` is accepted only when terrain-like, not approach synthesis.
- `scope-probe` and `scope-reconciler-brainstorm` — non-fast-path scope classification and HEAVY chunk reconciliation.
- `personas-and-roles` — `brainstorm.personas` controls ideator persona draws; underflow slots run vanilla and are recorded as `<none>`.
- `cost-estimation` — wide mode uses an inline conversational cost estimate and waits for explicit user confirmation before extra ideators dispatch.
- `active-plan-registry` and Run Brief — setup registers the session and finalization records outcome/next steps.
- `/z-plan` and `/z-research` — both consume `BRAINSTORM.md` as an optional seed input.

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
- Section headings and line numbers shift over time as the file grows (e.g. "Plan Route Check" now sits before "Phase 1 — Scaffolding" at line 483, and Phase 1 itself starts at 526, not 483) — treat `entry_points` line numbers as approximate pointers, re-grep `^## ` / `^### ` headings if a citation looks off.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-brainstorm.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

- `/z-brainstorm improve performance` -> asks sharpening questions first if no `GRILL.md`; after the reply, scope probe and ideation proceed.
- `/z-brainstorm give me 6 approaches to the auth redesign` -> parses `WIDE_N=6`, shows the wide cost gate, then on confirmation runs base ideators, overflow ideators, and clusterer.
- In Phase 4, `combine Codex and Gemini` drafts a synthesized five-section framing and waits for confirmation before writing `chosen_framing: synthesized`.
