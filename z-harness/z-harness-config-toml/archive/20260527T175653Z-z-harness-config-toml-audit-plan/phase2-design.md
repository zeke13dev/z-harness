# Phase 2 — Design audit

## KISS
- Tri-state enum for `docs.always_apply` is over-engineered given /z-do has no heuristic today (per F1). Binary is the KISS fit.
- `--for <command>` already correctly dropped in Phase 7 review.
- `should-notify` subcommand is appropriately small surface. OK.
- Five subcommands in `config.py` is on the upper edge of acceptable; each has a distinct purpose so this is acceptable.

## DRY
- Schema in `DEFAULTS` (Python) + `VALIDATORS` (Python) + duplicated in `docs/human/config.md` (table) + duplicated in `docs/llm/config-design.json` (invariants). That's 4 copies. SPEC says docs *reference, don't duplicate* — but documentation needs the enum values inline to be useful. **This is acceptable** for slice 1 (two knobs only), but flagged for slice 2: with 6+ knobs, the docs duplication becomes maintenance load. Future: consider auto-generating the docs/human/config.md "knobs" table from `DEFAULTS`/`VALIDATORS` at release time.

## SOLID
- SRP: `config.py` does loading + resolution + gating. Three responsibilities. Could split into `loader.py` + `gate.py`. **Accepted** for slice 1 — single file is easier to audit; split when a second gate appears.
- Open/Closed: adding a knob = append to DEFAULTS + VALIDATORS. Good.
- DIP: `should-notify` is the only "policy" code; lives inline. Acceptable; pull into a separate module if a second policy emerges.

## Defensive bloat
- Many exit codes (0,2,3,4). Truth table makes them explicit, so not bloat — just specificity. OK.
- `O_EXCL` de-dup is the minimum mechanism for atomic dedup. OK.

## Performance
- `config.py` invoked per command, paying Python startup ~50ms. With `export-env` doing one fork that sets all envs, fine. Frequent `get` calls in shell loops would compound; SPEC implicitly uses `export-env` not iterated `get`. OK.
- TOML parsing is trivial size; no perf concern.

## Security
- `shlex.quote` on all values in `export-env` (SPEC explicit). Mitigates shell injection if knob values came from user TOML.
- No prompt-fragment injection in slice 1 — Codex's "freeform user text → prompt" risk is correctly deferred.
- TOML parser is stdlib; no parser exposure.
- `git rev-parse --show-toplevel` is executed on every command setup; minor cost but no security concern (controlled command, no user-influenced args).

## Style
- No `STYLE.md` in this repo. N/A.

## Findings
### F5 (MINOR): doc duplication is a slice-2 footgun
With two knobs, four copies of schema info is fine. With six+ knobs, it becomes drift-prone. Recommendation: add note to PLAN.md non-goals / slice-2 mandate: "auto-generate docs/human/config.md knobs table from DEFAULTS/VALIDATORS before adding the 3rd knob."

### F6 (MINOR): `config.py` is 5 subcommands + gating logic in one file
SRP softly violated. Acceptable in slice 1; revisit when a second policy gate is added.

### F7 (NIT): config.py invoked twice per command setup
Once for `eval "$(... export-env)"` and once for each `should-notify` guard. With ~4 PushNotification sites per command × 50ms python startup = ~200ms added latency per command, all of which is python-startup-bound. Not blocking but worth noting. Mitigation if it bites later: have `should-notify` short-circuit by reading the env var that `export-env` already set, bypassing TOML parse on second invocation.
