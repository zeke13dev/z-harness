---
inclusion: manual
description: Interactive premise refinement — conversational on-ramp. Probes, clarifies,
---

# /z-reality — Interactive premise refinement

## What this is

`/z-reality` is a **conversational on-ramp** that sits before every other z-harness
command. It is a single conversation between the user and an AI thinking partner. The
AI clarifies, probes, reframes, and pushes the idea forward until the user signals
convergence ("yeah, that makes sense"). It produces a BRAINSTORM.md variant (`mode:
interactive`, `ideators: [interactive]`) and routes to `/z-brainstorm` (to
stress-test the premise) or `/z-plan` (if the premise is already tight).

**Not** a subagent flow. The conversation runs inline — no subagent dispatch, no
cross-LLM consult. The AI IS the thinking partner, running in the main thread.

**Not** `/z-grill` (adversarial interrogation with recommended answers).

**Not** `/z-brainstorm` (parallel vendor-diverse ideation).

**Key properties:**
- Iterative (not batch)
- Conversational (not orchestrator-synthesized)
- Artifact production gated on convergence (not always-writing)
- "No artifact / abandoned idea" is a valid outcome

---

## Setup

Before entering the conversation, the orchestrator must:

1. **Capture the topic.** From `$ARGUMENTS`. If blank/whitespace, open with "What
   are you thinking about?" and discover the topic in the conversation.
2. **Derive a slug.** If the user hasn't provided one, auto-derive from the topic
   once a clear premise emerges: short kebab-case, 2-4 words. Confirm with the user
   before writing.
3. **Resolve `Z_HARNESS_PLAN_DIR`.** Via `plan-path.sh resolve_plan_path <slug>`.
   Do nothing with it until Stage 4 (artifact write).
4. **Pick a run id.** `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
5. **Log `reality_run_start`:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" reality_run_start \
     "$(printf '{"topic":"%s","command":"/z-reality"}' "<original user prompt>")"
   ```

After Setup, enter the protocol. The conversation has four logical stages. These
are NOT gated harness phases — they describe the conversational arc.

---

## Stage 1 — Framing

The AI reads the user's premise and restates it back with precision.

**Goal:** establish shared understanding before probing.

**Format:** "Here's what I hear you saying: ... Is that right?"

The restatement should:
- Be precise, not a vague mirror
- Identify the core tension or goal
- Surface any obvious gaps or implicit assumptions

Wait for the user to confirm or correct before moving to Stage 2.

If the user opens with a fully-formed, constraint-rich task description (token count
≥15 words, contains file paths or concrete constraints, no exploratory language),
this may NOT be a `/z-reality` session — the underspecified detection should have
routed differently. If you find yourself with a crisp task anyway, say so and offer
to exit refinement: "This sounds like a concrete task rather than a raw idea. Want
to jump straight to `/z-plan` or `/z-do` instead?"

---

## Stage 2 — Probe / Clarify / Reframe loop

This is the core. The AI asks sharp questions, surfaces assumptions, identifies
tensions, and offers reframings.

### Direction level

The AI adapts its posture based on what the premise needs:

- **More directive** when the idea has obvious structural problems.
  Example: "that approach has a race condition — can we reframe?"
- **More exploratory** when the idea is novel but underspecified.
  Example: "tell me more about what 'good' looks like"
- **Equal partner** when the idea is coherent but needs pressure-testing.
  Example: "if we frame this as a data-model problem instead of a caching problem..."

Each exchange should advance the premise — narrowing or reshaping it. Ask at least
one question per exchange. Never write the artifact during this loop.

### Posture spec

| Signal from user | AI response |
|---|---|
| Vague wish ("I want faster queries") | Ask what "faster" means — latency? throughput? for which queries? What's the current baseline? |
| Contradiction ("batched but also real-time") | Surface the tension explicitly, ask which constraint yields. "Batched and real-time pull in opposite directions — which matters more for the core use case?" |
| Missing constraint ("no latency target mentioned") | Ask for the missing dimension. "What's the latency target? Without one, we can't know if the approach works." |
| Premise drift (topic shifts mid-conversation) | Note the shift, ask if this is a new premise or an expansion. "We started with caching, now we're talking about data partitioning — is this a broader reframe or a new idea?" |
| User seems stuck or looping | Offer a structured choices question with 2-3 distinct framings. "Let me reframe the options: (a) push computation to read time, (b) precompute and cache, (c) redesign the schema. Which direction feels right?" |
| User signals clarity ("yeah, that makes sense") | Move to Stage 3 |
| User signals frustration ("this isn't going anywhere") | Offer the escape-hatch menu (see Escape Hatches below) |

