# Brainstorm: Add user-facing TOML config to z-harness + slim README

## Mode
brainstorm

## Current state
- z-harness is a Claude Code plugin with 28 commands, 21 skills, 17 agents.
- Existing provider registry: `providers.json` (global `~/.config/z-harness/` + repo `.z-harness/` shadowing).
- Env-driven knobs: `Z_HARNESS_PLANS_DIR`, `Z_HARNESS_NOTIFY`, `Z_HARNESS_SLUG`, etc. (9 total env vars).
- Doc-fetcher behavior is procedural in global `CLAUDE.md`. No toggle.
- Auto-escalation logic hardcoded per-command (e.g., `/z-plan-light` → `/z-plan` on scope growth).
- Archive paths hardcoded; plan paths via `scripts/plan-path.sh`.
- Two-tier docs exist: `docs/human/` (human-readable) + `docs/llm/INDEX.json` (token-compacted LLM lookup).

## User constraints
- README becomes human-only quickstart (what this is / how to install / where to look). Reference material → `docs/human/` + `docs/llm/`.
- TOML config controls runtime behavior with knobs like:
  - `docs.always_apply` (force doc-fetcher even on small flows)
  - auto-escalate vs don't (z-do → z-plan-light → z-plan ladder)
  - per-module consultation preferences: always/never consult, specific CLI path, which consultants on which phases
  - defaults per subagent role, doc-fetcher depth, archive retention, push-notification toggles
- Auto-generate missing keys on first run (write defaults, never fail).
- "Thin wrapper / prompt injection-removal" — config-driven prompt fragments to minimize token overhead.
- Persist design in `docs/llm/` memory + `docs/human/` doc.
- Format: TOML.

## Brainstorm questions
1. Config schema shape — load-bearing vs noise.
2. Config location — `z-harness.toml`, `.z-harness/config.toml`, `~/.config/z-harness/`, or layered.
3. How skills READ config cheaply.
4. Thin wrapper / prompt injection-removal mechanism — concrete design.
5. Auto-generation of missing keys.
6. Maintenance — `docs/llm/` memory + `docs/human/` doc + `INDEX.json`.
7. Risks.
8. Smallest credible first slice.

## Ask
Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.
