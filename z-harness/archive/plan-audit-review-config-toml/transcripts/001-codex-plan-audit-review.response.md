## Codex Consultation: Plan Audit Review — z-harness TOML config

**10 New Findings:**

1. **BLOCKER** — SPEC.md:120 / commands/z-plan.md:23 / commands/z-do.md:16
   `config_resolved` event is gated on $Z_HARNESS_RUN, but existing setup assigns RUN without exporting it as Z_HARNESS_RUN. Event will never emit.
   Recommendation: Export Z_HARNESS_RUN before config.py export-env call.

2. **MAJOR** — SPEC.md:246, SPEC.md:248, TASKS.md:94
   Examples use $PLUGIN_ROOT but current commands use ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}; under set -u, $PLUGIN_ROOT breaks migrations.
   Recommendation: Use consistent PLUGIN_ROOT variable throughout.

3. **MAJOR** — SPEC.md:32, SPEC.md:54, SPEC.md:59
   schema_version is in DEFAULTS but export-env says 'all defined keys' while transliteration only covers 2-level dotted keys.
   Recommendation: Explicitly exclude metadata keys or define their env mapping.

4. **MAJOR** — SPEC.md:280 / TASKS.md:134
   /z-update is supposed to call ensure-defaults but no task modifies it.
   Recommendation: Add task for /z-update modification or remove the promise.

5. **MAJOR** — TASKS.md:5, TASKS.md:14, TASKS.md:43
   T001 ships as own PR while adding docs/human/config.md link before file exists.
   Recommendation: Move T001 into docs PR or defer config link until T003.

6. **MAJOR** — TASKS.md:91, TASKS.md:107
   'Whichever holds the dispatch logic' is unsafe — both commands/* and skills/*/SKILL.md copies can diverge.
   Recommendation: Update both files or establish single source of truth.

7. **MAJOR** — TASKS.md:73
   T005 smoke tests miss critical edge cases: repo precedence, explicit missing $Z_HARNESS_REPO_CONFIG, invalid-enum fallback, schema mismatch, parse errors, event de-dupe.
   Recommendation: Expand smoke suite to cover these before migrations.

8. **MAJOR** — TASKS.md:122
   T008 writes real ~/.config/z-harness/config.toml, risking developer config corruption.
   Recommendation: Run e2e with temp XDG_CONFIG_HOME and cleanup.

9. **MAJOR** — SPEC.md:113 vs SPEC.md:283
   Contradictory behavior for global invalid enum: one section says 'warn + fallback', another says 'exit 2'.
   Recommendation: Qualify edge case by layer (global vs repo/env) and add tests for both paths.

10. **MINOR** — SPEC.md:123
    De-dupe path embeds raw $Z_HARNESS_RUN (env-controlled, may contain slashes or hostile chars).
    Recommendation: Sanitize or hash run id before constructing temp-file path.
