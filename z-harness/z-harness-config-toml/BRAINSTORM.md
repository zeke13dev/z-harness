---
artifact: brainstorm
slug: z-harness-config-toml
generated_at: 2026-05-27T17:04:48Z
command: /z-brainstorm
input_hash: 8a5ada9253548171
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: codex
---

## Framing: claude

### Framing
Primarily a surface-area problem, not an architectural one. Users repeatedly touch only a handful of knobs (consult prefs, doc-fetcher gating, notification policy, plans dir). The config should be a stable external hook for those knobs — not a comprehensive control plane. README-slim is decoupled; ship it first.

### Core hypothesis
Treat the TOML config as a **schema'd env-var replacement layer**. A single `scripts/config.py` with `get | export-env | ensure-defaults` reads layered TOML at the start of each skill and exports env vars the existing commands already understand. Retrofits the whole harness without rewriting any command's internals. Defer prompt-fragment injection until the env-var layer is proven.

### Risks
- Layered config makes "why did this happen?" hard to debug — mitigate with a `config_resolved` event listing effective values + their source layer.
- Removing prompt context risks regressing model behavior in ways that don't show up in token counts but do show up in review-failure rate.
- Schema sprawl: every contributor wants a new key. Need a "load-bearing or noise?" rubric and a deprecation policy.
- Auto-write-on-first-run creates unintended git diffs. Scope auto-write strictly to the user-global path; repo-local stays opt-in.

### Plan implications
Three deliverables in order: (a) `scripts/config.py get|export-env|ensure-defaults` + a 6-key schema, (b) `docs/human/config.md` + `docs/llm/config-design.json` wired into INDEX.json, (c) migrate exactly two commands (e.g. `z-do`, `z-implement-all`) as proof. README rewrite is independent — do it first because trivially reversible.

### What would change my mind
- If commands need heterogeneous config access (some need structured nested data, not flat env), env-var universality breaks.
- If logging shows users almost never change defaults, the whole effort is unjustified.
- If a thin-wrapper prompt-fragment prototype shows measurable *quality* gain (not just token count), bump fragment injection earlier.

---

## Framing: codex

### Framing
Config is a **runtime contract, not a preference dump**. The 28 commands and 17 agents already have implicit policy decisions baked into prose — escalation budgets, consult phases, doc-fetcher routing, retention. The right abstraction is *named policy decisions* consumed by commands, with raw TOML keys as the user-facing surface but a resolver in the middle that translates keys → policies. Anything that only changes wording stays behind the resolver, not in raw TOML.

### Core hypothesis
**Layered TOML with deterministic merge order** (built-in defaults → `~/.config/z-harness/config.toml` → repo `.z-harness/config.toml` → env overrides for CI), exposed through a single Python helper:

```
scripts/config.py get <key>
scripts/config.py export-env --for <command>
scripts/config.py ensure-defaults
scripts/config.py explain <key>     # effective value + source layer
```

Commands consume shell-exported values. The `explain` subcommand is the load-bearing debuggability move — it makes layered config tractable. Schema lives in code (Python), not in a separate file, so resolver and schema cannot drift.

