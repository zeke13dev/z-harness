---
description: "Live depth-first interrogation that sharpens a vague idea into a buildable problem statement. Asks ONE question at a time, always states a recommended answer, self-serves codebase-answerable questions via Explore, and terminates adaptively. Writes..."
role: workflow
---

You are running **z-harness `/z-grill`** — a live, depth-first interrogation. You take a vague idea and grill it, ONE question at a time, until it becomes a problem statement someone could actually build against. Then you write `GRILL.md` as precontext for `/z-plan` or `/z-brainstorm`.

This is **not** a subagent flow. The interview happens inline, in this orchestrator thread — that is what lets each answer reshape the next question. Do not spawn a subagent to run the interview.

Topic (from `$ARGUMENTS`):

$ARGUMENTS

## Setup

1. **Resolve the plans base.** This anchors both the staging file and the eventual artifact path. Create the base if it does not exist (empty repo / first run):
   ```bash
   PLANS_BASE="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir)"
   mkdir -p "$PLANS_BASE"
   export Z_HARNESS_GRILL_STAGING="$PLANS_BASE/.grill-pending.md"
   ```
2. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-grill`.
3. **Resume check.** If `$Z_HARNESS_GRILL_STAGING` already exists, a prior `/z-grill` was abandoned mid-interview. Read it, summarize where the prior session left off, and continue the interview from there (do not restart the tree). The staging file is the resumable interview state. If it does not exist, create it with a header line and an empty `## Interview log` section.
4. **Version stamp + log run start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["topic"] = sys.argv[2]; v["command"] = "z-grill"
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" grill_run_start "$START_PAYLOAD"
   ```
5. Notification policy: see [docs/human/config.md](docs/human/config.md) (`notify.level` key). `/z-grill` is interactive by nature — push only on finalize.
6. Initialize an in-thread question counter `N=0`. It increments only on questions actually **asked of the user** (codebase-self-answered questions do not increment the user-facing count, but they are logged with `self_answered: true`).

## The decision tree (what "sharp" means)

A problem statement is buildable when these branches are resolved. Walk them **depth-first** — resolve a dependency before its dependent. Do not march through them in list order; let each answer redirect you to the highest-impact unresolved branch.

1. **Real pain.** What concrete, recent, painful moment triggered this? (No abstractions — a specific instance.)
2. **Pain magnitude.** How often, how costly, who feels it? Is this a papercut or a fire?
3. **Audience.** Just you, or do others hit this? If others, who — and have they complained, worked around it, or built something themselves?
4. **The 80% version.** What is the dumbest thing that solves 80% of the pain? (This is where most scope dies.)
5. **Killable scope.** Everything in the user's mental model that is NOT in the 80% version — and why each piece is cut.
6. **Hard constraints.** What can't change? (Existing system, data shape, integration point, deadline.) Many of these are **codebase-answerable** — self-serve them.
7. **Success signal.** How would the user know, concretely, that the thing worked?
8. **Open branches.** Genuinely undecided forks the user wants deferred to `/z-plan` or `/z-brainstorm`.

A branch is "high-impact" if leaving it unresolved would materially change the eventual plan. Termination is about high-impact branches, not about covering all eight.

## Phase 1 — Cold open (empty-args only)

**If the topic above is empty or whitespace**, you have nothing to grill yet. Open with a single broad question to seize a thread, then immediately switch to depth-first tree-walking.

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface this cold-open
     question via their native channel and accept a text reply. Silent omission
     is forbidden. -->
Use `AskUserQuestion`: "What's bugging you lately — what's the thing you keep wishing existed or worked differently?" Recommended framing to offer the user: "Give me the most recent specific moment it annoyed you, not the abstract version." Treat the reply as the seed topic and proceed to Phase 2.

**If a topic was provided**, SKIP this phase entirely. Do not cold-open. Go straight to Phase 2 and start grilling the provided topic.

## Phase 2 — The interrogation loop (inline, one question at a time)

This is the core. Loop until the termination check (below) fires. Each iteration handles exactly ONE branch question.

For the current highest-impact unresolved branch:

**Step A — Codebase-answerable?** Ask yourself: can this be answered by looking at the code rather than asking the user? (Hard constraints, existing system shape, "does X already exist", integration points — these usually can.) If yes, **do not ask the user.** Self-serve it:

<!-- RUNTIME-GATE: subagent; non-supporting drivers must surface this dispatch
     <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     question directly instead of self-answering. Silent omission is forbidden. -->
```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="Explore",
  model: "haiku",
  description="Grill self-answer: <one-line question>",
  prompt="<TARGETED codebase question that resolves this branch>\n\nReturn the concrete answer with file:line citations. Be terse — this answers one interview question."
)
```

Record the answer to the staging file, then log the self-answer (the user-facing counter `N` does NOT increment):
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" grill_question \
  "$(printf '{"n":%d,"self_answered":true}' "$N")"
```
Then continue to the next branch. **Do not ask the user a question the codebase already answers** — that is a hard invariant.

