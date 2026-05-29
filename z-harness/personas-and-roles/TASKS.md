# TASKS — personas-and-roles (v1)

Phases map to PLAN.md sections 1-9. Tasks within a phase can run in parallel unless a `**Deps:**` line says otherwise. Implementer model is set by `complexity-classifier` stamps applied at plan finalization.

---

## T001 — Config loader: 3-level TOML nesting [x]

> Done cycle 2; reviewer-flagged error-message typo fixed. 156 tests pass.

**Files:** `scripts/config.py`, `scripts/test_config.py`

**Description:** Extend `_KEY_RE` in `scripts/config.py` to support up to 3-level keys (`section.subsection.key`). `load_config()` must parse 3-level nested tables into the in-memory dict. `cmd_export_env` skips any key whose first segment is `roles`. `cmd_explain` traverses 3-level paths. Merge across the 4 layers (defaults/global/repo/env) stays per-field — when repo TOML sets only one subkey of a nested table, the other subkeys from global are preserved.

**Acceptance:**
- [ ] `_KEY_RE` accepts `roles.z_plan.consultant_primary.persona`; rejects `roles..foo`, `roles.z_plan.role.field.extra` (4 levels), and any key with uppercase or hyphens.
- [ ] Round-trip: `[roles.z_plan.consultant_primary] persona = "X"` parses correctly via `load_config()`.
- [ ] `cmd_export_env` outputs no `Z_HARNESS_ROLES_*` lines.
- [ ] `cmd_explain roles.z_plan.consultant_primary.persona` shows the value + source layer.
- [ ] Per-field merge test: global defines `persona = "A"`; repo defines `model = "opus"`; merged effective binding has both.
- [ ] Existing 2-level keys (`notify.level`, `workflow.audit_to_amend`) still resolve unchanged.

**DOCS:** config
**Complexity:** medium

---

## T002 — `/z-config migrate` subcommand [x]

> Done via user's parallel commit 87ae925 (cmd_migrate + _migrate_roles_data already in HEAD).

**Files:** `scripts/config.py`, `scripts/test_config.py`

**Deps:** T001

**Description:** Add `cmd_migrate` to `scripts/config.py`. Rewrites old provider names (`codex`, `gemini`, `claude`) in any `roles.*.runtime` config value to the new `-cli` form. Atomic via temp-file rename. Idempotent — re-running on already-migrated config is a no-op.

**Acceptance:**
- [ ] `python3 scripts/config.py migrate` rewrites `runtime = "codex"` → `runtime = "codex-cli"` in both global and project TOML when present.
- [ ] Idempotent: running twice produces no diff on the second run.
- [ ] Returns non-zero exit only on I/O error; zero on no-op.
- [ ] Test: pre-seed both layers with mixed old/new names; run migrate; assert all old names rewritten and existing new names untouched.

**DOCS:** config
**Complexity:** low

---

## T003 — Provider schema v2: schema + JSON Schema + v1 upgrade [x]

> Done cycle 3; resolved schema/validator coupling. 16 tests pass.

**Files:** `runtime/contract/provider.schema.json`, `scripts/resolve-provider.py`, `runtime/compat.py`, `runtime/tests/test_compat.py` (or analogous)

**Description:** Bump `runtime/contract/provider.schema.json` to accept `version: 2` with new optional fields: `model_arg_template` (array of strings), `model_env_var` (string), `default_model` (string), top-level `aliases` (object mapping old → new provider names). v1 entries continue to load (in-memory upgrade: set new fields to `null`; default `args_template: []` and `kind: "cli"` if missing). Update `resolve-provider.py` load path to perform the upgrade.

**Acceptance:**
- [ ] v2 JSON Schema validates the v2 example in SPEC §B1.
- [ ] v1 file (no `model_arg_template`, no `aliases`) loads without error; in-memory record has the new fields as `null`.
- [ ] `resolve-provider.py` returns the upgraded record with `model_arg_template`, `model_env_var`, `default_model` populated (or `null`).
- [ ] Existing tests in `runtime/tests/test_compat.py` pass against v2.

**DOCS:** providers-registry
**Complexity:** medium

---

