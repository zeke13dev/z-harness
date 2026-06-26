---
name: z-sharpen
disable-model-invocation: false
description: Reusable bounded idea-sharpening contract plus `/z-sharpen` wrapper. The
  inline component assesses prompt clarity and surviving alternatives, emits GRILL.md
  content, and recommends proceed/sharpen_more/route_to_brainstorm. The command wrapper
  adds slug resolution, collision handling, telemetry, and lifecycle.
argument-hint: "[raw idea — or blank to start the conversation]"
runtime: c1
driver_features_required:
  - subagent      # Explore self-serve for codebase-answerable questions
  - ask_user      # empty-topic bootstrap + recommended-answer confirmations (front-end command; the
                  # no-prompt rule is scoped to /z-brainstorm only)
unsupported_driver_behavior: explicit_gate
---

You are running the **z-harness `/z-sharpen`** conversational idea-sharpening command.

Topic (from `$ARGUMENTS`):

$ARGUMENTS

`/z-sharpen` contains two separate surfaces:

1. **Reusable inline component contract** — a bounded sharpening procedure that can be
   referenced by `/z-plan`, `/z-brainstorm`, or this wrapper. It takes prompt/precontext
   input, assesses clarity and alternatives, returns `GRILL.md` content, and recommends
   exactly one of `proceed`, `sharpen_more`, or `route_to_brainstorm`.
2. **`/z-sharpen` command wrapper** — the user-facing slash command. It owns empty-topic
   bootstrap, conversational lifecycle, slug derivation, collision handling, telemetry,
   final file writes, and advisory handoff.

`/z-plan` and `/z-brainstorm` callers reference **only** the reusable inline component
contract below. They must not depend on wrapper-only slug derivation, collision checks,
telemetry event names, session lifecycle, empty-topic bootstrap, or final handoff behavior.
Those callers already own their slug/session context; if they need logging, collision
checks, or pacing, they implement that behavior in their own command surface.

### Surface boundary rules

- The reusable component is pure orchestration guidance plus `GRILL.md` content. It does
  not create or choose plan directories, derive stable run slugs, check existing
  artifacts, emit telemetry, or own a multi-turn session.
- If a caller supplies a destination context, the component may perform that
  caller-directed `GRILL.md` write; the caller still owns whether and where the artifact
  is written.
- The wrapper may use the component's assessment and markdown exactly as returned, but any
  slug, collision, telemetry, abandonment, confirmation, and handoff behavior is wrapper
  state layered around that reusable result.

**Invariant — bounded vs. exhaustive:** z-sharpen = adaptive + bounded;
`/z-grill` = exhaustive + deliberate. If you find yourself wanting to grill every
dimension systematically, stop and recommend `/z-grill` instead.

## Surface 1 — Reusable inline component contract

Use this section when another command says it is invoking the shared z-sharpen contract.
This component is inline: it runs in the caller's orchestrator thread. Do not spawn a
subagent to conduct the interview. Explore is the only subagent allowed, used solely to
self-serve codebase-answerable questions so the user is not asked what the repo already
states.

### Inputs

- **Prompt input (required):** the raw idea, task, handoff text, or topic the caller wants
  sharpened.
- **Precontext input (optional):** caller-supplied context such as existing `GRILL.md`
  text, `BRAINSTORM.md` framing, `MAP.md`/`RESEARCH.md` summaries, handoff notes,
  constraints, known non-goals, or codebase facts. The component consumes precontext as
  already-resolved context; it does not derive slugs, inspect plan directories for
  collisions, or decide whether a caller's precontext is fresh.
- **Destination context (optional):** a caller-owned target path if the caller wants the
  component to write `GRILL.md` directly. If omitted, return the complete markdown content
  for the caller to write.
- **Interaction policy (caller-owned):** whether the caller may ask the user a free-text
  clarification. The component can recommend `sharpen_more`; the caller decides whether to
  end the turn, ask inline, skip, or abort according to that command's lifecycle.

### Procedure