**Step B — Ask the user (one question only).** If the branch is genuinely a judgment/preference/intent call that only the user can answer, increment `N` and ask exactly ONE question. Always state YOUR recommended answer — you are grilling, not surveying.

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface this interview
     question via their native channel and accept a text reply. Silent omission
     is forbidden. -->
Use `AskUserQuestion` with:
- A sharp, single question targeting the current branch.
- Your **recommended answer** as the default-marked option (label suffix: ` (Recommended)`), with a one-line rationale.
- 1-2 alternative options where they exist, plus a free-text path for "none of these".

Never batch. Never present a second question "while we're at it". One branch, one question.

After the user answers, append the Q+A to the staging file and log:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" grill_question \
  "$(printf '{"n":%d,"self_answered":false}' "$N")"
```

**Step C — Restage.** After every question (self-answered or asked), rewrite `$Z_HARNESS_GRILL_STAGING` with the running interview state: the seed topic, each resolved branch with its answer, and the still-open branches. This file is the durable interview state and the resume point — keep it current so an abandoned session is resumable.

### Termination check (run after every question)

Stop the loop when **either**:
- **No high-impact unresolved branch remains.** Every branch that would materially change the eventual plan is resolved. Remaining items, if any, are genuine deferrals → they become `## Open branches`.
- **The user calls it.** The user says some variant of "that's enough" / "let's write it up".

There is **no silent question cap.** Grill as long as it is productive.

**Standing stop offer.** Every few turns (roughly every 3-4 asked questions), surface a standing offer so the user always has the exit:

<!-- RUNTIME-GATE: ask_user; category=decision; non-supporting drivers must surface this standing
     stop offer via their native channel. Silent omission is forbidden. -->
Use `AskUserQuestion`: "We have enough to write a useful GRILL.md now — keep grilling, or finalize?"
- `keep grilling` (Recommended if high-impact branches remain) — continue the loop.
- `finalize now` — break the loop and go to Phase 3.

When the loop breaks, proceed to Phase 3.

## Phase 3 — Finalize (derive slug, collision-check, write GRILL.md)

1. **Derive a provisional slug** from the sharpened problem: short kebab-case, 2-4 words (e.g. "stop losing context at the planning boundary" → `context-boundary-loss`).