## T004 — `compose_argv` + null-template safety + model_env_var [x]

> Done cycle 2; clean review. compose_argv early-exit + build_env upfront model resolution + warning gating fixed.

**Files:** `scripts/resolve-provider.py`, `runtime/compat.py`, `runtime/tests/test_compat_providers.py`

**Deps:** T003

**Description:** New `compose_argv(provider_dict, effective_model)` returns the full argv list. Steps: (1) start with `provider['args_template']` copy; (2) if `model_arg_template` is not null, render `{model}` substitution and append; (3) the function is pure (no env mutation). Companion `build_env(provider_dict, effective_model, base_env)` returns a dict to use for the subprocess; merges `base_env` with `{model_env_var: effective_model}` when `model_env_var` is set. If both arg template and env var are set, the composer uses the arg template path and warns once via `model_env_var_ignored` log.

**Acceptance:**
- [ ] `compose_argv` on a v2 provider returns `args_template + rendered model_arg_template`.
- [ ] `compose_argv` on a v1 provider (null template) returns `args_template` only — no model arg appended, no exception.
- [ ] `build_env` returns `{...base_env, model_env_var_value: model}` when `model_env_var` set and `model_arg_template` is null.
- [ ] `build_env` returns `base_env` unchanged when neither is set.
- [ ] Empty-string model semantics: `compose_argv(..., effective_model="")` uses `default_model` from provider record; raises if both are empty/null.

**DOCS:** providers-registry
**Complexity:** medium

---

## T005 — Provider name aliases + memoized deprecation event [x]

**Files:** `scripts/resolve-provider.py`, `runtime/compat.py`

**Deps:** T003

**Description:** When `resolve(role)` is called, the looked-up provider name is passed through `aliases` first; if it matches an old name, the resolver substitutes the new one and emits `provider_alias_used` via `log-event.sh`. The emission is memoized at module scope: a process-local set keyed on the old-name string ensures one emission per (process, alias). Legacy `providers.json` `roles` fallback also passes through alias resolution.

**Acceptance:**
- [ ] `aliases: {codex: codex-cli}` + role bound to `codex` resolves to `codex-cli` and emits `provider_alias_used` once.
- [ ] Same alias resolved 100 times in one process → exactly one `provider_alias_used` event.
- [ ] Two different aliases (`codex`, `gemini`) → two events, one each.
- [ ] When resolution falls through to legacy `providers.json.roles[role] = "codex"`, both `legacy_provider_roles_used` and `provider_alias_used` fire.

**DOCS:** providers-registry
**Complexity:** medium

---

## T006 — Persona file schema + loader (+ `where` subcommand) [x]

> Done cycle 2 + manual patch. 27 tests pass. resolve/list-bindings/validate/read deferred to T007 (have stubs).

**Files:** `personas/README.md` (new), `scripts/resolve-persona.py` (new), `scripts/resolve-persona.sh` (new), `runtime/contract/persona.schema.json` (new), tests

**Scope note:** T006 includes `list-personas` AND `where <name>` subcommands. `resolve`, `list-bindings`, `validate`, `read` are T007.

**Deps:** T001

**Description:** Define persona file format: markdown with YAML frontmatter (`name`, `description`, optional `compatible_roles` list, optional `contract` enum {freeform, review-verdict, strict-json}); body = prompt prefix. JSON Schema in `runtime/contract/persona.schema.json`. Loader scans three layers in order: `personas/builtin/` (shipped), `~/.config/z-harness/personas/`, `<repo>/.z-harness/personas/`. Last layer wins per name. Emit `persona_shadowed` once per (process, name) on collision.

**Acceptance:**
- [ ] `personas/README.md` documents the schema with one example persona.
- [ ] `resolve-persona.py list-personas` returns JSON array with `{name, source_layer, path}` per persona across all three layers.
- [ ] Layered storage: a persona present in all three layers shows three entries in `where`, one in `list-personas` (the winner), and emits `persona_shadowed` exactly once.
- [ ] Schema validation rejects non-kebab names, dotted names, names with slashes.
- [ ] `compatible_roles` is optional; absence is valid.

**DOCS:** personas-and-roles
**Complexity:** high

