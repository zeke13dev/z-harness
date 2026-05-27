# Phase 1 Scaffolding — z-harness-config-toml

**input_hash:** a9a5827fe57b0cc4
**generated_at:** 2026-05-27T16:57:38Z

## Topic

Add a user-facing TOML config to the z-harness repo + slim the README to a human-only quickstart.

## User constraints (from scaffolding input)

- README becomes human-only quickstart (what this is / how to install / where to look). Reference material lives in docs/human/ + docs/llm/.
- TOML config controls runtime behavior. Knobs named:
  - `docs.always_apply` (force doc-fetcher even on small flows)
  - auto-escalate vs don't (z-do → z-plan-light → z-plan ladder)
  - per-module consultation preferences: always/never consult, specific CLI path, which consultants on which phases
  - defaults per subagent role, doc-fetcher depth, archive retention, push-notification toggles
- Auto-generate missing keys on first run (write defaults, never fail).
- Thin wrapper / prompt injection-removal: config-driven prompt fragments that minimize token overhead (e.g. skip codex-consult preamble if `consult.codex = "never"`).
- Persist the config DESIGN as docs/llm/ memory + docs/human/ doc.
- Format preference: TOML.

## Doc-fetcher synthesis

### providers-registry

Config-file-based registry routing consultant/reviewer dispatches via providers.json at user-global (`~/.config/z-harness/`) or repo-local (`.z-harness/`) scope; three fixed roles (consultant_primary, consultant_secondary, reviewer) mapped to named providers; resolution via scripts/resolve-provider.sh with per-key shadowing emitting `provider_shadowed` events. This is the direct precedent for layered config: user-global config merged with repo-local config, per-key override (not whole-file), schema version enforced (must equal 1).

**Key invariants:**
- consultant_primary and consultant_secondary must resolve to distinct providers; resolver exits nonzero on collision
- Repo-local overrides user-global per-key
- A role with no bound provider halts immediately
- Schema version field must equal 1

**Key files:**
- `scripts/resolve-provider.sh` — single resolution entrypoint used by every dispatch site
- `scripts/resolve-provider.py` — Python implementation for exports/tests
- `docs/human/PROVIDERS.md` — user-facing guide with schema reference, config locations, precedence

### plan-layout-migration

`Z_HARNESS_PLANS_DIR` env var controls plan output dir; default is `z-harness/plans`. `scripts/plan-path.sh` is the single source of truth for path construction; commands must never construct paths inline. Archive paths are currently hardcoded in commands (not going through plan-path.sh). `Z_HARNESS_NOTIFY` is env-driven with no config file toggle.

**Key invariants:** commands MUST use scripts/plan-path.sh; `Z_HARNESS_PLANS_DIR` when set respected verbatim; no writes to legacy path.

**Key files:**
- `scripts/plan-path.sh` — exports plan_dir and legacy_plan_dir; single source of truth
- `docs/human/PLAN-LAYOUT.md` — user-facing guide

### commands (relevant slice)

28 commands spanning planning, debug, implement, review, audit families. Auto-escalation is hardcoded per command: z-implement-all has retry budgets, z-debug has hypothesis budgets, z-do has an escalation ladder. Doc-fetcher behavior is procedural in CLAUDE.md global rules — no toggle exists anywhere in the repo. Consult behavior (which consultants, which phases) is embedded in per-command prompt text. Surface area: 28 commands, 21 skills, 17 agents.

## Explore synthesis

(skipped — Z_HARNESS_BRAINSTORM_EXPLORE not set)

## RESEARCH.md

(not present)
