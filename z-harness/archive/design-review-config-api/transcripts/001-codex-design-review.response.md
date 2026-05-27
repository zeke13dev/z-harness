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