1. **Frame the current understanding.** Restate the idea in 2-3 sentences: actors, pain,
   approximate scope, and any constraints supplied by precontext.
2. **Self-serve codebase-answerable gaps.** Before asking the user, ask whether the gap can
   be answered by looking at the repo.

   <!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
        requirement and skip the Explore Agent() call. If skipped, ask the user the
        question directly instead of self-answering. Silent omission is forbidden. -->
   ```
   Agent(
     subagent_type="general-purpose",
     model="haiku",
     description="Self-serve: <one-line question>",
     prompt="<question about the codebase>\nrepo_root: <abs path>"
   )
   ```

   Log or record the self-answered question using the caller's own mechanism. Do not use
   `/z-sharpen` wrapper telemetry from this component.
3. **Assess clarity.** Decide whether the available input can clearly state:
   - the concrete problem being solved;
   - the minimal scope, including what is intentionally cut;
   - the evidence or pain that makes the problem worth solving;
   - the genuinely open forks, if any.
4. **Assess alternatives.** Decide whether surviving alternatives are minor planning
   choices or materially different framings. Materially different framings are alternatives
   that would change the problem statement, success criterion, target user, architecture
   direction, or first task batch.
5. **Probe only the highest-signal gap.** If one bounded clarification would likely make
   the idea buildable, recommend a concrete answer and ask the caller/user to confirm or
   correct it. Do not run a checklist. Do not interrogate every dimension.

### Component outputs

Return all of the following to the caller:

1. **Clarity assessment:** `clear` or `unclear`, plus the missing dimension if unclear.
2. **Alternatives assessment:** `single_path`, `minor_open_forks`, or
   `material_alternatives`, plus a one-line rationale.
3. **Recommendation output:** exactly one of:
   - `proceed` — the problem is buildable and any open forks are minor enough for planning.
   - `sharpen_more` — the prompt is still under-specified, and a focused clarification is
     the next best move.
   - `route_to_brainstorm` — materially different framings survived sharpening; parallel
     ideation should run before planning.
4. **GRILL.md output:** on `proceed` or `route_to_brainstorm`, provide a complete
   `GRILL.md` using the schema below. On `sharpen_more`, do not write a final artifact;
   return the best current draft fields and the next clarification to ask.

If the caller supplied a destination context and the recommendation is `proceed` or
`route_to_brainstorm`, write the destination `GRILL.md`. Otherwise, return the markdown to
the caller. The component never writes `BRAINSTORM.md`.

```markdown
---
generated_at: <iso 8601 UTC timestamp>
status: complete
slug: <caller-owned slug, or "inline" if no slug exists>
---

# GRILL — <caller-owned slug or short title>

## Sharpened problem
<1 paragraph — the buildable problem statement. Concrete, not abstract.>

## Pain evidence
<the specific recent painful moment(s), frequency, cost, who feels it>

## Who else has this
<just-me / named others + how they cope today; or "unknown — solo papercut">

## Dumbest version that solves 80%
<the minimal thing that kills most of the pain>

## Killed scope
<each piece cut from the user's original mental model + why it was cut>

## Open branches
<genuinely undecided forks deferred to planning/brainstorming; or "none">

## Recommended next command
<`/z-plan <slug>` or `/z-brainstorm <slug>` + one-line rationale (advisory only)>
```

Recommendation mapping:

- `proceed` maps to **`/z-plan <slug>`** when the terrain is known and the remaining work
  is decision-making plus task breakdown.
- `route_to_brainstorm` maps to **`/z-brainstorm <slug>`** when `## Open branches`
  contains materially different framings that would benefit from parallel ideation.
- `sharpen_more` maps to no next command yet.

## Surface 2 — `/z-sharpen` command wrapper

This wrapper invokes the reusable inline component above as a user-facing conversational
command. The wrapper, not the reusable component, owns session lifecycle, slug/collision
behavior, telemetry, final writes, and user-visible handoff.

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What are you thinking about?" via their native channel. Silent omission is
     forbidden. -->