---

## T007 — `resolve-persona.py`: resolve/list-bindings/validate/read [x]

**Files:** `scripts/resolve-persona.py`, tests

**Deps:** T006, T001

**Description:** Implement remaining subcommands. `resolve <command> <role>` normalizes the command name (`/z-plan` → `z_plan`), reads TOML, applies resolution order (override → roles.<cmd> → roles.default → providers.json.roles → error), returns `{persona, model, runtime, source, persona_body_path}` JSON. `list-bindings [--command]` walks the resolved bindings. `validate` checks compatible_roles + contract against role registrations. `read <name>` prints frontmatter + body. `where <name>` prints all layer paths defining `<name>`.

**Acceptance:**
- [ ] `resolve z-plan consultant_primary` returns the correct persona/model/runtime for both pre- and post-migration configs.
- [ ] Command-name normalization: `/z-plan` and `z_plan` both resolve to the same binding.
- [ ] `validate` exits non-zero when a default binding references a missing persona.
- [ ] `read <missing>` exits non-zero with an actionable error.
- [ ] `where <name>` prints exactly one line per defining layer in load order.
- [ ] When binding axes resolve from ≥2 different layers, emit `persona_binding_chimera` event with per-axis source layers.

**DOCS:** personas-and-roles
**Complexity:** medium

---

## T008 — Default personas + default TOML bindings [x]

**Files:** `personas/builtin/codex-default-consultant.md`, `personas/builtin/gemini-default-consultant.md`, `personas/builtin/codex-default-reviewer.md`, default config bindings shipped via `cmd_ensure_defaults`

**Deps:** T006

**Description:** Author three persona files from scratch. Each is short (≤30 lines body) and embeds the persona's tone/contract expectations. Update `scripts/config.py` `DEFAULTS` or `cmd_ensure_defaults` to ship `[roles.default.consultant_primary]`, `[roles.default.consultant_secondary]`, `[roles.default.reviewer]` triples per SPEC §E. Verify: `validate` subcommand from T007 passes against the default bindings.

**Acceptance:**
- [ ] All three persona files exist with valid frontmatter (`compatible_roles`, `contract`).
- [ ] Default bindings ship as part of `cmd_ensure_defaults` (or shipped TOML template).
- [ ] `resolve-persona.py validate` passes on a clean install.
- [ ] `resolve z-plan consultant_primary` (with no user TOML) returns the default persona/runtime triple.

**DOCS:** personas-and-roles
**Complexity:** medium

---

## T009 — Role contract declarations [x]

**Files:** `agents/consultant-primary.md`, `agents/consultant-secondary.md`, `agents/reviewer.md`, `scripts/resolve-persona.py` (role registry), tests

**Deps:** T006

**Description:** Add a small role registry (Python dict in `resolve-persona.py` or a separate JSON) mapping role → `expected_contract`. Three entries: `consultant_primary: freeform`, `consultant_secondary: freeform`, `reviewer: review-verdict`. Update each `agents/<role>.md` documentation to mention `expected_contract`. `validate` subcommand hard-fails when a bound persona's `contract` disagrees with the role's `expected_contract`.

**Acceptance:**
- [ ] Role registry contains the three entries.
- [ ] `validate` fails (non-zero exit, actionable message) if `personas/builtin/codex-default-reviewer.md` had `contract: freeform` (artificial test).
- [ ] When persona omits `contract`, treat as "any" (passes validation against any role).
- [ ] Agent docs updated.

**DOCS:** agents
**Complexity:** high

---

## T010 — Dispatcher.run override kwargs [x]

**Files:** `runtime/dispatch/dispatcher.py`, `runtime/tests/test_dispatch.py`

**Deps:** T007

**Description:** Extend `Dispatcher.run()` signature to accept `persona=None, model=None, runtime=None` kwargs. When called, run resolution order: explicit kwargs → resolve-persona output → error. Emit `persona_bound` with the resolved triple + source per axis. Emit `model_resolved` with the model source. Existing callers unchanged (kwargs default to None).