2. **Collision check (unconditional, reuse the `/z-plan` logic).** Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to list existing slugs across new and legacy layouts. If the provisional slug matches an existing slug dir:
   - **Precontext-only slug dir** (only `MAP.md`, `BRAINSTORM.md`, `RESEARCH.md`, and/or `GRILL.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, reuse the slug (a fresh `GRILL.md` write will overwrite a prior one, which is the intended resume/refresh behavior; note this in your summary).
   <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug-collision
        confirmation question (overwrite / pick a variant) via their native channel.
        Silent omission is forbidden. -->
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): **collision.** Prompt the user via `AskUserQuestion` to either overwrite (write GRILL.md into the existing dir) or pick a variant slug. This collision check runs UNCONDITIONALLY. Record whether a collision occurred for telemetry.

3. **Resolve the destination** and move staging into place:
   ```bash
   export Z_HARNESS_SLUG=<resolved-slug>
   export Z_HARNESS_PLAN_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")"
   mkdir -p "$Z_HARNESS_PLAN_DIR"
   ```
   Write the final `$Z_HARNESS_PLAN_DIR/GRILL.md` (schema below) from the interview state, then **remove the staging file** — it has been promoted:
   ```bash
   rm -f "$Z_HARNESS_GRILL_STAGING"
   ```
   Removing the staging file only after a successful write is a hard invariant: GRILL.md is written only on finalize, and the staging file is removed only after the move succeeds.

4. **Log finalize:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" grill_finalized \
     "$(printf '{"slug":"%s","collision":%s}' "$Z_HARNESS_SLUG" "$COLLISION")"
   ```
   Where `$COLLISION` is `true` or `false`.

### GRILL.md schema

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

## Phase 4 — Handoff (advisory, NEVER auto-dispatch)

Recommend the next command — but **do not invoke it**. This matches z-harness's route-decision convention: `/z-grill` produces precontext and stops; the user chooses whether to plan.

- Recommend **`/z-plan <slug>`** when the terrain is known and the path is clear enough that the remaining work is decision-making + task breakdown.
- Recommend **`/z-brainstorm <slug>`** when multiple plausible framings survived the grill — i.e. `## Open branches` carries forks that would materially change the plan, and parallel ideation would help before planning.

State the recommendation in one or two sentences, point at the written `GRILL.md` path, and stop. The user runs the next command themselves.

## Phase 5 — Finalize telemetry + summary

1. **Log phase end:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
     "$(printf '{"status":"complete","questions_asked":%d,"slug":"%s"}' "$N" "$Z_HARNESS_SLUG")"
   ```
2. Push-notify on finalize (if policy != `off`): "Grill complete. GRILL.md written for `<slug>` — recommend `/z-plan` or `/z-brainstorm`."
3. Brief 2-3 sentence summary to the user: the sharpened problem in one line, where GRILL.md was written, and the recommended next command.

**Abandon path.** If the user walks away mid-interview (does not reach Phase 3), nothing is finalized: the staging file `$Z_HARNESS_GRILL_STAGING` persists, no `GRILL.md` is written, and a later `/z-grill` resumes from the staging file (Setup step 3). This is intended — the command is resumable and never half-writes the artifact.

## Anti-patterns (push back)

- **Batching questions.** "While we're at it, also..." is forbidden. One branch, one question. If you feel the urge to batch, you are surveying, not grilling.
- **Asking what the codebase already answers.** Hard constraints, "does X exist", integration shapes — self-serve these via Explore. Asking the user wastes their turn and signals you did not look.
- **Surveying without a recommendation.** Every question states YOUR recommended answer. A grill has a point of view; a survey does not.
- **Marching the tree in list order.** Walk depth-first by impact. If the user's first answer makes the 80% version obvious, jump there — do not plod through branches 1-8 in sequence.
- **A silent question cap.** Do not stop after some fixed count. Stop when high-impact branches are resolved or the user calls it.
- **Writing GRILL.md early.** The artifact is written only on finalize. Mid-interview state lives in the staging file, never in GRILL.md.
- **Auto-dispatching the next command.** `/z-grill` recommends `/z-plan`/`/z-brainstorm` and stops. Never invoke them.

## Out of scope

- **Planning.** No SPEC/PLAN/TASKS, no task breakdown, no decisions doc. `/z-grill` sharpens the problem; `/z-plan` plans it.
- **Cross-LLM consult.** No Gemini/Codex consultants. The grill is a one-on-one interview, not a panel.
- **Implementation or review.** `/z-grill` writes no code and runs no reviewer.
- **Ideation breadth.** Generating multiple competing approaches is `/z-brainstorm`'s job. `/z-grill` narrows; brainstorm widens.
- **Terrain mapping.** Deep codebase mapping is `/z-map`. `/z-grill` only self-serves the specific constraints a branch needs.

## Hard rules

- **One question at a time.** Never batch.
- **Self-answer codebase questions.** Never ask the user something Explore can answer from the code.
- **Always recommend an answer.** Every user-facing question carries your recommendation.
- **GRILL.md is written only on finalize**, and the staging file is removed only after a successful move.
- **Collision check runs unconditionally** before writing into any slug dir.
- **Handoff is advisory** — never auto-dispatch `/z-plan` or `/z-brainstorm`.
- **No emojis** anywhere.

### Git history-rewrite safety

`/z-grill` writes no code and rewrites no history, so this is informational: if a later command you recommend ends up rewriting history on a branch tracking an upstream, run `git branch -r --contains <sha>` for each commit being rewritten first; if the upstream ref appears, STOP and prefer rebase or new-commit over silent rewrite.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
| `ask_user` | yes | Phase 1 cold-open (empty-args); Phase 2 Step B per-question interview AskUserQuestion; Phase 2 standing stop offer; Phase 3 slug-collision confirmation |
| `skill_invoke` | no | — |

Driver support requirements: see frontmatter `driver_features_required`.

Non-supporting drivers **must surface and skip** any gated block — silent
omission is forbidden. Each gated call site is annotated with a
`<!-- RUNTIME-GATE: ... -->` comment immediately before the call.
