---
inclusion: manual
description: Interactive premise refinement — conversational on-ramp. Probes, clarifies,
---

You are running the **z-harness `/z-reality`** interactive premise-refinement command.

Topic (from `$ARGUMENTS`):

$ARGUMENTS

<!-- RUNTIME-GATE: ask_user; category=mechanical_proceed; non-supporting drivers must surface the question
     "What are you thinking about?" via their native channel. Silent omission is
     forbidden. -->
**If the topic above is empty or whitespace**, open with: "What are you thinking
about?" The entire conversation discovers the topic.

`/z-reality` is a **conversational on-ramp** — a thinking-partner conversation
that refines a raw idea into a crisp premise. It runs inline (no subagents, no
cross-LLM consult) and produces a BRAINSTORM.md variant (`mode: interactive`)
only after the user signals convergence.

## Setup

1. **Derive slug.** From the topic or from the converged premise (during Stage 4):
   short kebab-case, 2-4 words. Confirm with the user.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p $Z_HARNESS_PLAN_DIR`.
5. **Log run start:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" reality_run_start \
     "$(printf '{"topic":"%s","command":"/z-reality"}' "<original user prompt>")"
   ```

## Protocol

Now follow the full interactive protocol in `skills/z-reality/SKILL.md`:
- Stage 1 — Framing: restate the premise back
- Stage 2 — Probe / Clarify / Reframe loop
- Stage 3 — Convergence gate: synthesize and confirm
- Stage 4 — Artifact production and route handoff

The protocol must run inline — no subagents, no cross-LLM consult, no phase
telemetry. Log only `reality_run_start`, `reality_convergence`, and
`reality_run_end`.

If the user abandons, log and exit cleanly. No BRAINSTORM.md is written.
