MODE: design-review

CONTEXT: Layered TOML config for z-harness Slice 1. Precedent: `scripts/resolve-provider.py` (layered JSON with global + repo shadowing, emits `provider_shadowed` events). Three decisions flagged for consultation.

## Precedent code pattern

From resolve-provider.py:
- Layered loading: global (`~/.config/z-harness/providers.json`) → repo (`.z-harness/providers.json`), repo wins
- Validation separate from merge (validate each provider entry AFTER merge)
- Schema enforced in code (not JSON schema file)
- Shadow detection: per-key dedup guard via PPID stamp file in /tmp; stderr warn + JSON event
- Exit codes: 0 success, 1 unresolvable, 2 schema violation
- Export model: single JSON output, caller parses it

## D5 — config.py public API surface

**Tentative:** Subcommands `get <dotted.key>`, `export-env --for <command>`, `ensure-defaults`, `explain <key>`. Commands eval the export-env output at setup. No `should-notify` subcommand — handled separately in D9.

**Alternatives:** just `get` + shell-side env tests; sourceable env file.

**One concrete failure mode:** If `export-env` uses dotted-key naming (notify_level="all") and scripts then eval bash-unsafe characters in the value (e.g., a path with spaces), shell injection is possible unless the exporter quotes all output. The tentative doesn't address this.

## D7 — docs.always_apply semantics

**Tentative:** Tri-state enum `"always" | "smart" (default) | "never"`. `"smart"` = current heuristic (light flows skip doc-fetcher; heavy flows always dispatch). `"always"` = light flows also dispatch. `"never"` = light flows skip even when heuristic would call.

**Alternatives:** plain bool; per-command override map.

**One concrete failure mode:** No specification of which flows are "light" and which are "heavy." Commands that migrate to this setting won't know whether to obey `"smart"` without reading the heuristic logic from the orchestrator or a central registry. If that logic drifts, `"smart"` becomes a footgun.

## D9 — notify.level API and gate

**Tentative:** Enum `"off" | "approval_only" | "all"` (matches README docs). Slice 1 IMPLEMENTS the gate (currently documented but never read). API: `config.py should-notify --event <kind>` returns exit 0 if notification should fire, exit 1 otherwise. Migrated commands wrap PushNotification with `bash $PLUGIN_ROOT/scripts/config.py should-notify --event approval && <emit>`.

**Alternatives:** env-var shell test; bool config.

**One concrete failure mode:** Exit-code-based APIs in shell are fragile when piped — e.g., `config.py should-notify --event approval && emit_notification | log` will log a failure without signaling it back up. Also, for `--event approval` to work, every command must agree on what events exist (approval, what else?). No central registry of valid event names.

---

TASK: For EACH decision (D5, D7, D9), give:
(a) ONE concrete reason the tentative is wrong (brief, specific)
(b) Your recommendation (pick one alternative or modify the tentative)
(c) What would change your mind on that recommendation

Be concrete and brief.