### Anti-posture (the AI must NOT)

- Write the artifact before convergence
- Push a single framing as "the answer" — the user owns the premise
- Mirror without probing (pure active-listening is not enough)
- Ignore contradictions to be agreeable
- Dispatch subagents, explore code, or consult other LLMs (this is a conversation)
- Spawn any shell scripts other than the three logging calls

---

## Stage 3 — Convergence gate

When the user signals convergence, the AI synthesizes the converged premise back to
the user for explicit confirmation. This gate is **mandatory** — the AI never writes
the artifact before the user confirms.

### Synthesis template

Present this structured block:

```
Here's what we've converged on:

**Problem:** <one sentence>
**Why it matters:** <one sentence>
**Approach:** <one paragraph>
**Key constraints:** <bullet list>
**Risks (surfaced in conversation):** <bullet list>
**Open questions (deferred):** <bullet list>

Does this capture it? Options:
- "Yeah, that makes sense" — write artifact and route
- "Almost — let me refine one thing" — continue refining
- "Good enough for now" — write artifact with status: draft
- "Actually, let's abandon this" — exit cleanly
```

Wait for the user's explicit choice. Do NOT proceed until they pick one.

### Convergence signal vocabulary

The AI watches for these phrases or their semantic equivalents during Stage 2 and
at the convergence gate:

| User phrase | Meaning |
|---|---|
| "yeah, that makes sense" | Full convergence → artifact + route |
| "good enough" / "let's move on" / "ship it" | Convergence with caveat → artifact with `status: draft` |
| "abandon" / "bad idea" / "let's not" / "nevermind" | Abort (see Escape Hatches) |
| "this is close but" / "almost" / "one more thing" | Continue refining — loop back to Stage 2 |
| "not quite" / "I don't think so" | Premise needs more work — loop back to Stage 2 |

---

## Stage 4 — Artifact production and route handoff

### On convergence ("yeah, that makes sense")

1. **Resolve slug.** If not already set, auto-derive from the converged premise:
   short kebab-case, 2-4 words. Confirm with the user.
2. **Check for collision.** If `BRAINSTORM.md` already exists at the slug path, ask:
   overwrite, pick a different slug, or abort. (No "append to existing" — interactive
   refinement produces a fresh premise.)
3. **Write `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`** with the interactive variant format
   (see Artifact Format below).
4. **Log `reality_convergence`:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" reality_convergence \
     "$(printf '{"rounds":%d,"signal":"yeah","artifact_path":"%s"}' \
        "<conversation length>" "$Z_HARNESS_PLAN_DIR/BRAINSTORM.md")"
   ```
5. **Present next-step menu:**
   ```
   BRAINSTORM.md written to <path>.

   What's next?
   - `/z-brainstorm` — stress-test this premise with 3 vendor-diverse ideators
   - `/z-plan` — go straight to planning (the premise feels tight enough)
   - `/z-do` — this is small enough to implement directly
   - "Let me sit with this" — exit without routing
   ```
   Do NOT auto-invoke the next command. The user chooses.

### On "good enough" / draft

Same as convergence, but set `status: draft` in the frontmatter. The body is
identical. When presenting the next-step menu, add a note: "The premise is marked
draft — downstream commands will treat it as provisional."

### On abandon

1. Confirm once: "You want to abandon this idea? (No artifact will be written.)"
2. If confirmed, log and exit:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" reality_convergence \
     "$(printf '{"rounds":%d,"signal":"abandon","artifact_path":""}' "<rounds>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" reality_run_end \
     "$(printf '{"outcome":"abandoned","rounds":%d}' "<rounds>")"
   ```
3. No BRAINSTORM.md is written.

### On user rejecting refinement

If during Stage 1 or Stage 2 the user says "no, just do X" or equivalent:
1. Stop the conversation immediately — don't push refinement.
2. Log the convergence as an abandon/reject.
3. Route to the appropriate concrete command based on X (use the standard routing
   table from AGENTS.md).

