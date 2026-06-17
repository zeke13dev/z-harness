---
trigger: model_decision
description: "Interactive understanding — reconstruct what a codebase feature actually does,"
---

# /z-verify — Interactive understanding

## What this is

`/z-verify` is a **conversational understanding command**. It reads the codebase,
reconstructs what a feature actually does (not what it was supposed to do),
cross-references that against every source of intent (spec, docs, config,
conventions), probes tensions with the user one at a time, and converges on a
verified model. Output is `VERIFY.md` — an honest map of "what is" after the user
has clarified every divergence.

**Three-phase protocol:**

| Phase | What happens | Interaction |
|---|---|---|
| 1 — Reconstruct | Read the code. Trace actual implementation. Build an honest map — no assumptions, just what's on disk. | Silent |
| 2 — Cross-reference | Check the reconstruction against intent artifacts (plan slug, TASKS.md, conversation). Flag divergences: "Plan says X, code does Y." One at a time. | Interactive |
| 3 — Converge | Draft VERIFY.md. Present to user. Refine interactively — "change the verdict on #2", "add a next action." Write to disk when user signals done. | Interactive |

**Not** a plan-verification orchestrator. It does not compose `/z-audit` or
`/z-review-all`. It does not judge correctness. It reads, traces, and asks.

**Not** a subagent flow. The conversation runs inline — the AI is the thinking
partner, running in the main thread. Phase 1 may dispatch `explore` subagents for
large codebases, but the probe loop is always inline.

**Not** `/z-reality` (premise refinement for new ideas). `/z-verify` is for
**existing** code — understanding what's there.

**Not** `/z-map` (terrain map with citations). `/z-map` is batch; `/z-verify` is
interactive. `/z-map` describes; `/z-verify` probes intent.

**Not** `/z-audit` (correctness/cleanliness/design audit). `/z-verify` does not
judge. It asks "is this intentional?"

**Key properties:**
- Interactive (not batch)
- Codebase-grounded (reads source, not just docs)
- Honest — maps what IS, not what should be
- Convergent — ends with a verified model, not an open question
- "No tensions found" is a valid outcome

---

## Setup

1. **Determine the subject.** From `$ARGUMENTS`:

   | User passes | Subject resolution |
   |---|---|
   | `--slug <slug>` | Read `$Z_HARNESS_PLAN_DIR/SPEC.md` → `PLAN.md` → `TASKS.md`. The subject is the plan's implementation files. |
   | `--path <file-or-dir>` | That file or directory. Resolve relative to repo root. |
   | `--concept <name>` | Search the repo for the concept (grep source files). Present top candidates to the user to confirm. |
   | Nothing (plan-aware) | Detect if a TASKS.md exists for the current plan → use it. Otherwise ask: "Which feature should I reconstruct?" |
   | Nothing (plan-less) | Ask: "Which feature should I reconstruct?" |

2. **Derive a slug.** From the subject: short kebab-case, 2-3 words (e.g. `--path src/fee/model.rs` → `fee-model`). Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs` to check for collisions. If the user passed `--slug`, use that slug directly (no derivation).

3. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.

4. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-verify-<slug>`.

5. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/`

6. **Log run start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["subject"] = sys.argv[2]; v["command"] = "z-verify"
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<subject>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" verify_run_start "$START_PAYLOAD"
   ```

---

## Phase 1 — Reconstruct "what is"

**Read the codebase. Trace the actual implementation. Produce an honest map — no assumptions, just what's on disk.**

This is the only silent phase. No user interaction. The agent reads, traces, and
builds an internal model. Phase 1 ends when the agent has a coherent picture OR
hits a genuine ambiguity it can't resolve from code alone.

### 1a. Read the source

**If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** to ground
the reading in the two-tier docs. One call:

```
<!-- agent dispatch / skill invocation not supported in Windsurf; see CAPABILITIES.md -->
  subagent_type="doc-fetcher",
  description="Doc context for <subject>",
  prompt="query: <one-sentence subject description>\nrepo_root: <abs path>\ndepth: standard"
)
```

If doc-fetcher returns a `DRIFT WARNING`, note it — it becomes the first probe in
Phase 2.

Then read the source files. For a small feature (1-5 files): read them all. For a
medium feature (6-15 files): read the core files plus one layer of callers/callees.
For a large feature (>15 files): read the core, then dispatch `explore` subagents
for the fringes:

