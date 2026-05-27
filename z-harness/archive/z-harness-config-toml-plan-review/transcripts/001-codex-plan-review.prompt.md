MODE: plan-review

SPEC and PLAN for z-harness TOML config (slice 1). Full texts below.

---

# SPEC excerpt (questions 1-6)

File 1: scripts/config.py — Python helper for reading, layering, and exporting z-harness TOML config.
- Layered precedence: built-in defaults → ~/.config/z-harness/config.toml → .z-harness/config.toml (repo) → env vars (Z_HARNESS_<SECTION>_<KEY>)
- DEFAULTS = { schema_version: 1, notify.level: "approval_only" (off|approval_only|all), docs.always_apply: "auto" (always|auto|never) }
- Subcommands:
  - get <dotted.key> — resolves and prints raw scalar value
  - export-env [--for <command>] — prints export lines for env var setup (per-command filtering accepted but ignored in slice 1)
  - ensure-defaults — writes ~/.config/z-harness/config.toml if missing (never repo-local)
  - explain <dotted.key> — prints value + source layer for each override
  - should-notify --event <kind> — **Always exits 0**, prints yes|no based on notify.level and event kind
- Validation: schema_version must == 1; invalid enum values exit 2; TOML parse errors exit 2
- Event: config_resolved emitted once per $Z_HARNESS_RUN (run-scoped de-dup)
- Error handling: missing config skipped silently; permission denied → exit 4

File 2: scripts/config.sh — thin wrapper exec'ing config.py

File 3: docs/human/config.md — full human reference (what this is, file locations, the knobs, transliteration rule, CLI reference, examples, config_resolved event, future knobs)

File 4: docs/llm/config-design.json — compact LLM concept entry

File 5: docs/llm/INDEX.json — modified to add config-design entry

File 6: README.md — rewritten to target shape (pitch + install + 3 quickstart commands + pointers to docs)

File 7: commands/z-plan.md — migrated (config.py export-env setup, should-notify guards on PushNotifications, Phase 1 conditionals on docs.always_apply with exception for heavy flows)

File 8: commands/z-do.md — migrated (same export-env setup, should-notify guards, docs.always_apply interpreted in shell logic for light flow)

Behavioral invariants:
- After eval "$(... export-env)", $Z_HARNESS_NOTIFY_LEVEL and $Z_HARNESS_DOCS_ALWAYS_APPLY guaranteed valid
- should-notify is ONLY place that interprets notify.level
- docs.always_apply interpreted in command shell logic; heavy flows ignore "never"
- config_resolved fires once per command run, de-duped per $Z_HARNESS_RUN

Edge cases documented:
- First invocation with no config file: defaults apply silently
- Repo in CI with no ~/.config: defaults apply; no errors
- Malformed user TOML: exit 2 (intentional, not silent)
- Typos in enum values: exit 2 (prevents silent failure)
- Invoked outside /z-* run (no $Z_HARNESS_RUN): works, no event emitted
- Concurrent /z-* runs: separate $Z_HARNESS_RUN, separate events, temp-file de-dup is run-keyed

Non-goals: prompt-fragment injection (slice 3), consult prefs / escalation budgets / archive retention (slice 2), per-command filtering in export-env (slice 2), --init-repo flag (slice 2), migrating skills/ (slice 2), other 26 commands (slice 2+)

DRY: schema in one place (DEFAULTS + VALIDATORS in config.py); docs reference, don't duplicate
KISS: no prompt-fragment injection, no per-command filtering, two knobs, four subcommands + one gate
SOLID: SRP — config.py only handles loading/resolution; gating policy decisions in should-notify

---

# PLAN excerpt (migration order, Phase A–F)

Phase A: Write config.py + config.sh + manual tests
Phase B: Write docs/human/config.md + docs/llm/config-design.json + add to INDEX.json + docs/human/INDEX.md
Phase C: Rewrite README.md to target shape; relocate old content to docs/human/
Phase D: Migrate /z-do (light flow proof): export-env setup + docs.always_apply conditional + should-notify guards
Phase E: Migrate /z-plan (heavy flow proof): export-env setup + should-notify guards + add "heavy flows ignore never" note to docs
Phase F: Validation (smoke tests + events.jsonl inspect)

Decisions table includes:
- D3: Layer order matches resolve-provider.py precedent
- D4: ensure-defaults writes user-global only
- D5: API = get + export-env + ensure-defaults + explain + should-notify (both consultants reviewed)
- D6: One config_resolved event per $Z_HARNESS_RUN
- D9: should-notify --event always exits 0, prints yes|no (set-e safe, future-proof)
- D12: README target shape mitigates Gemini's README-as-LLM-orientation risk

---

# Your review (6 questions)

1. What's wrong, missing, or fragile in the SPEC (file by file)?
2. Is the slice scope right — would you cut anything further, or is anything in non-goals actually load-bearing for slice 1?
3. Edge cases SPEC misses?
4. Migration order: Phase D (/z-do) then Phase E (/z-plan) — defensible? Or should heavy-flow migration come first?
5. The should-notify API — final critique of the always-exit-0-print-yes/no pattern?
6. Any DRY/KISS/SOLID violations I missed?

Be brief and concrete. List discrete issues; don't repeat the SPEC back.
