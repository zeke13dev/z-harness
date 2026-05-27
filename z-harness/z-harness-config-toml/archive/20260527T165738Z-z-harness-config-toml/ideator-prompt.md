MODE: brainstorm

Topic: Add a user-facing TOML config to the z-harness repo + slim the README to a human-only quickstart.

Scaffolding:
---
User constraints:
- README becomes human-only quickstart (what this is / how to install / where to look). Reference material lives in docs/human/ + docs/llm/.
- TOML config controls runtime behavior. Example knobs the user named:
  - `docs.always_apply` (force doc-fetcher even on small flows)
  - auto-escalate vs don't (z-do → z-plan-light → z-plan ladder)
  - per-module consultation preferences: always/never consult, specific CLI path, which consultants on which phases
  - defaults per subagent role, doc-fetcher depth, archive retention, push-notification toggles
- Auto-generate missing keys on first run (write defaults, never fail).
- "Thin wrapper / prompt injection-removal" — config-driven prompt fragments to minimize token overhead: e.g. skip the codex-consult preamble entirely if `consult.codex = "never"`; trim the doc-fetcher preface if `docs.always_apply = false` and task is small.
- Persist the config DESIGN in the repo as a docs/llm/ memory + docs/human/ doc.
- Format preference: TOML.

Current state (from doc-fetcher):
- providers.json + scripts/resolve-provider.{sh,py} already exist (schema_version, role-based mapping, global ~/.config/z-harness/ + repo `.z-harness/` with per-key shadowing emitting `provider_shadowed` events). This is a precedent.
- `Z_HARNESS_PLANS_DIR` and `Z_HARNESS_NOTIFY` are env-driven knobs that could absorb into TOML.
- Plan paths via `scripts/plan-path.sh`. Archive paths hardcoded in commands.
- Doc-fetcher behavior is procedural (in CLAUDE.md/global rules), no toggle exists.
- Auto-escalation hardcoded per-command (z-implement-all retry budget, z-debug hypothesis budget, z-style-init fallback).
- 28 commands, 21 skills, 17 agents → big surface area to migrate.
- No config.toml anywhere yet.

Brainstorm questions:
1. Config schema shape — load-bearing vs noise.
2. Config location — `z-harness.toml`, `.z-harness/config.toml`, `~/.config/z-harness/`, or layered.
3. How skills READ config cheaply — shell TOML parser, python helper, generated env-export, pre-templated SKILL.md.
4. Thin wrapper / prompt injection-removal mechanism — concrete design.
5. Auto-generation of missing keys — write-back vs in-memory defaults; how to surface.
6. Maintenance — docs/llm/ memory + docs/human/ doc + INDEX.json wiring.
7. Risks — drift, stale keys, consult prefs leaking into wrong prompts.
8. Smallest credible first slice.
---

Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.
