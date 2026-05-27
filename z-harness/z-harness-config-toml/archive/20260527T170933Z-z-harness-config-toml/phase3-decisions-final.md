# Phase 3 — Final decisions (post-consult)

Gemini and Codex disagreed on all three flagged decisions. Articulating "one reason each might be wrong" before accepting:

## D5 — config.py public API surface

- **Codex:** keep tentative (`get`, `export-env`, `ensure-defaults`, `explain`). Matches env-var precedent in this codebase.
- **Gemini:** drop `export-env`; use `get` + `dump`+`jq` so the python layer stays "dumb."

**One reason Codex might be wrong:** `export-env` permanently couples the Python parser to shell-safe variable naming. Dotted-key → bash-varname transliteration creates a hidden contract; key renames silently break shell consumers.

**One reason Gemini might be wrong:** Python startup is ~50ms; a command setup that reads 4–5 keys via individual `get` calls pays ~200–250ms vs ~50ms for a single eval. Across 21 skills this compounds.

**Final call: KEEP TENTATIVE** (Codex). Both surfaces exist — `export-env` for the common case of "set all this command's knobs at setup" (fork once); `get` for ad-hoc reads; `explain` for debug. Mitigate Codex's coupling risk by documenting the dotted-key → ENV transliteration rule explicitly in `docs/human/config.md` (lowercase + dot → underscore + uppercase, e.g. `notify.level` → `Z_HARNESS_NOTIFY_LEVEL`).

## D7 — docs.always_apply semantics

- **Codex:** keep tri-state enum `"always" | "smart" | "never"`.
- **Gemini:** plain bool; key-absence = default (use heuristic).

**One reason Codex might be wrong:** `"smart"` embeds drifting heuristic semantics. If a future release changes what "smart" means (e.g. expands which flows count as "light"), all existing user configs silently change behavior.

**One reason Gemini might be wrong:** D4 says `ensure-defaults` writes all keys with comments. "Absence = default" then either contradicts D4 (don't write this key) or becomes impossible to distinguish from "explicitly set to false." `config.py explain docs.always_apply` would have no clean answer for "heuristic" state.

**Final call: KEEP TENTATIVE** (Codex), with one rename: `"smart"` → `"auto"`. "Auto" more clearly signals "library decides" and ages better than "smart." Document the heuristic explicitly in `docs/human/config.md` so changes to its meaning are visible signals, not silent.

## D9 — notify.level API and gate

- **Codex:** `config.py should-notify --event <kind>` subcommand, exit 0/1.
- **Gemini:** `config.py get notify.level` + shell string compare (exit-code-as-boolean is unsafe under `set -e`).

**One reason Codex might be wrong:** Exit-code-as-boolean is genuinely unsafe with `set -e` (or `set -eo pipefail`). One bash flip and notifications silently die.

**One reason Gemini might be wrong:** Pushing gate logic into every command means future gate extensions (rate limiting, dedup, multi-event eval) require N-command rewrites instead of one helper change.

**Final call: COMPROMISE.** Keep the `should-notify --event <kind>` subcommand BUT make it always exit 0; print `yes` or `no` on stdout. Commands invoke as:
```bash
[ "$(bash $PLUGIN_ROOT/scripts/config.py should-notify --event approval)" = yes ] && <emit>
```
This is `set -e` safe, explicit, future-proof, and centralizes gate logic in the resolver.

---

## Consult interactions / cross-cutting findings

- Both consultants independently flagged **schema sprawl** as the highest-impact long-term risk. Cap at ≤6 keys for slice 1; refuse additions until a second user asks. → Codified as a "do not add knobs in this slice" guardrail in PLAN.md.
- Both consultants endorsed `explain` as load-bearing for layered-config debuggability. Keep.
- Both consultants endorsed `config_resolved` event emission (precedent: `provider_shadowed`).
- Codex flagged "enum-driven fragments, never freeform user text → prompt" — applies to slice 3 (prompt-fragment injection), not slice 1. Noted in PLAN.md non-goals.

## Shortcuts taken? None.

No shortcuts in this slice. The slice itself is *already* a shortcut over the full Codex framing (we're not building prompt-fragment injection, consult prefs, escalation budgets, archive retention — those are slice 2 and 3).
