---
name: z-learn
disable-model-invocation: false
description: Interactive progressive-disclosure tutor for understanding code. Replaces repetitive "explain more / tell me about X" sessions. Four depth lenses, resumable staging, optional LEARN.md artifact. Read-only, no cross-LLM consult.
argument-hint: "<target> [orientation|walkthrough|deep|audit-brief] or free-text"
runtime: c1
driver_features_required:
  - subagent
  - ask_user
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-learn`** — an interactive tutor for understanding code (especially AI-generated code the user did not write). You teach in small chunks, cite every code claim, and let the user steer depth via fuzzy language or a standing navigation menu. This is **not** a subagent flow — the loop runs inline so each turn builds on prior context.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

## The four lenses (shared with `/z-explain`)

| Lens | User signals | Delivers per turn |
|------|--------------|-------------------|
| **orientation** | "high level", "overview", "why", "design decisions" | Purpose, rationale, architectural choices |
| **walkthrough** | "how does it work", "flow", "pipeline", "what happens next" | One slice of execution/data flow |
| **deep** | "more detail", "this function", "line by line", "tell me about X" | Line-level behavior on the focused piece |
| **audit-brief** | "audit", "what could break", "invariants", "edge cases" | Invariants, failure modes, verification hooks |

Default starting lens: **orientation** unless args or fuzzy NL say otherwise.

**Fuzzy routing:** Treat NL as a *hint*, not a hard switch. After each turn, state which lens you used: "Treated that as walkthrough — say *deeper*, *audit lens*, or *pivot* to adjust."

**Audit-brief disclaimer:** Prepares the user to audit; does not replace `/z-audit` for findings.

## Setup

1. **Resolve plans base** and staging path:
   ```bash
   PLANS_BASE="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" base_dir)"
   mkdir -p "$PLANS_BASE"
   export Z_HARNESS_LEARN_STAGING="$PLANS_BASE/.learn-pending.md"
   ```
2. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-learn`.
3. **Resume check.** If `$Z_HARNESS_LEARN_STAGING` exists, read it. Summarize where the prior session left off (target, current lens, last focus). **Continue the tutor loop from the last turn — do not restart from scratch.** If the new invocation's target **differs** from the staging header `target:`:

<!-- RUNTIME-GATE: ask_user ; category=decision; -->
   warn and ask whether to continue the old session or start fresh.
4. If no staging file, create one using the **shared staging schema**:
   ```markdown
   # Learn session (pending)
   target: <parsed or TBD>
   started: <iso8601 UTC>
   current_lens: orientation
   last_focus:

   ## Prior explain
   (empty — populated by /z-explain handoff if present)

   ## Turn log
   ```
5. **Ingest prior `/z-explain` context.** If `## Prior explain` contains content, treat it as already-covered ground — do not repeat; build on it and continue from `current_lens` / `last_focus` in the header.
6. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["arguments"] = sys.argv[2]; v["command"] = "z-learn"
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" learn_run_start "$START_PAYLOAD"
   ```
7. **Route/archive dir** (for Phase 0 handoff artifacts):
   ```bash
   export LEARN_ARCHIVE_DIR="$PLANS_BASE/.learn-archive/$RUN"
   mkdir -p "$LEARN_ARCHIVE_DIR"
   ```
8. Notification policy: see [docs/human/config.md](docs/human/config.md). Push only on finalize.
9. Initialize turn counter `T=0`.

## Phase 0 — Route check

Same routes as `/z-explain`. If intent mismatches interactive tutoring, write `$LEARN_ARCHIVE_DIR/route-decision.md`, log handoff, recommend the target command, and **stop** without auto-dispatch:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" learn_route_handoff \
  "$(printf '{"target_command":"%s","reason":"%s"}' "$ROUTE_CMD" "$ROUTE_REASON")"
```

| Signal | Route to |
|--------|----------|
| Terrain unknown | `/z-map <question>` |
| Find bugs | `/z-audit <target>` |
| Change code | `/z-do <task>` or `/z-plan-light <task>` |
| Quick one-shot answer | `/z-explain <target>` |

## Phase 1 — Cold open (empty-args only)

<!-- RUNTIME-GATE: ask_user ; category=mechanical_proceed; -->
If arguments are empty and staging has no target, ask: "What code should we learn — file, module, pipeline, or topic?" One question only. Proceed to Phase 2 when target is known.

If arguments provide a target, skip cold open.

## Phase 2 — Initial grounding (once per session)

Run only on session start or when target changes:

1. doc-fetcher if `docs/llm/INDEX.json` exists (same pattern as `/z-explain`).
2. **Plan-slug precontext.** If the target is a plan slug (matches `all_plan_slugs` or resolves via `resolve_plan_path`):
   ```bash
   TARGET_SLUG="<derived slug>"
   TARGET_PLAN_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$TARGET_SLUG")"
   ```
   Read `$TARGET_PLAN_DIR/MAP.md`, `$TARGET_PLAN_DIR/SPEC.md`, `$TARGET_PLAN_DIR/GRILL.md`, and `$TARGET_PLAN_DIR/LEARN.md` if present (LEARN is a snapshot — use for continuity, not as sole source of truth).
3. Targeted Explore or direct reads for scope discovery — enough to teach orientation, not a full `/z-map`.

Record grounding summary in staging under `## Grounding`.

## Phase 3 — The tutor loop (inline, one chunk per turn)

Loop until termination (below). Each iteration delivers **one teaching chunk** for the current lens and focus topic.

### Step A — Teach one chunk