**Acceptance:**
- [ ] All existing `Dispatcher.run()` callers compile and run unchanged.
- [ ] Passing `persona="X"` overrides whatever TOML says; emit `persona_override_used`.
- [ ] Passing `model="opus"` overrides; emit `persona_override_used`.
- [ ] `persona_bound` event payload reflects the actual resolved triple after all overrides.

**DOCS:** none
**Complexity:** medium

---

## T011 — `/z-personas` slash command + skill [x]

**Files:** `commands/z-personas.md` (new), `skills/z-personas/SKILL.md` (new)

**Deps:** T007

**Description:** Slash command + skill mirror; surface `list`, `roles`, `validate`, `read <name>`, `where <name>`. Default (no args) = `roles`. Output formatted for human reading: tabular for `roles`, JSON-or-pretty for the rest. Command name normalization is reversed on output (prints `/z-plan`, not `z_plan`).

**Acceptance:**
- [ ] `/z-personas` (no args) prints a table of `[command | role | persona | model | runtime]`.
- [ ] `/z-personas list` prints persona names by layer.
- [ ] `/z-personas validate` exits non-zero on invalid state; prints diagnostics.
- [ ] `/z-personas read codex-default-reviewer` prints frontmatter + body.
- [ ] `/z-personas where codex-default-reviewer` prints all defining layers in load order.

**DOCS:** commands, skills
**Complexity:** low

---

## T012 — CI grep gate [x]

**Files:** `scripts/ci-grep-gates.sh` (new), CI workflow (`.github/workflows/*.yml` or equivalent)

**Deps:** T005

**Description:** Shell script that scans `commands/`, `skills/`, `scripts/`, `agents/`, `runtime/` for the pattern `\b(codex|gemini|claude)\b` not followed by `-cli` or other allowed suffixes. Exempt paths: `docs/llm/*.json`, `z-harness/*/archive/`, the `aliases` mapping in `providers.json` itself. Exit non-zero with a per-match report on hit. Wire into existing CI.

**Acceptance:**
- [ ] Script runs locally: `bash scripts/ci-grep-gates.sh` exits 0 on a clean repo, non-zero with an offending grep added.
- [ ] Allowlist exempts the four-config-file `aliases` mapping.
- [ ] CI workflow file updated to call the gate.

**DOCS:** scripts
**Complexity:** medium

---

## T013 — Multi-IDE persona export module [x]

**Files:** `runtime/drivers/antigravity/persona_export.py` (new), `runtime/drivers/cursor/persona_export.py` (new), `runtime/drivers/codex/persona_export.py` (new), `runtime/drivers/claude/persona_export.py` (new), tests

**Deps:** T006

**Description:** Per-target persona export module under each existing driver dir. Each module exposes `export_persona(persona_file_path, target_export_root) -> Path`. Output paths per SPEC §G1: agy gets `.agent/personas/<name>.md` (native), cursor gets `.cursor/personas/<name>.mdc`, codex gets `prompts/personas/<name>.md`, claude (subagent target) gets `personas/<name>.md` flat. Each adapter writes a "persona export portability" header that documents whether the target consumes it natively (agy: yes; cursor/codex: no, falls back to system-prompt context injection).

**Acceptance:**
- [ ] Each driver's `persona_export.py` produces the expected output path with frontmatter+body preserved.
- [ ] The four output paths exist after running for each target.
- [ ] Unit tests round-trip a sample persona file through each adapter.

**DOCS:** multi-ide-exports
**Complexity:** medium

---

## T014 — `/z-export --include=personas` wiring + audit-tarball allowlist [x]

**Files:** `commands/z-export.md`, `scripts/export-{cursor,codex,agy}.py` (no changes — deprecated; just verify `--include=personas` flag is honored via the new modules), `scripts/audit-tarball.sh`

**Deps:** T013

**Description:** Update `/z-export` to invoke the per-target `persona_export.py` modules during export. The deprecated per-target Python scripts are NOT extended; instead, `/z-export` is updated to call the new modules directly. Update `scripts/audit-tarball.sh` allowlist to permit `personas/` in tarballs.

