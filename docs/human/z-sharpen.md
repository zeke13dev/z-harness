# z-sharpen

> Last updated: 2026-06-26
> Covers source: skills/z-sharpen/SKILL.md

## Overview

`/z-sharpen` is the reusable bounded idea-sharpening contract plus the user-facing slash-command wrapper. The shared component takes a raw idea or handoff/precontext, assesses clarity and surviving alternatives, may ask the highest-signal bounded clarification, returns complete `GRILL.md` content when ready, and recommends exactly one of `proceed`, `sharpen_more`, or `route_to_brainstorm`. Unlike `/z-grill`, which exhaustively interrogates every dimension of a requirements space, `/z-sharpen` is deliberately limited: it escalates to pin a fuzzy dimension only when needed, and stops as soon as the idea is buildable.

The wrapper lives in `skills/z-sharpen/SKILL.md` and runs as a `c1` conversational command. `/z-plan` and `/z-brainstorm` reuse only the inline component contract; they must not depend on wrapper-only slug derivation, collision checks, telemetry, empty-topic bootstrap, or final handoff behavior. The component and wrapper never write `BRAINSTORM.md` and never auto-dispatch `/z-plan` or `/z-brainstorm`; handoff is advisory prose plus `GRILL.md`.

## Key entry points

- `skills/z-sharpen/SKILL.md:23` — surface split — reusable inline component contract vs `/z-sharpen` command wrapper.
- `skills/z-sharpen/SKILL.md:39` — surface boundary rules — component does not own slugs, collisions, telemetry, or multi-turn wrapper lifecycle.
- `skills/z-sharpen/SKILL.md:55` — reusable inline component contract — caller-owned prompt/precontext/destination inputs; no interview subagent.
- `skills/z-sharpen/SKILL.md:113` — component outputs — clarity assessment, alternatives assessment, `proceed|sharpen_more|route_to_brainstorm`, and `GRILL.md` content.
- `skills/z-sharpen/SKILL.md:165` — recommendation mapping — `proceed` maps to advisory `/z-plan`; `route_to_brainstorm` maps to advisory `/z-brainstorm`.
- `skills/z-sharpen/SKILL.md:173` — command wrapper — user-facing lifecycle, empty-topic bootstrap, slug/collision behavior, telemetry, final writes, and handoff.
- `skills/z-sharpen/SKILL.md:217` — slug derivation and collision check — precontext-only dirs continue; finished-plan dirs require confirmation.
- `skills/z-sharpen/SKILL.md:255` — write `GRILL.md` — writes only on convergence; never writes `BRAINSTORM.md`.
- `skills/z-sharpen/SKILL.md:264` — advisory handoff — recommends next command but never invokes it.

## How it interacts with others

- `z-brainstorm` — Uses only the reusable inline component in Phase 0 when `GRILL.md` is absent. It does not invoke the `/z-sharpen` wrapper, does not inherit wrapper slug/collision/telemetry behavior, and does not auto-dispatch `/z-plan` when the component says `proceed`.
- `z-plan` and `planning-router` — Post-artifact route checks and planning-router can recommend `/z-sharpen` for question-heavy or underspecified artifacts. The recommendation is surfaced through a route gate; the caller never auto-dispatches the command.
- `commands` (z-plan, z-grill) — `GRILL.md` is the shared artifact format. Both `/z-grill` and `/z-sharpen` write GRILL.md with the same schema; last-writer-wins on a given slug.
- `scripts` (plan-path.sh, log-event.sh) — Used by the wrapper for base directory resolution, slug collision detection, and telemetry.

## Edge cases / gotchas

- **Bounded vs. exhaustive distinction must be preserved.** If the command finds itself wanting to probe every dimension systematically, it should stop and recommend `/z-grill` instead. The two commands serve distinct roles; conflating them makes `/z-grill` vestigial.
- **Writes GRILL.md, not BRAINSTORM.md.** `/z-brainstorm` owns BRAINSTORM.md. Downstream tooling that expects BRAINSTORM.md will not find z-sharpen output there.
- **Reusable component is not the wrapper.** `/z-plan` and `/z-brainstorm` may call the shared contract, but wrapper-only behavior (empty-topic bootstrap, slug resolution, collision prompts, telemetry names, and final handoff) stays in the `/z-sharpen` command.
- **Component output is advisory at routing boundaries.** `proceed` and `route_to_brainstorm` recommend next commands; callers surface choices and must not auto-dispatch them.
- **Slug collision on precontext-only dir** (only MAP.md/BRAINSTORM.md/RESEARCH.md/GRILL.md present, no PLAN.md/SPEC.md/TASKS.md) — treated as continuation; no user prompt; new GRILL.md overwrites the old one silently.
- **Slug collision on finished-plan dir** (PLAN.md or TASKS.md exists) — requires explicit user confirmation via `AskUserQuestion` before overwriting.
- **GRILL.md schema is shared with /z-grill.** If both commands run against the same slug, the second one overwrites the first.
- **No active-plan registration.** `/z-sharpen` is not a plan-family command and does not register with the active-plan registry.
- **Abandonment writes nothing.** On user abandon at any stage, only a `sharpen_run_end` event with `status: abandoned` is emitted; no artifact is created.
- **Advisory handoff only.** The final recommendation to run `/z-plan` or `/z-brainstorm` is stated in prose — the command never auto-dispatches to either.

## Examples

- `z-sharpen "add a retry system to the overnight runner"` — starts with a non-empty topic and runs the wrapper around the shared component.
- `z-sharpen` (no argument) — opens with "What are you thinking about?" and discovers the topic in the first turn.
- After convergence on a vague-terrain topic where open branches survive, the component returns `route_to_brainstorm` and the wrapper recommends `/z-brainstorm <slug>` without invoking it.
