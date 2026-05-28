# Final review — personas-and-roles

Run: 20260528T224612Z-review
Base ref: 7b2469a (parent of T001+T003 commit; 8 commits in range, 2 of which are user's parallel z-overnight work — call those out, don't flag as drift)
Diff stats: 57 files changed, 7586 insertions, 470 deletions (10110 lines of diff)

## Prong A — Implementation drift

### Severity: blocker

**A1. `providers.json` never updated to v2 with new names or aliases [both LLMs converge].**
The default TOML bindings shipped by `cmd_ensure_defaults` reference `runtime = "codex-cli"`, `runtime = "gemini-cli"`. But the actual `.z-harness/providers.json` was never touched — it still has only `codex` and `gemini` as provider entries with no `aliases` mapping. On a fresh install, `resolve-persona.py resolve` returns `runtime = "codex-cli"` → downstream `resolve-provider.py` looks up `"codex-cli"` in providers → not found → fail. The cmd_migrate subcommand only rewrites config TOML, not providers.json. Net effect: **the default state ships broken**.

Pushback considered: could the intent be "user runs migrate before first use"? No — migrate only touches config, not providers. There's no out-of-the-box-working path without manually editing providers.json. Real blocker.

**A2. Dispatcher.run() resolves `effective_model` but never passes it to `build_env()` [Codex flagged as blocker; Gemini flagged as minor — severity disagreement].**
At runtime/dispatch/dispatcher.py around line 170: `env = build_env(provider_config)` is called WITHOUT the resolved model. This means `model_env_var` (the T004 feature for CLIs that take model via env var) is completely bypassed in the actual dispatch path. T004's tests pass because they exercise build_env directly, not via Dispatcher.run.

Pushback considered: maybe build_env's env var handling is an orchestrator concern, not dispatcher's? But Dispatcher.run already resolves model — it should use it. Real blocker. Codex's grading is right.

### Severity: major

**A3. `persona_body_path` returned but no orchestrator integration [Gemini flagged].**
`resolve-persona.py resolve` correctly returns `persona_body_path` per spec, but no code reads that file and prepends the body to the role's task prompt at dispatch time. Dispatcher.run doesn't do it; no Agent() call site is documented to do it. The whole persona-as-prompt-prefix story is wired into the registry but not into actual prompt construction.

Pushback considered: maybe this is intentional, deferred to the calling-site (Agent dispatcher in the orchestrator)? Spec implies "prepended at dispatch time" but doesn't name the responsible code. Either the spec is incomplete (Prong B) or the implementation is incomplete (Prong A). I'm calling it Prong A because resolve-persona already does the path lookup — the missing piece is small enough that someone should have wired it.

**A4. `persona_bound` event payload shape mismatch vs SPEC [Codex flagged].**
SPEC §H lists `persona_bound — {command, role, persona, model, runtime, source}`. Implementation emits `{command_id, persona, model, runtime, source: {persona: layer, model: layer, runtime: layer}}`. Two issues: (a) `command_id` not `command + role` — the dispatcher doesn't have `role` context; (b) `source` is a nested per-axis dict rather than a single string. Implementation choice arguably better than spec, but the mismatch is real. Either update spec to document per-axis nesting, or flatten to a single resolution-path string.

### Severity: minor

- **A5. Dispatcher emits `dispatch_start` BEFORE resolution** (Codex) — payload doesn't carry final resolved values. Move emission after resolution block. Telemetry consistency issue, not a functional bug.
- **A6. Dispatcher doesn't call resolve-persona.py** (Gemini) — design ambiguity. If dispatcher is a thin pass-through and the orchestrator resolves before calling, this is fine; spec language ambiguous.
- **A7. resolve subcommand doesn't pre-validate `compose_argv` would succeed** (Codex) — late failure with cryptic error instead of fail-fast. Edge case for malformed providers.

## Prong B — Spec gaps

### Severity: blocker (spec must be corrected before shipping)

**B1. Provider rename strategy underspecified [Gemini flagged].**
SPEC says "rename codex → codex-cli with backward-compat aliases" but never says: (a) should providers.json have NEW entries + alias mapping back to old? (b) old entries + alias forward to new? (c) both? (d) who is responsible — implementer or user-on-install? The implementation guessed; the result is A1's broken state. SPEC needs prescriptive mechanism, not just directive.

**B2. Default TOML bindings distribution undefined [Gemini flagged].**
SPEC §E shows the default `[roles.default.*]` table but never says: where the defaults live (in `cmd_ensure_defaults` Python? in a shipped TOML file? in a template?), what happens when a user already has a config with old names, whether migration is automatic or manual. Implementation chose `cmd_ensure_defaults` (reasonable), but spec didn't prescribe.

### Severity: major

**B3. Resolution-ownership ambiguity (orchestrator vs dispatcher) [Codex flagged].**
SPEC §D1 lists resolution order but doesn't name WHO performs the resolution. Implementation has dispatcher accept kwarg overrides and expect provider_config to be pre-resolved by the caller. Code structure is clear; spec is vague. Worth a paragraph in the spec.

### Severity: minor

- **B4. Event payload shapes underspecified** (Gemini) — spec lists event names but doesn't fully detail payloads.
- **B5. Role contract enforcement "fails at startup" is vague** (Gemini) — could mean dispatcher rejects, validate exits non-zero, or Agent() rejects. Implementation chose validate (correct interpretation, but spec phrasing could be tighter).
- **B6. `persona_body_path` field undocumented** (Codex) — return value from resolve subcommand; spec doesn't specify absolute vs relative or intended use.

## Consensus vs disagreement

**Both flagged (high confidence):**
- A1 providers.json missing v2 update (Gemini blocker; Codex implicit in A2 chain)
- A2 build_env effective_model not passed (Codex blocker, Gemini minor — Codex grade is right)
- A4 persona_bound payload mismatch (Codex)
- B3 resolution ownership ambiguity

**Only one flagged (medium confidence):**
- A3 persona_body integration missing (Gemini only — but it's a real architectural gap)
- B1, B2 spec gaps (Gemini only — but Codex agrees implicitly via "SPEC clarity" major)

**No disagreement on direction; mostly grade disagreements on severity.**

## Summary
- 2 blockers (A1 + A2): the harness ships broken out of the box AND the model_env_var feature is unreachable via Dispatcher.run.
- 2 majors (A3 + A4): persona body never reaches the prompt; event payload doesn't match spec.
- 2 spec blockers (B1 + B2): the provider rename + defaults-distribution semantics need to be made prescriptive.
- 1 spec major (B3): document resolution ownership.
- 6 minors total across both prongs.
