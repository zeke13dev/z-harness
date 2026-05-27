# MODE: brainstorm

## Topic
Add a user-facing TOML config to the z-harness repo + slim the README to a human-only quickstart.

## Input artifact + constraints

### User constraints
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

### Current state (repo snapshot)

**Existing registry precedent:**
- providers.json + scripts/resolve-provider.{sh,py} already exist
- Global `~/.config/z-harness/` + repo `.z-harness/` with per-key shadowing pattern established
- `Z_HARNESS_PLANS_DIR` and `Z_HARNESS_NOTIFY` are env-driven knobs (could absorb into TOML)

**Scope of runtime config:**
- 28 commands, 21 skills, 17 agents
- Doc-fetcher behavior currently procedural (in global CLAUDE.md; no toggle)
- Auto-escalation hardcoded per-command (z-implement-all retry budget, z-debug hypothesis budget, z-style-init fallback)
- Plan paths via scripts/plan-path.sh; archive paths hardcoded in commands
- No config.toml anywhere yet

**Existing env-knob examples:**
```bash
Z_HARNESS_NOTIFY = "off" | "approval_only" | "all"
Z_HARNESS_MAX_EXPLORE = default 3
Z_HARNESS_DOC_STALENESS_THRESHOLD = default 20%
Z_HARNESS_LOCAL_CARGO_CLEAN = 0 | 1
Z_HARNESS_BRAINSTORM_EXPLORE = 0 | 1
Z_IMPLEMENT_PAUSE_TASKS = default 5
Z_IMPLEMENT_PAUSE_MINUTES = default 30
```

### Brainstorm questions to address
1. Config schema shape — load-bearing vs noise.
2. Config location — `z-harness.toml`, `.z-harness/config.toml`, `~/.config/z-harness/`, or layered.
3. How skills READ config cheaply (Haiku agents need minimal context).
4. Thin wrapper / prompt injection-removal mechanism — concrete design.
5. Auto-generation of missing keys.
6. Maintenance — docs/llm/ memory + docs/human/ doc + INDEX.json.
7. Risks (migration, silent breakage, complexity debt).
8. Smallest credible first slice.

## Ask

Return exactly five sections:

1. **Framing** — the problem you're solving and why it matters
2. **Core hypothesis** — the core bet you'd make if you had to pick one
3. **Risks** — concrete failure modes and tradeoffs
4. **Plan implications** — how this changes the implementation roadmap
5. **What would change my mind** — evidence that would disconfirm the hypothesis

Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.
