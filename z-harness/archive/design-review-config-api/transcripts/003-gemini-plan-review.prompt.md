# Mode: plan-review

## Artifacts

### SPEC.md
z-harness TOML config (slice 1):
- Single Python helper `scripts/config.py` for layered TOML config
- Layering: built-in defaults → global TOML (~/.config/z-harness/config.toml) → repo-local (.z-harness/config.toml) → env vars
- Two functional knobs in slice 1: `notify.level` (off|approval_only|all) and `docs.always_apply` (always|auto|never)
- Five subcommands: `get <key>` | `export-env [--for <cmd>]` | `ensure-defaults` | `explain <key>` | `should-notify --event <kind>`
- `should-notify` always exits 0, prints yes/no on stdout
- New docs: docs/human/config.md (8 sections) + docs/llm/config-design.json
- README rewrite to pitch + install + 3 quickstart commands + pointers (cut content relocated to docs/human/)
- Two migrated commands: /z-plan and /z-do as proof of pattern

### PLAN.md
Ordered phases A–F:
- Phase A: Write config.py + config.sh + manual test
- Phase B: Write human/config.md, llm/config-design.json, update INDEX.json
- Phase C: Rewrite README, relocate cut content
- Phase D: Migrate /z-do (light flow) — add export-env, gate doc-fetcher on docs.always_apply, wrap PushNotifications
- Phase E: Migrate /z-plan (heavy flow) — add export-env, wrap PushNotifications, document exception that /z-plan ignores docs.always_apply="never"
- Phase F: Manual smoke test + events.jsonl validation

---

## Specific questions for Gemini

1. **What's wrong, missing, or fragile in the SPEC (file by file)?**
   - Any ambiguities in the config layer precedence?
   - Validation logic sound (exit codes, schema_version check, enum constraints)?
   - The `ensure-defaults` idempotency guarantee — correct as stated?
   - Shell quoting in export-env — any edge cases (spaces, special chars in values)?

2. **Slice scope: Is it right?**
   - Would you cut anything further?
   - Is anything in non-goals actually load-bearing for slice 1?
   - Concretely: does /z-do + /z-plan migration really prove the pattern, or would one command suffice?

3. **Edge cases SPEC misses?**
   - Symlinks in config paths (e.g., ~/.config is a symlink)?
   - Unicode in TOML keys or values?
   - TOML syntax corner cases (e.g., dotted keys in TOML clashing with the transliteration rule)?
   - What if `$Z_HARNESS_REPO_CONFIG` points to a nonexistent file?

4. **Migration order: `/z-do` then `/z-plan` — defensible?**
   - Would you reverse (heavy flow first)?
   - Or migrate both in parallel as part of the same commit?
   - Any risk that /z-do's doc-fetcher conditional becomes a testing liability?

5. **The `should-notify` API — final critique of the always-exit-0-print-yes/no pattern?**
   - Are there scenarios where a command needs to know *why* the gate returned "no"? (e.g., distinguish "notify=off" from "event=unknown"?)
   - Is always-exit-0 sufficient for `set -e` safety?
   - Should the event kinds be declared in schema or left open-ended?

6. **Any DRY/KISS/SOLID violations I missed?**
   - Is the DEFAULTS dict + VALIDATORS dict split the right granularity, or should schema live elsewhere?
   - Does `export-env --for <command>` (accepted but ignored) introduce needless complexity, or is it a reasonable forward-compatible placeholder?
   - Should the translator rule (dotted → Z_HARNESS_<SECTION>_<KEY>) be testable/documented in config.py, or is inline doc sufficient?

---

## Context

### Shell quoting in export-env
The SPEC says values are shell-quoted with `shlex.quote`. Example transliterations:
- `notify.level = "approval_only"` → `export Z_HARNESS_NOTIFY_LEVEL='approval_only'`
- If user sets a value with spaces (not in slice 1, but forward-compatibility): `export Z_HARNESS_SOME_VAL='value with spaces'`

### config_resolved event
Fired once per `$Z_HARNESS_RUN` with payload:
```json
{
  "values": {"notify.level": "approval_only", ...},
  "sources": {"notify.level": "defaults", ...}
}
```
De-dup keyed by temp file under $TMPDIR.

### Known patterns from codebase
- `scripts/resolve-provider.py` (precedent for env override pattern)
- `providers.json` schema_version=1 (exit code 2 on mismatch)
- Two-tier docs: docs/human/ + docs/llm/INDEX.json (LLMs read via doc-fetcher)
- `/z-plan` and `/z-do` are entry points; other 26 commands deferred to slice 2+

---

## Ask

Critique this plan: What's wrong, missing, or fragile? For each of the six questions above, be concrete and brief. List discrete issues; do not repeat SPEC back.
