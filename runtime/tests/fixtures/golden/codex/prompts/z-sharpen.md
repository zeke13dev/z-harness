# /z-sharpen

You are running the **z-harness `/z-sharpen`** conversational idea-sharpening command.

Topic (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What are you thinking about?" via their native channel. Silent omission is
     forbidden. -->
**If the topic above is empty or whitespace**, open with: "What are you thinking
about?" The entire conversation discovers the topic.

`/z-sharpen` is a **bounded** conversational on-ramp — a thinking-partner conversation
that adaptively refines a raw idea into a crisp, buildable problem statement. It starts
conversational (reframe/probe), escalates to pin individual fuzzy dimensions only as needed,
and stops once the idea is buildable. It never exhaustively interrogates every dimension —
that is `/z-grill`'s job.

**Invariant — bounded vs. exhaustive:** z-sharpen = adaptive + bounded;
`/z-grill` = exhaustive + deliberate. If you find yourself wanting to grill every
dimension systematically, stop and recommend `/z-grill` instead.

## Setup

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

## Protocol (inline — no subagents for the interview itself)

The conversation runs inline in this orchestrator thread. Do not spawn a subagent to run
the interview. Explore is the only subagent allowed, used to self-serve codebase-answerable
questions so the user is not asked what the repo already states.

### Stage 1 — Framing restate

Restate the idea back to the user in your own words. Make it concrete: name the actors,
the pain, and the approximate scope as you understand them. This is a check, not a lecture —
keep it brief (2-3 sentences). Invite correction.

### Stage 2 — Probe / Clarify / Reframe loop

Adaptively explore the idea. This stage is **not** a structured checklist — follow the
thread with the highest signal, not a fixed order.

**For each turn:**

**Step A — Codebase-answerable?** Ask yourself: can this be answered by looking at the
codebase rather than the user? If yes, self-serve it:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     <!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
     question directly instead of self-answering. Silent omission is forbidden. -->
```
<!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
  subagent_type="general-purpose",
  model="haiku",
  description="Self-serve: <one-line question>",
  prompt="<question about the codebase>\nrepo_root: <abs path>"
)
```
Log the self-answered question and continue. Do NOT ask the user about it.

**Step B — Probe or reframe conversationally.** Offer a reframing, ask a clarifying
question, or surface a tension you see. Keep it conversational — one thread at a time.

**Step C — Adaptive escalation (bounded).** If a particular dimension stays fuzzy after
a conversational exchange, **escalate** for that dimension only: state a recommended answer
and ask the user to confirm or correct it. Example: "I'm reading this as [X] — does that
match, or is it more like [Y]?" This is a single-dimension pin, not a full interrogation.

Resume conversational probing after each pin.

**Codebase self-serve examples (Step A):** Does this integration point already exist? Does
this data model already have the field? Is there an existing command that covers this?
These do not count against the bounded-escalation budget.

### Stage 3 — Convergence gate

The idea is buildable when you can clearly articulate:
- The concrete, specific problem being solved (not abstract);
- The minimal scope (what's in and what's cut);
- The key open forks (genuinely deferred vs. known).

**Adaptive termination:** stop probing once those three things are clear. Do not continue
probing just to cover all possible dimensions — if it's buildable, stop.

When you believe the idea is sharp enough, summarize what you've converged on and ask the
user to confirm: "Here's what I've got — does this capture it, or is there something
important I'm missing?" Proceed to Stage 4 only on user confirmation.

If the user signals convergence themselves ("that's it", "let's write it up", similar),
accept it and proceed to Stage 4.

### Stage 4 — Artifact production and handoff

Only reached on convergence. On abandonment, exit cleanly — no artifact written.

#### Slug derivation and collision check

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

#### Log convergence

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_convergence \
  "$(printf '{"slug":"%s","collision":%s}' "$Z_HARNESS_SLUG" "$COLLISION")"
```

#### Write GRILL.md

Write `$Z_HARNESS_PLAN_DIR/GRILL.md` using the EXACT schema `/z-grill` already produces.
**Never write BRAINSTORM.md** — `/z-brainstorm` owns that artifact.

```markdown
---
generated_at: <iso 8601 UTC timestamp>
status: complete
slug: <resolved-slug>
---

# GRILL — <resolved-slug>

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
<genuinely undecided forks deferred to planning; or "none">

## Recommended next command
<`/z-plan <slug>` or `/z-brainstorm <slug>` + one-line rationale (advisory only)>
```

GRILL.md is written only on convergence. An abandoned session writes nothing.

#### Handoff (advisory, NEVER auto-dispatch)

Recommend the next command — but **do not invoke it**. State the recommendation in one or
two sentences, point at the written `GRILL.md` path, and stop. The user runs the next
command themselves.

- Recommend **`/z-plan <slug>`** when the terrain is known and the path is clear enough
  that the remaining work is decision-making + task breakdown.
- Recommend **`/z-brainstorm <slug>`** when multiple plausible framings survived sharpening
  — i.e., `## Open branches` carries forks that would materially change the plan, and
  parallel ideation would help before planning.

#### Log run end

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_run_end \
  "$(printf '{"slug":"%s","status":"complete"}' "$Z_HARNESS_SLUG")"
```

## Abandonment

If the user abandons at any stage, log and exit cleanly:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" sharpen_run_end \
  "$(printf '{"slug":"","status":"abandoned"}')"
```

No artifact is written on abandonment.
