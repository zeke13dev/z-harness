# Phase 1 Scaffolding

## Topic
Add a user-facing TOML config to the z-harness repo + slim the README to a human-only quickstart.

User constraints:
- README becomes human-only quickstart (what this is / how to install / where to look). Reference material lives in docs/human/ + docs/llm/.
- TOML config controls runtime behavior. Example knobs:
  - `docs.always_apply` (force doc-fetcher even on small flows)
  - auto-escalate vs don't (z-do → z-plan-light → z-plan ladder)
  - per-module consultation preferences: always/never consult, specific CLI path, which consultants on which phases
  - defaults per subagent role, doc-fetcher depth, archive retention, push-notification toggles
- Auto-generate missing keys on first run (write defaults, never fail).
- "Thin wrapper / prompt injection-removal" — config-driven prompt fragments to minimize token overhead: skip codex-consult preamble if `consult.codex = "never"`, trim doc-fetcher preface if `docs.always_apply = false` and task is small.
- Persist the config DESIGN in the repo as docs/llm/ memory + docs/human/ doc.
- Format: TOML.

## Doc-fetcher synthesis (verbatim)

### Current Control Mechanisms

**1. Consultation Routing (Provider Registry)** — `scripts/resolve-provider.sh` wraps `scripts/resolve-provider.py`. Reads `providers.json` from `~/.config/z-harness/providers.json` (global) and `<repo>/.z-harness/providers.json` (repo-local override, per-key shadowing, emits `provider_shadowed` event). Schema validates `schema_version == 1`, maps roles (`consultant_primary`, `consultant_secondary`, `reviewer`) to named providers. **Already extensible for a TOML layer**.

**2. Plan Discovery & Archive Paths** — `scripts/plan-path.sh` resolves canonical vs legacy paths; respects `Z_HARNESS_PLANS_DIR` env override. Other archive paths hardcoded in commands.

**3. Notification Policy** — `Z_HARNESS_NOTIFY` env (default `approval_only`). Already env-driven.

**4. Doc-fetcher Behavior** — NO explicit config. Dispatched by instructions in global CLAUDE.md and subagent declarations. No toggle for always-apply.

**5. Auto-Escalation Ladder** — Hardcoded per-command:
- `z-implement-all` max retries (line 76 "retries once on review failure")
- `z-debug` hypothesis tournament phases (implicit)
- `z-style-init` parallel critique fallback (implicit)

**6. Prompt Fragments** — Static in agent .md, skill .md, command .md. No data-driven toggles.

### Natural Injection Tiers

**Tier 1 (minimal):** Wrap existing envs — `Z_HARNESS_PLANS_DIR` → `[paths].plans_dir`; `Z_HARNESS_NOTIFY` → `[behavior].notification_policy`; provider resolver gets a `[consultation]` TOML layer in front.

**Tier 2 (moderate):** Command toggles — `[escalation] review_retry_max`, `hypothesis_budget`, `critique_fallback`; `[archive] archive_root`, `preserve_previous`.

**Tier 3 (higher):** Memory + doc behavior — `[memory] auto_review_enabled`, `candidate_cap`, `truncate_threshold`; `[docs] doc_fetcher_always_apply`, `index_staleness_warn_days`.

### Recommended Architecture (doc-fetcher's suggestion)

- Location: `<repo>/.z-harness/config.toml` (matches providers.json)
- Injection: early shell stanza in each skill that `eval`s python-emitted env vars from the TOML
- Provider resolution: TOML `[consultation]` derives env vars before calling existing resolver (no resolver changes)
- Archive paths, memory gates, doc-fetcher gates: read TOML at entry, bind env, fall back to hardcoded defaults

### No changes needed to
- Agent Markdown files (static instructions)
- `resolve-provider.sh` (thin wrapper preserved)
- MEMORIES-FLAT.md rendering

## Repo state snapshot
- 28 commands, 21 skills, 17 agents → lots of surface area to migrate
- providers.json + scripts/resolve-provider.* already exist (precedent for repo-local config)
- docs/human/ + docs/llm/ tier already in place (INDEX.json present)
- README.md exists; needs slim-down (currently mixes quickstart with reference)
- No existing config.toml anywhere in repo

## Brainstorm questions for ideators
1. Config schema shape — which knobs are load-bearing, which are noise. Be opinionated about minimum viable surface.
2. Config location — repo root `z-harness.toml`, `.z-harness/config.toml`, `~/.config/z-harness/`, or layered (global + repo)?
3. How skills READ config cheaply — pure-shell TOML parser (yq/tq/dasel), python helper, generated env-export, or pre-templated SKILL.md?
4. The "thin wrapper / prompt injection-removal" mechanism — concrete design. Pre-processor templating SKILL.md fragments at load time? Loader stanza in each skill that emits/suppresses lines based on config? Token-overhead vs maintenance tradeoffs.
5. Auto-generation of missing keys — write-back to disk vs in-memory defaults; how to surface "we added defaults" without nagging.
6. Maintenance: docs/llm/ memory entry + docs/human/ doc + INDEX.json wiring. What's the right schema-validation cadence?
7. Risks — config-drift from skill behavior, stale keys, consult prefs leaking into prompts that shouldn't see them.
8. Smallest credible first slice — what subset to ship first to prove the mechanism without rewriting 21 skills?
