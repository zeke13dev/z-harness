# z-sharpen

> Last updated: 2026-06-19
> Covers source: commands/z-sharpen.md

## Overview

`/z-sharpen` is a bounded, conversational idea-sharpening on-ramp. It acts as a thinking-partner that takes a raw or vague idea and converges it into a crisp, buildable problem statement through adaptive probing and reframing. Unlike `/z-grill`, which exhaustively interrogates every dimension of a requirements space, `/z-sharpen` is deliberately limited: it escalates to pin a fuzzy dimension only when needed, and stops as soon as the idea is buildable. The artifact it writes is `GRILL.md`, using the same schema as `/z-grill`, so downstream commands (`/z-plan`, `/z-brainstorm`) can consume either without distinction.

It lives in `commands/z-sharpen.md` and runs as a `c1` conversational command — no subagent is spawned for the interview itself. The only subagent allowed during a session is a Haiku Explore call to self-serve codebase-answerable questions, so the user is never asked what the repo already states. `/z-sharpen` is also auto-invoked inline by `/z-brainstorm` during its Phase 0 sharpen-vs-skip gate when the topic is judged vague.

## Key entry points

- `commands/z-sharpen.md:1` — `/z-sharpen` — The slash command itself. Receives the raw idea via `$ARGUMENTS`; an empty argument opens with "What are you thinking about?".
- `commands/z-sharpen.md:57` — Stage 1 (Framing restate) — Restates the idea back to the user concretely in 2-3 sentences; invites correction before probing begins.
- `commands/z-sharpen.md:65` — Stage 2 (Probe/Clarify/Reframe loop) — Adaptive three-step per-turn protocol: (A) codebase-answerable self-serve via Haiku Explore, (B) conversational probe/reframe, (C) bounded escalation to pin a single fuzzy dimension with a recommended answer.
- `commands/z-sharpen.md:100` — Stage 3 (Convergence gate) — Terminates probing once three signals are clear: concrete problem, minimal scope, key open forks. User must confirm before Stage 4 proceeds.
- `commands/z-sharpen.md:118` — Stage 4 (Artifact production and handoff) — Derives slug, runs collision check via `plan-path.sh all_plan_slugs`, writes `GRILL.md`, and recommends (but never auto-dispatches) the next command.
- `commands/z-sharpen.md:162` — GRILL.md schema — Frontmatter (`generated_at`, `status: complete`, `slug`) plus seven sections: Sharpened problem, Pain evidence, Who else has this, Dumbest version that solves 80%, Killed scope, Open branches, Recommended next command.

## How it interacts with others

- `z-brainstorm` — Auto-invokes `/z-sharpen` inline during Phase 0 sharpen-vs-skip gate (D5) when the topic is deemed vague. The inline run reproduces the full z-sharpen protocol in the same conversation turn; no subagent dispatch. After convergence or abandon, z-brainstorm continues with scope-probe.
- `planning-router` — Rule 5: if `premise_underspecified` is true and `current_command` is NOT `/z-sharpen`, recommends `/z-sharpen`. The loop-prevention guard (`current_command != /z-sharpen`) is explicit in planning-router.md:146.
- `commands` (z-plan, z-grill) — `GRILL.md` is the shared artifact format. Both `/z-grill` and `/z-sharpen` write GRILL.md with the same schema; last-writer-wins on a given slug.
- `scripts` (plan-path.sh, log-event.sh) — Used for base directory resolution, slug collision detection, and the three telemetry events.

## Edge cases / gotchas

- **Bounded vs. exhaustive distinction must be preserved.** If the command finds itself wanting to probe every dimension systematically, it should stop and recommend `/z-grill` instead. The two commands serve distinct roles; conflating them makes `/z-grill` vestigial.
- **Writes GRILL.md, not BRAINSTORM.md.** `/z-brainstorm` owns BRAINSTORM.md. Downstream tooling that expects BRAINSTORM.md will not find z-sharpen output there.
- **Slug collision on precontext-only dir** (only MAP.md/BRAINSTORM.md/RESEARCH.md/GRILL.md present, no PLAN.md/SPEC.md/TASKS.md) — treated as continuation; no user prompt; new GRILL.md overwrites the old one silently.
- **Slug collision on finished-plan dir** (PLAN.md or TASKS.md exists) — requires explicit user confirmation via `AskUserQuestion` before overwriting.
- **GRILL.md schema is shared with /z-grill.** If both commands run against the same slug, the second one overwrites the first.
- **No active-plan registration.** `/z-sharpen` is not a plan-family command and does not register with the active-plan registry.
- **Abandonment writes nothing.** On user abandon at any stage, only a `sharpen_run_end` event with `status: abandoned` is emitted; no artifact is created.
- **Advisory handoff only.** The final recommendation to run `/z-plan` or `/z-brainstorm` is stated in prose — the command never auto-dispatches to either.

## Examples

- `z-sharpen "add a retry system to the overnight runner"` — starts with a non-empty topic; proceeds immediately to Stage 1 framing restate.
- `z-sharpen` (no argument) — opens with "What are you thinking about?" and discovers the topic in the first turn.
- After convergence on a vague-terrain topic where open branches survive, Stage 4 recommends `/z-brainstorm <slug>` rather than `/z-plan <slug>`.