**If the topic above is empty or whitespace**, open with: "What are you thinking
about?" The entire conversation discovers the topic.

### Setup

1. **Resolve the plans base:**
   ```bash
   PLANS_BASE="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir)"
   mkdir -p "$PLANS_BASE"
   ```
2. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-sharpen`.
3. **Log run start:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_run_start \
     "$(printf '{"topic":"%s","command":"/z-sharpen"}' "<original user prompt>")"
   ```

### Wrapper lifecycle

1. Start from `$ARGUMENTS` or the empty-topic answer.
2. Invoke the reusable inline component with:
   - prompt input = the current topic/conversation summary;
   - precontext input = any user-supplied context already present in the conversation;
   - no destination context until slug/collision resolution succeeds.
3. If the component returns `sharpen_more`, ask one focused conversational question with a
   recommended answer, wait for the user's free-text reply, and invoke the component again
   with the updated prompt/precontext. This is a single-threaded wrapper lifecycle; do not
   spawn a subagent to run the interview.
4. Stop probing when the component returns `proceed` or `route_to_brainstorm`. Summarize the
   converged problem and ask the user to confirm: "Here's what I've got — does this capture
   it, or is there something important I'm missing?" Proceed to artifact production only on
   user confirmation.
5. If the user abandons before confirmation, run the abandonment path. No artifact is
   written.

### Slug derivation and collision check

Only the command wrapper performs this section.

1. **Derive a provisional slug** from the sharpened problem: short kebab-case, 2-4 words.

2. **Collision check (unconditional).** Run:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs
   ```
   to list existing slugs. If the provisional slug matches an existing slug dir:
   - **Precontext-only slug dir** (only `MAP.md`, `BRAINSTORM.md`, `RESEARCH.md`, and/or
     `GRILL.md` present — no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no
     prompt, reuse the slug. A fresh `GRILL.md` write overwrites any prior one (note this
     in your summary).
   <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug-collision
        confirmation question (overwrite / pick a variant) via their native channel.
        Silent omission is forbidden. -->
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): **collision.** Prompt the
     user via `AskUserQuestion` to either overwrite (write `GRILL.md` into the existing dir)
     or pick a variant slug.

   Record whether a collision occurred in `$COLLISION` (`true` or `false`) for telemetry.

3. **Resolve paths:**
   ```bash
   export Z_HARNESS_SLUG=<resolved-slug>
   export Z_HARNESS_PLAN_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")"
   mkdir -p "$Z_HARNESS_PLAN_DIR"
   ```

### Log convergence

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_convergence \
  "$(printf '{"slug":"%s","collision":%s,"recommendation":"%s"}' "$Z_HARNESS_SLUG" "$COLLISION" "<proceed|route_to_brainstorm>")"
```

### Write GRILL.md

Invoke the reusable inline component one final time or reuse its latest returned markdown,
now with destination context `$Z_HARNESS_PLAN_DIR/GRILL.md` and slug
`$Z_HARNESS_SLUG`. Write the exact `GRILL.md` schema above. **Never write
`BRAINSTORM.md`** — `/z-brainstorm` owns that artifact.

`GRILL.md` is written only on convergence. An abandoned session writes nothing.

### Handoff (advisory, NEVER auto-dispatch)

Recommend the next command — but **do not invoke it**. State the recommendation in one or
two sentences, point at the written `GRILL.md` path, and stop. The user runs the next
command themselves.

- Recommend **`/z-plan <slug>`** when the component returned `proceed`.
- Recommend **`/z-brainstorm <slug>`** when the component returned
  `route_to_brainstorm`.

### Log run end

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_run_end \
  "$(printf '{"slug":"%s","status":"complete"}' "$Z_HARNESS_SLUG")"
```

## Abandonment

If the user abandons at any stage before confirmed convergence, log and exit cleanly:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_run_end \
  "$(printf '{"slug":"","status":"abandoned"}')"
```

No artifact is written on abandonment.