**Acceptance:**
- [ ] `/z-export --target=all` produces persona files under each target's export root.
- [ ] `bash scripts/audit-tarball.sh dist/z-harness-*.tar.gz` passes when the tarball contains `personas/` and the expected per-target persona directories.
- [ ] No edits to `scripts/export-{cursor,codex,agy}.py` (they remain deprecated/frozen).

**DOCS:** multi-ide-exports
**Complexity:** low

---

## T015 — Telemetry collision check + global event grep [x]

> Done via spec-precheck mechanical grep — zero external collisions across 8 new event names. No code change. (SUMMARY: archive/tasks/T015/SUMMARY.md)

**Files:** verification only — no edits

**Deps:** none (mechanical check before merge)

**Description:** Before merging, run a mechanical grep across the repo to confirm none of the seven new event names already exist anywhere as `log-event.sh` first arguments. Document the result inline in the merge commit.

**Acceptance:**
- [ ] `grep -rE 'log-event\.sh.*\"(persona_(bound\|override_used\|compat_warning\|shadowed\|binding_chimera)\|provider_alias_used\|legacy_provider_roles_used\|model_resolved)\"' --include="*.md" --include="*.sh" --include="*.py" -l` returns nothing outside the personas-and-roles plan files.
- [ ] No new event name collides with existing.

**DOCS:** none
**Complexity:** low

---

## T016 — `docs/human/PERSONAS.md` + `docs/human/PROVIDERS.md` restructure [x]

**Files:** `docs/human/PERSONAS.md` (new), `docs/human/PROVIDERS.md` (rewrite)

**Deps:** T006, T008, T010, T011

**Description:** Author `PERSONAS.md` covering persona file format, layered storage, TOML binding, override kwargs, `/z-personas` command, examples. Restructure `PROVIDERS.md` to focus on the runtime registry only (CLI binding, args_template, model_arg_template, aliases); cross-link to PERSONAS.md for the role-binding story.

**Acceptance:**
- [ ] `PERSONAS.md` includes: file format, layered storage with precedence, TOML binding example, override kwargs example, `/z-personas` reference, troubleshooting (`persona_binding_chimera` interpretation, `persona_shadowed` debug).
- [ ] `PROVIDERS.md` no longer claims `roles` mapping is canonical — explains that `[roles.*]` TOML is preferred, `providers.json.roles` is legacy fallback.
- [ ] Cross-links between the two docs.

**DOCS:** providers-registry, personas-and-roles
**Complexity:** low

---

## T017 — `docs/llm/personas-and-roles.json` + INDEX update [x]

**Files:** `docs/llm/personas-and-roles.json` (new), `docs/llm/INDEX.json`, `docs/llm/providers-registry.json` (update)

**Deps:** T016

**Description:** New LLM-tier concept `personas-and-roles` covering the persona feature surface. Update `providers-registry.json` to mark itself as the runtime-only concept and link to `personas-and-roles`. Add `personas-and-roles` to INDEX.json with `source_files` covering the new files. Bump both concepts' `last_updated`.

**Acceptance:**
- [ ] `personas-and-roles.json` validates against the existing concept schema.
- [ ] `INDEX.json` lists the new concept with correct `source_files`.
- [ ] `providers-registry.json` linked from `personas-and-roles.json` via `depends_on` or `consumed_by`.

**DOCS:** personas-and-roles, providers-registry
**Complexity:** medium

---

## Task-count check

17 tasks. Within 10-20 target. No need to split or restructure.

## Phase dependency notes

- T001 unblocks T002, T006, T007.
- T003 unblocks T004, T005.
- T006 unblocks T007, T008, T009, T013.
- T007 unblocks T010, T011.
- T013 unblocks T014.
- T015 is a pre-merge mechanical check (can run any time).
- T016, T017 close the loop after the code lands.

Parallelizable batches: {T001, T003} → {T002, T004, T005, T006} → {T007, T008, T009, T013} → {T010, T011, T012, T014} → {T015, T016, T017}.

---

# Fixup tasks (post-/z-review-all)

Opened in response to final review findings. See archive/20260528T224612Z-review/findings.md.

## T100 — providers.json v2 upgrade with aliases (fixes A1 blocker) [x]

**Files:** `.z-harness/providers.json` (or wherever the shipped providers config lives), `runtime/tests/test_compat_providers.py`

