## (1) Framing

This is primarily a **surface-area problem masquerading as an architecture problem**. The z-harness has 28 commands all containing hardcoded behavioral constants — retry budgets, escalation thresholds, consultant invocations, doc-fetcher depth — that are currently immutable from outside the codebase. The TOML config doesn't need to be a comprehensive control plane on day one; it needs to be a **stable external hook** for the handful of knobs users actually touch repeatedly. The README slim is the easier half: it's already true that README is the wrong place for reference docs when docs/human/ exists.

## (2) Core hypothesis

The winning design treats TOML config as a **env-var replacement layer with schema**, not a prompt-fragment system. The existing `Z_HARNESS_NOTIFY` and `Z_HARNESS_PLANS_DIR` pattern already works: commands read environment variables, not files. A `scripts/config.py` (or `.sh`) that reads TOML and exports env-vars at the start of any run would retrofit every command without touching their internals. The thin-wrapper/prompt-injection-removal idea should be deferred until the config system is stable — mixing "toggle behavior" with "modify prompt text" in the same config creates two different maintenance surfaces.

## (3) Risks

- The layered config (global + repo-local) creates debugging nightmares. A run behaves unexpectedly because `~/.config/z-harness/config.toml` says `consult.codex = "never"` and the user forgot. The mitigation is mandatory `config_resolved` event logging (emit the merged effective config at run start, not just shadowed keys).
- Prompt-fragment injection is the riskiest piece. If `consult.codex = "never"` removes a preamble block that sets up context the downstream logic assumes, you get silent behavioral breakage rather than a clean feature toggle. Enum-gated code paths (if/else in command logic) are safer than text removal.
- Schema sprawl: defining 50 knobs before any are used means 45 keys that are never touched accumulate documentation debt. Start with ≤6 keys that have immediate demand.
- Auto-write-on-first-run risks creating unintended git diffs if the user runs inside a repo they didn't mean to configure. Make write-on-first-run opt-in or scoped to the user-global path only.

## (4) Plan implications

First slice is exactly three deliverables: (a) `scripts/config.py` with `get / export-env / ensure-defaults` subcommands, (b) the TOML schema with ≤6 keys (`docs.always_apply`, `notifications.mode`, `routing.auto_escalate`, `archive.retention_days`, `consult.codex`, `consult.gemini`), and (c) `docs/human/config.md` + `docs/llm/config-design.json` wired into INDEX.json. Then migrate exactly two commands (`z-do` for auto-escalate, one plan command for doc-fetcher depth) as proof of concept before touching the other 26. README rewrite is a one-shot edit, completely decoupled from the config work — do it first since it's trivially reversible.

## (5) What would change my mind

If the proof-of-concept migration of two commands reveals that every command reads config differently (some via subagent, some via shell, some via inline Python), then the "env-var as universal interface" approach fails and a more intrusive per-command refactor is required. If users never actually change the default values after initial install, the config system is a complexity tax with no benefit — usage telemetry on the six initial keys after one month would be the signal. If the thin-wrapper/prompt-removal actually produces measurable quality improvements (not just token count reductions), then it earns its complexity.