### Risks
- Premature schema sprawl across 28 commands — start with ≤6 keys, refuse the rest until a second user asks.
- Freeform prompt injection — prefer enum-driven fragments where TOML value is an enum and the resolver maps enum → static fragment, never arbitrary user text → prompt.
- Invisible layered behavior — emit `config_resolved` events (precedent: providers.json's `provider_shadowed`).
- Auto-write file churn — only write `~/.config/z-harness/config.toml` with minimal comments; never write repo-local automatically.

### Plan implications
First slice = **one schema + one loader + one docs page + two migrated knobs only**: `notify.level` (replaces `Z_HARNESS_NOTIFY`) and `docs.always_apply` (gates doc-fetcher in flows where it's currently optional). Docs wired into `INDEX.json`. No prompt-fragment injection in slice 1 — prove the loader works, then expand to consult prefs and escalation budgets in slice 2. Slice 3 adds the fragment mechanism once we know which fragments actually move quality.

### What would change my mind
- If a shared shell prelude already exists across skills, change the loader strategy to inject into the prelude rather than per-skill.
- If TOML write-back proves formatting-hostile (round-tripping comments/order), switch to "config is read-only on disk; defaults are in code".
- If users want per-phase consult precision day one, schema needs richer structure earlier.
- If users want per-repo behavior far more than personal defaults, drop the user-global layer.

---

## Framing: gemini

### Framing
The goal is a transition from hardcoded/env-heavy to a **configuration-driven runtime where prompts themselves are dynamically assembled**. Config is not just settings — it's an active layer that prepends a `<runtime_config>` block into every skill invocation. README becomes pure quickstart; reference material moves out aggressively. The bet is that the static token footprint of skill prompts can shrink substantially by replacing "if-then-else" prose with a structured block the agent reads.

### Core hypothesis
**Policy-Fragment Injection.** Build `scripts/manage-config.py` (read/merge/auto-defaults) and `scripts/inject-context.sh` (interception layer that prepends a `<runtime_config>` block to the skill prompt at execution). Layered fallback: `~/.config/z-harness/config.toml` → `./.z-harness/config.toml`. Strip env-var checks and inline escalation prose from skill `.md` files and refactor them to obey the injected block. Claim: 20–40% token reduction on skill preambles + a single source of truth for behavior.

### Risks
- Shell-native TOML parsing is brittle; Python `tomllib` adds a runtime dependency.
- Opaque prompt injection — when an agent misbehaves, root cause splits across base `.md`, TOML, and injector. Hard to bisect.
- Schema-vs-LLM drift: the model's training won't include your TOML keys, so renames silently degrade behavior.
- **README-slim has its own risk** — the README is *also* LLM workspace orientation. Aggressive trimming may degrade the harness's own self-understanding when an agent greps the repo cold. (Genuinely distinct risk the other two missed.)
- Loss of "why" — replacing procedural rules with declarative config strips the rationale the model uses for edge cases.

### Plan implications
- Gut README to pitch + install + pointers; migrate command/agent specifics to `docs/human/`.
- Build TOML manager + injection layer together — meaningless apart.
- Migrate `/z-plan` first (highest token-savings target), then fan out.
- Update `docs/human/` + `docs/llm/INDEX.json` with the schema.
- Requires refactoring ~all 21 skills before full benefit — value curve is back-loaded.

### What would change my mind
- Token profiling shows savings negligible vs maintenance cost.
- Users find auto-generated `.z-harness/` files to be repo pollution and prefer env vars.
- Host (Claude Code) ships native config management that makes this redundant.

---

## Anti-bias check

I am the orchestrator running on Claude; per protocol, every Claude-favoring pick gets explicit justification.

**Framing.** Codex wins. It identifies the right abstraction (named policy decisions, with TOML as surface and resolver as translator) rather than treating the problem as either pure surface-area (Claude) or pure prompt re-architecture (Gemini). Claude's framing is sound but smaller-than-the-actual-question; Gemini's framing assumes prompt injection is the whole point, which is one of three things the user asked about.

**Core hypothesis.** Codex wins on completeness — the `explain` subcommand directly addresses the layered-config debuggability problem all three identified as a risk. Claude's "schema'd env-var replacement" is a strict subset of Codex's design. Gemini's policy-fragment injection is bolder but is exactly the part of the project that should come *after* a working loader exists.

**Risks.** Gemini wins. The only ideator to flag README-slim as having its own load-bearing-context risk — the README is also LLM orientation material. Codex and Claude both missed this. Codex's enum-driven-fragment risk and `config_resolved` event mitigation are also valuable; Claude's "users may never change defaults" is a useful falsifier the others missed.

**Plan implications.** Codex wins. Smallest credible first slice is most concrete and immediately shippable (one schema, one loader, one docs page, two specific keys). Claude's "README first" sequencing should be folded into Codex's plan — not in conflict. Gemini's "migrate /z-plan first" is the highest-risk first slice (touches the most-used, most-load-bearing skill); wrong place to prove a new mechanism.

**What would change my mind.** Tie between Codex and Claude — both produced concrete, testable falsifiers. Gemini's falsifiers ("if host ships native config") are exogenous and not actionable.

**Net.** Codex is the strongest framing on substance. Borrow Gemini's README-as-LLM-orientation risk; borrow Claude's "auto-write only to user-global" guardrail and "README rewrite first because reversible" sequencing.

## Orchestrator recommendation

**Codex framing**, supplemented by (a) Gemini's README-as-LLM-orientation risk, (b) Claude's "auto-write only to user-global path" guardrail, and (c) Claude's "README slim first because independent and reversible" sequencing. The Codex first-slice (notify.level + docs.always_apply, two migrated commands, `explain` subcommand) is the right MVP.

## User choice

**Codex framing** (orchestrator recommendation accepted).

Verbatim Codex framing reproduced for `/z-plan` consumption:

### Framing
Config is a **runtime contract, not a preference dump**. The 28 commands and 17 agents already have implicit policy decisions baked into prose — escalation budgets, consult phases, doc-fetcher routing, retention. The right abstraction is *named policy decisions* consumed by commands, with raw TOML keys as the user-facing surface but a resolver in the middle that translates keys → policies. Anything that only changes wording stays behind the resolver, not in raw TOML.

### Core hypothesis
**Layered TOML with deterministic merge order** (built-in defaults → `~/.config/z-harness/config.toml` → repo `.z-harness/config.toml` → env overrides for CI), exposed through a single Python helper:

```
scripts/config.py get <key>
scripts/config.py export-env --for <command>
scripts/config.py ensure-defaults
scripts/config.py explain <key>     # effective value + source layer
```

Commands consume shell-exported values. The `explain` subcommand is the load-bearing debuggability move. Schema lives in code (Python), not in a separate file, so resolver and schema cannot drift.

### Risks (with supplements from anti-bias)
- Premature schema sprawl — start with ≤6 keys.
- Freeform prompt injection — prefer enum-driven fragments; resolver maps enum → static fragment.
- Invisible layered behavior — emit `config_resolved` events.
- Auto-write file churn — write only `~/.config/z-harness/config.toml` (Claude's guardrail).
- **README-slim risks LLM orientation** — README is also agent-cold-orient material; don't gut, restructure (Gemini's risk).

### Plan implications
First slice = **one schema + one loader + one docs page + two migrated knobs**: `notify.level` (replaces `Z_HARNESS_NOTIFY`) and `docs.always_apply`. Slice 2 = consult prefs + escalation budgets. Slice 3 = enum-driven prompt-fragment mechanism. **Sequencing tweak (from Claude):** ship the slim README first as an independent, reversible PR before any config work begins.

### What would change my mind
- Shared shell prelude exists → inject there.
- TOML write-back formatting-hostile → read-only on disk, defaults in code.
- Per-phase consult precision needed day one → richer schema earlier.
- Per-repo desire dwarfs personal-defaults desire → drop user-global layer.