**Description:** Update the shipped `providers.json` from version 1 to version 2. KEEP existing `codex` / `gemini` / `claude` entries unchanged (for back-compat with users who haven't migrated). ADD new entries `codex-cli` / `gemini-cli` / `claude-cli` with identical `command` / `args_template` / `timeout_s`. ADD top-level `aliases` map `{"codex": "codex-cli", "gemini": "gemini-cli", "claude": "claude-cli"}`. Verify on fresh install: `cmd_ensure_defaults` writes config with `runtime = "codex-cli"` and resolve-provider succeeds.

**Acceptance:**
- [ ] `providers.json` has `version: 2`
- [ ] Both old and new provider entries exist
- [ ] Aliases map populated
- [ ] Integration test: ensure-defaults → resolve-persona resolve consultant_primary → resolve-provider (resolved runtime "codex-cli") returns valid provider record

**Complexity:** low

---

## T101 — Dispatcher.run wires effective_model into build_env (fixes A2 blocker) [x]

**Files:** `runtime/dispatch/dispatcher.py`, `runtime/tests/test_dispatch.py`

**Description:** After resolving `effective_model` in Dispatcher.run, pass it to build_env: `env = build_env(provider_config, base_env=None, effective_model=_resolved_model)`. Verify model_env_var feature works end-to-end via dispatcher.

**Acceptance:**
- [ ] build_env called with effective_model
- [ ] Test: dispatch with provider configured for model_env_var → subprocess env contains the expected variable
- [ ] Existing test_dispatch tests still pass

**Complexity:** low

---

## T102 — Persona body prepend integration (fixes A3 major) [x]

**Files:** `runtime/dispatch/dispatcher.py` (extend) OR new helper in `runtime/dispatch/persona_prompt.py`, `runtime/tests/test_dispatch.py`, `docs/human/PERSONAS.md` (update example)

**Description:** Implement the persona-body-prepend step per SPEC §D's resolution-ownership clarification. Orchestrator pattern: read `persona_body_path` from resolve-persona output, read the file, prepend to the role's task prompt. Either (a) document the pattern in PERSONAS.md + provide a helper, OR (b) thread it into Dispatcher.run via a `task_prompt=` kwarg that the dispatcher prepends to. Pick (a) — keep dispatcher thin.

**Acceptance:**
- [ ] Helper function `runtime/dispatch/persona_prompt.py:prepend_persona(body_path, task_prompt) -> str` exists
- [ ] PERSONAS.md documents the orchestrator pattern (read body_path → prepend → dispatch)
- [ ] Test: prepend_persona returns body + "\n\n" + task_prompt; empty body_path returns task_prompt unchanged

**Complexity:** low

---

## T103 — persona_bound payload align with SPEC (fixes A4 major) [x]

**Files:** `runtime/dispatch/dispatcher.py`, `runtime/tests/test_dispatch.py`, SPEC.md §H

**Description:** persona_bound event currently emits `{command_id, persona, model, runtime, source: {persona: layer, model: layer, runtime: layer}}`. SPEC §H lists `{command, role, persona, model, runtime, source}`. Reconcile: either (a) update SPEC to document per-axis nested source (recommended — implementation shape is more useful), OR (b) flatten source to a single string. Also: add `role` to the event payload (Dispatcher.run gains optional `role=` kwarg from caller).

**Acceptance:**
- [ ] SPEC §H updated to match emitted payload OR payload updated to match spec — pick one
- [ ] `role` field present in payload
- [ ] test_dispatch covers the final shape

**Complexity:** low

---

## T104 — Run /z-maintain-docs after fixup [x]

**Description:** Once T100-T103 are done, regenerate docs/llm/personas-and-roles.json + docs/human/PERSONAS.md to reflect the fixed-up implementation. Run `/z-maintain-docs --apply --scope personas-and-roles` (or scope by concept).

**Acceptance:**
- [ ] docs/llm/personas-and-roles.json has updated entry_points reflecting prepend_persona helper
- [ ] docs/human/PERSONAS.md documents the orchestrator persona-body-prepend pattern
- [ ] INDEX.json bumped

**Complexity:** low