```
<!-- agent dispatch / skill invocation not supported in Windsurf; see CAPABILITIES.md -->
  subagent_type="explore",
  description="Trace callers of <core function>",
  prompt="Find all callers of <function> in <repo_root>. Return file:line citations and one-line summaries. Do not audit — just locate."
)
```

**Read depth checklist:**
- Source files (the feature itself)
- Tests (what's actually tested)
- Config / constants (what's parameterized)
- Docstrings / comments (what the author claimed)
- Callers (who depends on this)
- Callees (what this depends on)

### 1b. Build the internal model

The agent holds this structure in context (not written to disk yet):

```
SUBJECT: <path or slug>
DECLARED INTENT (from spec/docs/comments): <1-2 sentences, or "none declared">
ACTUAL BEHAVIOR: <what the code does — 1 paragraph, grounded in what was read>
SURFACE: <public functions, types, exports>
INTERNALS: <key internal logic, algorithms, data flow>
INVARIANTS (assumed or enforced): <list with file:line evidence>
ASSUMPTIONS (not validated): <list — "assumes input is non-null, checked nowhere">
DEPENDENCIES: <what it calls — function:file>
DEPENDEES: <what calls it — function:file>
CONFIG: <keys, defaults, where defined>
EDGE CASES HANDLED: <list with evidence>
EDGE CASES NOT HANDLED: <list — "what happens when X is empty? code doesn't say">
```

### 1c. When Phase 1 ends

| Condition | Action |
|---|---|
| Model is coherent | Proceed to Phase 2 |
| Model has gaps the code can't resolve | Proceed to Phase 2 — gaps become the first probes |
| Subject doesn't exist (file not found) | Exit: "Nothing to reconstruct. Check your path or slug." |
| Subject is too large (>20 files, user didn't scope) | Warn: "This feature spans N files. I'll reconstruct the core; ask me to drill into anything I skip." |

---

## Phase 2 — Cross-reference "what was intended"

**Check the reconstruction against available intent artifacts. Flag every
divergence where "what is" differs from "what was intended."**

Phase 1 built an honest map of the code. Phase 2 now cross-references that map
against the declared intent — the artifacts that state what the code was
supposed to do. The agent works through them in priority order, flags every
divergence, and presents them to the user one at a time.

### 2a. Locate intent artifacts (priority order)

The agent checks for these artifacts in order. The first one found that provides
concrete intent becomes the primary cross-reference source:

| Priority | Artifact | Where to look | What it provides |
|---|---|---|---|
| **1** | Plan slug | If `--slug <slug>` was passed → read SPEC.md, PLAN.md, TASKS.md from `$Z_HARNESS_PLAN_DIR` | Declared behavior, invariants, design decisions, task-level acceptance criteria |
| **2** | TASKS.md (standalone) | If a TASKS.md or TASK.md exists at a user-specified path or in the current working directory | Task descriptions, acceptance criteria, file-change lists |
| **3** | Original conversation | The user's prompt that invoked `/z-verify`, plus any clarifying statements in the current conversation | The user's stated understanding of what the feature should do |

After checking these three, the agent also scans secondary sources for additional
intent signals: docstrings/comments in the code, config values, function/type
naming conventions, and test assertions. These are lower-authority but still
useful — a docstring that says "returns Result" while the code panics is a
divergence even if no SPEC.md exists.

**If no intent artifacts exist at all** (no plan slug, no TASKS.md, no prior
conversation context), the agent asks the user to state what they expected:

> "No plan, spec, or prior conversation found for this feature. Before I
> cross-reference, tell me: what did you expect this code to do?"

The user's reply becomes the primary source of intent for the cross-reference.

### 2b. Flag divergences

For each source of intent, the agent compares the declared intent against the
Phase 1 reconstruction. Where they disagree, the agent **flags a divergence**.

A divergence is **any case where the code's observable behavior contradicts a
statement of intent.**

**Divergence types:**

| Type | Example |
|---|---|
| **Invariant violation** | SPEC.md says "all mutations are idempotent"; `submit()` increments a counter at `handler.rs:142` |
| **Missing behavior** | SPEC.md says "accepts any Order"; code panics on empty Order at `model.rs:55` |
| **Extra behavior** | TASKS.md lists 3 changed files; code also touches a 4th file not in the task |
| **Contract mismatch** | Docstring says "returns Result"; function panics on error at `lib.rs:30` |
| **Config drift** | Config declares `precision: 4`; code hardcodes floor-to-2 at `model.rs:88` |
| **Naming mismatch** | Function named `validate()` but mutates global state — name implies read-only |
| **Test gap** | Tests cover only positive amounts; code accepts negative with no guard |
| **Stub vs complete** | TASKS.md marks task `[x]` done; code has a `todo!()` or empty function body at the listed file |
| **Dead surface** | `export function legacy_normalize()` — called nowhere in the codebase |
| **User expectation** | User said "this should never block"; code has a blocking `.await` at `lib.rs:30` |

### 2c. Present the cross-reference summary

Open Phase 2 with a summary of what was checked and how many divergences were
found:

> "Checked the reconstruction against 3 intent sources:
> - SPEC.md (plan `order-router`) — 2 divergences flagged
> - Docstrings — 1 divergence flagged
> - Config — 0 divergences
>
> 3 divergences total. Going one at a time."

If no divergences are found:

> "Checked the reconstruction against all available sources of intent.
> No divergences found. The code matches every declared intent."

→ Skip the loop, proceed directly to Phase 3.

### 2d. Divergence loop

The agent presents each divergence one at a time, in priority order (spec first,
then docstrings, then config, then naming, then internal contradictions).

**For each divergence, the canonical format is "Plan says X, code does Y":**

> **Divergence 1/3 — SPEC.md §3.2**
>
> Plan says: "All mutations are idempotent — calling `submit()` twice with the
> same payload produces the same result."
>
> Code does: `submit()` increments `self.request_counter` on every call at
> `src/order/handler.rs:142`. Second call with same payload → different counter.
>
> Intentional, or a bug?

**Agent posture:**
- Every divergence follows the same format: "Plan says X. Code does Y."
- Cite the source (SPEC.md §section, docstring at file:line, config key)
- Cite the code (file:line, specific behavior)
- One divergence at a time
- Accept the user's answer
- If the user says "that's a bug" → mark as DIVERGENCE (needs fix)
- If the user says "yes, intentional" → mark as INTENTIONAL; ask if the intent artifact should be updated to match reality

**Loop control:**
- After each answer, refine the internal model
- The user can say "skip" → move to next divergence, leave unresolved
- The user can say "done" / "converge" → exit loop, proceed to Phase 3
- If the agent discovers a NEW divergence from the user's answer → add to queue
- If no divergences remain → proceed to Phase 3

### 2e. User signals

| Signal | Meaning |
|---|---|
| "skip" / "next" | Move to the next divergence without resolving this one |
| "done" / "converge" | All divergences resolved or accepted. Proceed to Phase 3. |
| "drill into X" | Pause the loop; read and trace X deeper. Resume. |
| "document this" | Mark this divergence for VERIFY.md even if intentional |

### 2d. User signals

The user can control the loop with these signals:

| Signal | Meaning |
|---|---|
| "skip" / "next" | Move to the next tension without resolving this one |
| "done" / "converge" | All tensions resolved or accepted. Proceed to Phase 3. |
| "drill into X" | Pause the loop; read and trace X deeper. Resume. |
| "document this" | Mark this tension as worth recording in VERIFY.md even if intentional |

---

## Phase 3 — Interactive convergence

**Draft VERIFY.md. Present it to the user. Refine together until the model,
verdicts, and next actions match what the user believes. Write to disk only when
the user signals done.**

Phase 2 resolved the divergences. Phase 3 now captures them in the artifact —
but the user gets to review and refine before it lands on disk.

### 3a. Draft VERIFY.md

The agent drafts the full VERIFY.md artifact in context (not yet written to
disk). The schema is the same as the final artifact (see 3c). The draft includes
everything from Phase 1's reconstruction and Phase 2's cross-reference results.

### 3b. Present the draft

> "Here's the draft VERIFY.md. Key points:
> - Reconstructed model covers 3 files, 7 functions, 2 invariants
> - 3 divergences flagged: 2 bugs, 1 intentional
> - Suggested next actions: fix `process()` idempotency, remove dead code, update config
>
> Anything to change before I write it?"

**User can refine anything in the artifact:**

| User says | Agent does |
|---|---|
| "Change the verdict on #2 to INTENTIONAL" | Updates the cross-reference table |
| "Add a next action: write integration test for empty input" | Appends to next actions |
| "The model is wrong — `process()` doesn't touch the counter, `submit()` does" | Corrects the reconstruction |
| "Remove divergence #3 — we're keeping that dead code" | Removes the row |
| "Add a note: this diverges from the upstream API spec too" | Adds a note to the divergence |
| "Looks good, write it" | Writes VERIFY.md to disk, exits Phase 3 |

This is a refinement loop, not a re-probe. The user is editing the artifact, not
answering new divergence questions. The loop runs until the user signals "done"
or "looks good" or "write it."

### 3c. Write VERIFY.md

When the user signals done, write the artifact to
`$Z_HARNESS_PLAN_DIR/VERIFY.md` (or the adhoc directory for plan-less mode):

```markdown
---
artifact: verify
slug: <slug>
run_id: <RUN>
generated_at: <ISO timestamp>
subject: <path or plan slug>
phase: understanding
---

# VERIFY.md — <subject>

## Reconstructed model

**Subject:** <path or plan slug>
**Declared intent:** <from spec/docs/comments, or "none declared">
**Actual behavior:** <1 paragraph — what the code does>

### Surface
<public functions, types, exports — list with file:line>

### Internals
<key logic, algorithms, data flow — 1 paragraph>

### Dependencies
| Calls | File:line |
|---|---|
| <function> | <path>:<line> |

### Called by
| Caller | File:line |
|---|---|
| <function> | <path>:<line> |

### Invariants
| Invariant | Evidence | Enforced? |
|---|---|---|
| <statement> | <path>:<line> | yes / assumed / no |

### Edge cases
| Case | Handled? | Evidence |
|---|---|---|
| <description> | yes / no | <path>:<line> or "not found" |

### Config
| Key | Default | Defined at |
|---|---|---|
| <key> | <default> | <path>:<line> |

## Cross-reference results

| # | Source | Plan says | Code does | Clarification | Verdict |
|---|---|---|---|---|---|
| 1 | SPEC.md §3.2 | All mutations are idempotent | `process()` increments counter at `handler.rs:142` | "That's a bug" | DIVERGENCE — needs fix |
| 2 | Config `fee.precision` | precision: 4 | `calculate()` floors to 2 at `model.rs:88` | "Config is aspirational" | INTENTIONAL — update config |
| 3 | Naming | `legacy_normalize()` — exported function | Called nowhere in codebase | "Remove it" | DIVERGENCE — dead code |

## Verdict

- **Sources of intent cross-referenced:** N (spec, docs, config, naming, tests)
- **Intentional divergences:** M (code intentionally differs from declared intent)
- **Unintentional divergences (bugs / gaps):** P (code should match intent but doesn't)
- **Open questions (user deferred):** Q
- **No divergences found:** true/false

## Next actions

- [ ] Fix: <divergence> — suggested: <command>
- [ ] Document: <divergence> — suggested: waive or update docs
- [ ] Explore: <open question> — suggested: /z-map
```

If no divergences were found:

```markdown
## Cross-reference results

No divergences found. The code matches every source of declared intent.

## Verdict

Model matches intent. No divergences.
```

---

## Finalize

1. **Log run end:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" verify_run_end \
     "$(printf '{"slug":"%s","tensions_found":%d,"divergences":%d,"open_questions":%d}' \
        "$Z_HARNESS_SLUG" "<T>" "<D>" "<Q>")"
   ```

2. **Push-notify** (if policy != `off`): "Verification complete. `<D>` divergences found, `<Q>` open questions."

3. **Brief summary** to user (3-5 sentences): what was reconstructed, key tensions, converged model.

---

## Hard rules

- **Never judge.** "Is X intentional?" not "X is wrong." The user is the authority.
- **Always cite evidence.** Every claim about the code includes `file:line`.
- **One tension at a time.** Don't overwhelm the user with a list of 20 things.
- **Honest map.** Report what the code does, not what it should do.
- **Accept the user's answer.** Don't argue. The user owns the intent.
- **Never edit code.** The output is VERIFY.md only. Remediation is the user's next step.
- **No emojis** in artifacts.