### On session end

After the next-step choice or abandon, log `reality_run_end`:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" reality_run_end \
  "$(printf '{"outcome":"%s","rounds":%d}' "<converged|abandoned|timeout>" "<rounds>")"
```

---

## Escape hatches

Three escape paths:

### 1. User-initiated abandon

Triggered by "abandon", "bad idea", "let's not", "nevermind". AI asks once to
confirm, then logs and exits. No artifact written.

### 2. AI-sensed frustration

If the conversation reaches 8+ rounds without convergence, the AI proactively
offers the escape hatch:

```
This doesn't seem to be converging. Options:
- (a) try a different angle — reframe the problem entirely
- (b) write what we have as draft — capture the current state, refine later
- (c) abandon — revisit later when the idea is clearer
```

### 3. Disconnect / timeout

If the user disconnects mid-session, no artifact is written. If they return, the
conversation resumes from chat context — no staging file is needed.

---

## Slug derivation

If no slug is provided, auto-derive from the converged premise:
- Short kebab-case, 2-4 words
- Example: "add caching layer for analytics queries" → `analytics-caching`
- Confirm with the user before writing

---

## Artifact format (interactive BRAINSTORM.md variant)

### Frontmatter

```yaml
---
artifact: brainstorm
slug: <slug>
generated_at: <UTC ISO 8601>
command: /z-reality [<original user prompt — truncated to 120 chars>]
mode: interactive
input_hash: <sha256(canonicalize(converged_premise + "\n---\n" + conversation_len_rounds)).hexdigest()[:16]>
depends_on: []
ideators:
  - interactive
ideator_models:
  interactive: default
status: complete | draft
chosen_framing: interactive
---
```

`input_hash` computation:
```
input_hash = sha256(canonicalize(
    converged_premise_text + "\n---\n" + str(conversation_rounds)
)).hexdigest()[:16]
```

`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of
whitespace to a single space.

### Body

```markdown
## Framing: interactive (human + AI co-produced)

### Converged premise

**Problem:** <one sentence>
**Why it matters:** <one sentence>
**Approach:** <one paragraph>
**Key constraints:** <bullet list>
**Risks (surfaced in conversation):** <bullet list>
**Open questions (deferred):** <bullet list>

### Conversation summary

<2-3 sentence summary of the refinement arc — what changed from initial premise to
converged premise. Not the full transcript.>
```

Only ONE framing section. No anti-bias check, no orchestrator recommendation, no
user choice blocks. The `chosen_framing: interactive` already captures the
selection.

### `status: draft` variant

Same body, but `status: draft` in frontmatter. Downstream `/z-plan` treats it as
usable but notes the premise is provisional.

---

## Logging

Three events only — no phase telemetry:

| Event kind | When | Fields |
|---|---|---|
| `reality_run_start` | Conversation begins | `topic`, `command` |
| `reality_convergence` | User signals convergence | `rounds`, `signal` (yeah/good_enough/abandon), `artifact_path` (if written) |
| `reality_run_end` | Conversation ends | `outcome` (converged/abandoned/timeout), `rounds` |

No `user_wait_start`/`user_wait_end` bracketing — the entire interaction is a
conversation; there's no machine-time to separate.

---

## Edge cases

- **Empty topic:** If `$ARGUMENTS` is blank, open with "What are you thinking
  about?" — the conversation discovers the topic.
- **User rejects refinement:** If the user says "no, just do X," exit refinement
  immediately and route to the appropriate concrete command.
- **Fully-formed topic:** If the user opens with a crisp, constraint-rich task
  description, say so and offer to skip refinement (this shouldn't happen if the
  underspecified detection works, but guard anyway).
- **Slug collision:** If BRAINSTORM.md already exists at the derived slug path, ask:
  overwrite, pick a different slug, or abort.
- **pi-specific invocation:** `/z-reality` cannot be run via pi subagents — it's an
  inline conversation. The pi shim delegates to the main thread.

---

## Out of scope (v2)

- Persona weaving (one agent adopting multiple perspectives)
- Full conversation transcript in the artifact
- Multi-turn Explore subagents during refinement
- Reality-run resume staging file
- Z_HARNESS_CONSULT interaction (irrelevant — no cross-LLM consult)
- Claim acquire / active-plan registration