- Length: ~1 screen (roughly 150-400 words) unless user asked for terse.
- Structure matches active lens (same schemas as `/z-explain` Phase 3, but **one slice** per turn for walkthrough/deep — do not exhaust the whole system at once).
- **Citation contract:** every code claim gets `file:line`.
- End with a one-line "focus" label: what you just covered and what natural next slice would be.

### Step B — Restage

Append turn summary to `$Z_HARNESS_LEARN_STAGING` (`## Turn log` entry: turn number, lens, focus, key citations). Update `current_lens` and `last_focus` in the header.

Log:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" learn_turn \
  "$(printf '{"t":%d,"lens":"%s","focus":"%s"}' "$T" "$LENS" "$FOCUS")"
```
Increment `T`.

### Step C — Standing navigation menu

After every teaching chunk, present navigation via `AskUserQuestion` (compact menu):

<!-- RUNTIME-GATE: ask_user ; category=mechanical_proceed; -->
- **deeper** — same focus, more line-level detail (switch to or stay in `deep`)
- **next** (Recommended when walkthrough lens) — next slice of the flow
- **pivot: \<topic\>** — free-text: jump to a named component/symbol/concept
- **switch lens** — pick orientation | walkthrough | deep | audit-brief
- **finalize** — write LEARN.md and end session
- **stop** — save staging, exit without LEARN.md

Parse the user's choice (including free-text pivots) and loop. Fuzzy replies map to the closest option; confirm when ambiguous.

### Termination

Stop the loop when the user picks **finalize** or **stop**, or says variants of "that's enough".

- **stop** — staging persists; no LEARN.md. Later `/z-learn` resumes.
- **finalize** — proceed to Phase 4.

There is no silent turn cap.

## Phase 4 — Finalize (optional LEARN.md)

Only when user chose **finalize**.

1. **Derive provisional slug** from target: short kebab-case, 2-4 words.

2. **Collision check (unconditional, same rules as `/z-grill`).** Run `bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" all_plan_slugs`. If the provisional slug matches an existing slug dir:
   - **Precontext-only slug dir** (only `MAP.md`, `BRAINSTORM.md`, `RESEARCH.md`, `GRILL.md`, and/or `LEARN.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — reuse the slug (a fresh `LEARN.md` write overwrites a prior one; note this in your summary).
   <!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the slug-collision
        confirmation question (overwrite / pick a variant) via their native channel.
        Silent omission is forbidden. -->
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): **collision.** Prompt via `AskUserQuestion` to overwrite (write LEARN.md into the existing dir) or pick a variant slug.

3. **Resolve destination** and write artifact:
   ```bash
   export Z_HARNESS_SLUG=<resolved-slug>
   export Z_HARNESS_PLAN_DIR="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")"
   mkdir -p "$Z_HARNESS_PLAN_DIR"
   ```
   Write `$Z_HARNESS_PLAN_DIR/LEARN.md` (schema below), then remove staging:
   ```bash
   rm -f "$Z_HARNESS_LEARN_STAGING"
   ```
   Removing the staging file only after a successful write is a hard invariant.

4. Log:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" learn_finalized \
     "$(printf '{"slug":"%s","turns":%d}' "$Z_HARNESS_SLUG" "$T")"
   ```

### LEARN.md schema

Lens-structured summary — **not** a raw transcript.

```markdown
---
generated_at: <iso 8601 UTC>
status: complete
slug: <resolved-slug>
target: <original target>
turns: <T>
---

# LEARN — <slug>

## Target
<what was studied>

## Orientation
<design purpose and key decisions>

## Walkthrough
<execution/data flow summary>

## Deep dives
<symbol/block notes covered>

## Audit brief
<invariants, failure modes, verification checklist>

## Open threads
<topics not yet covered; or "none">

## Recommended next command
<`/z-audit`, `/z-map`, `/z-plan`, or "none" + one-line rationale — advisory only>
```

Omit empty sections. Merge duplicate material across turns.

## Phase 5 — Summary

1. Log `phase_end` with turns and slug (if finalized).
2. Push-notify on finalize (if policy != `off`).
3. Brief summary: target, turns, lens coverage, LEARN.md path or staging path for resume.

**Abandon path.** Mid-loop exit via **stop** keeps `.learn-pending.md`; no LEARN.md.

## Anti-patterns

- **Dumping all lenses at once.** One chunk per turn.
- **Repeating `/z-explain` content** when `## Prior explain` exists in staging.
- **Claiming audit findings** in audit-brief lens — teach verification, not verdicts.
- **Auto-dispatching** `/z-audit`, `/z-map`, or `/z-plan`.
- **Writing LEARN.md mid-session** — staging only until finalize.

## Out of scope

- Planning, implementation, code review.
- Cross-LLM consult.
- Full terrain mapping (`/z-map`).

## Hard rules

- **One teaching chunk per turn.**
- **Standing menu after every turn** (except when routing out in Phase 0).
- **Citations on every code claim.**
- **LEARN.md only on finalize**; staging removed only after successful write.
- **Collision check runs unconditionally** before writing into any slug dir.
- **No emojis** anywhere.

---

## Runtime contract conformance

| Feature | Used | Gates |
|---------|------|-------|
| `subagent` | yes | Phase 2 doc-fetcher + Explore |
| `ask_user` | yes | Phase 1 cold-open; Phase 3 standing menu each turn |
| `skill_invoke` | no | — |

Non-supporting drivers **must surface and skip** any gated block — silent omission is forbidden.
