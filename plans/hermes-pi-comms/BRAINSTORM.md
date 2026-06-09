---
artifact: brainstorm
slug: hermes-pi-comms
generated_at: 2026-06-09T16:29:48Z
command: /z-reality Improve Hermes-pi communication mechanism and token economics
mode: interactive
input_hash: 186cae34d8df604d
depends_on: []
ideators:
  - interactive
ideator_models:
  interactive: default
status: complete
chosen_framing: interactive
---

## Framing: interactive (human + AI co-produced)

### Converged premise

**Problem:** Hermes and pi communicate through tmux screen-scraping — spawn sessions, paste-buffer, poll capture-pane. This is fragile (send-keys mangling, buffer issues, session lifecycle), costly (Hermes burns turns reading intermediate output), and has no message boundary. Subagents also run on Pro when Flash would suffice; the AGENTS.md note claiming "no cheap Haiku tier" was incorrect.

**Why it matters:** This is the backbone of every z-harness workflow. Every phase burns extra tokens and latency; every tmux glitch is a reliability hit. Fixing it makes the whole harness faster, cheaper, and more robust.

**Approach:** Two-phase execution.

**Phase 1 — Token economics (D, immediate):** Pin doc-fetcher, explore, and other pattern-matching/retrieval subagents to `deepseek-v4-flash` in their agent definitions. Flash is confirmed available via pi's DeepSeek API key — the AGENTS.md note was wrong and must be updated. This is a configuration fix with immediate token savings and no architectural risk.

**Phase 2 — Communication mechanism (B, after Phase 1):** Build an MCP server wrapping pi that Hermes loads as a tool (`hermes mcp add pi --command ...`). Exposes two tool surfaces:
- `pi_instruct(context, instruction)` — primary, one-shot: spawn pi with instruction, block until completion, return final output. No tmux, no polling, no session state.
- `pi_spawn_session` / `pi_send` / `pi_read` — fallback for phases that need retained context across turns (e.g., multi-step interactive work).

Phase 2 is gated on a prototype investigation answering four unknowns about pi's programmatic surface (see Open Questions below). The MCP server lives in the z-harness repo. Before building, check GitHub for existing pi MCP servers.

**Key constraints:**
- pi's TUI may require a pseudo-terminal (pty) — piping stdin/stdout may not work. The prototype must test this.
- pi's `-p` output may include spinners, thinking blocks, tool-call echo, and ANSI escapes — if dirty, options are (a) push for a pi `--quiet` / `--json-output` flag, or (b) filter server-side.
- pi may need protocol changes (done marker, clean output mode) if the as-is surface is insufficient — this extends scope from "thin wrapper" to "pi protocol evolution."
- No existing MCP servers found yet; default assumption is build, not find, but GitHub search is a pre-build step.

**Risks (surfaced in conversation):**
- **pi surface risk:** pi's programmatic surface may not support headless operation cleanly, pulling scope from "write a thin wrapper" into "modify pi's protocol." The prototype is the hedge — it answers this before the build commits to complexity.
- **Session complexity risk:** Session management in the MCP server adds complexity (process lifecycle, pty allocation, TTL, output buffer management) that the one-shot `pi_instruct` path may make unnecessary if z-harness phases are sufficiently self-contained.
- **pty requirement risk:** If pi's TUI requires a pty (raw mode, curses, terminfo), the MCP server needs a pty shim — increasing implementation complexity beyond simple subprocess management.

**Open questions (deferred to prototype):**
- Does `pi -p "<instruction>"` return clean final output, or noisy intermediate output (spinners, tool calls, thinking blocks, ANSI escapes)?
- Does pi require a pty, or does stdin/stdout piping via subprocess work?
- How do we detect completion in session mode — process exit? Silence heuristic? A pi protocol marker?
- Does an existing MCP server for pi exist on GitHub? Search before building.

### Conversation summary

Initial framing identified four pain points (polling, tmux fragility, subagent cost, no native integration) across four options (hook, MCP, script+skill, token optimization). User clarified that Flash IS available (AGENTS.md note was incorrect), D is trivially doable, and B (MCP) is the destination architecture. Converged on a sequenced two-phase plan: D first (immediate config wins, no risk), then B gated on a prototype that answers pi's programmatic surface unknowns. Key architectural decision: `pi_instruct` one-shot as primary tool surface, with session/resume as fallback — keeping the complexity budget low unless retained context proves necessary.

## Execution sequence

1. **Flash subagent config (D):** Pin `doc-fetcher`, `explore`, and other retrieval/pattern-matching subagents to `deepseek-v4-flash` in their agent definitions. Update AGENTS.md to remove the incorrect "no cheap Haiku tier" note.
2. **GitHub search:** Check for existing pi MCP servers. If found, evaluate vs. build.
3. **Prototype investigation:** Test pi's programmatic surface — `pi -p` output cleanliness, pty requirement, completion detection. Answers the four open questions.
4. **MCP server build (B):** Based on prototype findings, build the MCP server in z-harness repo exposing `pi_instruct` (primary) and session tools (fallback). If prototype reveals gaps, push pi protocol changes as needed.
5. **Integration:** Hermes loads pi MCP server, replaces tmux workflow.
