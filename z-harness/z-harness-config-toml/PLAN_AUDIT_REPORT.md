# Plan Audit Report — z-harness-config-toml

- **Date (UTC):** 2026-05-27T17:56Z
- **Slug:** z-harness-config-toml
- **Run ID:** 20260527T175653Z-z-harness-config-toml-audit-plan
- **Sources:** Phase 1 reality check + Phase 2 design audit + adversarial Codex + adversarial Gemini

## Summary

Two BLOCKERS the prior Phase 7 review missed; seven MAJORS worth amending the plan for; six MINORS for note-only. Most material: (a) `$Z_HARNESS_RUN` is never exported so `config_resolved` events would never fire as currently specified; (b) `docs.always_apply = "auto"` (default) silently demotes /z-do's current behavior because /z-do today **unconditionally** dispatches doc-fetcher (there is no heuristic to "preserve").

Recommend `/z-amend` before implementation. Most amendments are small and surgical.

---

## reality-check Reality Check findings

### F1 (BLOCKER): tri-state default silently demotes /z-do
SPEC §"File 8" claims default `"auto"` preserves /z-do's "current heuristic." [commands/z-do.md:71-83](commands/z-do.md:71) and [skills/z-do/SKILL.md:72](skills/z-do/SKILL.md:72) show /z-do **unconditionally** dispatches doc-fetcher. No heuristic exists.

**Pushback considered:** "Maybe 'auto' could be defined as 'dispatch unconditionally for now'." — Then `"auto"` and `"always"` are aliases in slice 1, which is exactly the over-engineering the tri-state was supposed to avoid.

**Recommendation:** Drop the tri-state. Use binary `"always" | "never"` with default `"always"`. KISS; matches reality.

### F2 (MAJOR): Z_HARNESS_NOTIFY prose lingers in 16 non-migrated commands
Cosmetic (no script reads it) but creates user-facing inconsistency post-slice-1.

**Pushback considered:** "Slice 2 will migrate them anyway." — True, but slice 2 isn't sequenced; cosmetic inconsistency persists for an unbounded window.

**Recommendation:** Add T009 — mechanical prose pass (~30 min) updating Z_HARNESS_NOTIFY mentions in non-migrated commands to "see docs/human/config.md" pointer.

---

## design-check Design & Style findings

### F5 (MINOR, deferred to slice 2): doc duplication footgun at 3rd knob
Two-knob schema info appears in `DEFAULTS`, `VALIDATORS`, `docs/human/config.md`, `docs/llm/config-design.json`. Fine at 2; drift-prone at 6+.

**Recommendation:** Add note to PLAN.md non-goals/slice-2: "auto-generate `docs/human/config.md` knobs table from `DEFAULTS`/`VALIDATORS` before adding the 3rd knob."

### F7 (NIT): python-startup latency per command
4× `should-notify` × 50ms = ~200ms. Acceptable; note for future.

---

## adversarial Adversarial Consult findings

### F-BLOCKER-1 (Codex): `$Z_HARNESS_RUN` never exported
SPEC says `config_resolved` event emits "iff `$Z_HARNESS_RUN` is set." Skills set `RUN=$(date -u ...)` but never `export RUN`; subprocesses (incl. `config.py`) won't see it.

**Pushback considered:** "log-event.sh receives RUN as positional arg, so maybe config.py can too." — Yes, but SPEC currently reads from env. Either route works; SPEC must declare.

**Recommendation:** Choose one path. Prefer: every migrated command's setup adds `export Z_HARNESS_RUN="$RUN"` before the `config.py export-env` line. SPEC and TASKS T002/T006/T007 updated to make this explicit.

### F-MAJOR-3 (Codex): `schema_version` in DEFAULTS but it's not a knob
`export-env` would try to emit `Z_HARNESS_SCHEMA_VERSION` and break the "user-knob" mental model.

**Recommendation:** Add `META_KEYS = {"schema_version"}` to `config.py`. `export-env`, `get`, `explain` skip meta keys (or treat them as advanced).

### F-MAJOR-4 (Codex): `/z-update` claimed to call `ensure-defaults` but no task modifies it
SPEC §"Edge cases" says "/z-update calls ensure-defaults"; TASKS doesn't touch /z-update.

**Recommendation:** Drop the /z-update claim from SPEC. Replace with: "Users invoke `bash scripts/config.sh ensure-defaults` manually, or it's called by `/z-init-docs` on first repo init. Documented in install section of README."

### F-MAJOR-5 + F15: T001 README link to docs/human/config.md is broken until T003 lands
T001 ships as PR1, T003 in PR2; the README link points to a not-yet-existing file.

**Recommendation:** Merge T001 into the same PR as T002–T005 (PR2 becomes "loader + docs + slim README"). Drop the "T001 ships alone" sequencing. The slim README is no longer "trivially reversible before config work" because it depends on `docs/human/config.md` existing. Original sequencing was wrong.

### F-MAJOR-6 (Codex): "whichever holds dispatch logic" — both files exist and can diverge
For most z-* commands, `commands/X.md` AND `skills/X/SKILL.md` both exist with overlapping content.

**Recommendation:** T006/T007 acceptance must say: "Update BOTH `commands/<cmd>.md` AND `skills/<cmd>/SKILL.md` if both contain the matching code paths. If they currently diverge, flag and stop before migration."

### F-MAJOR-7 (Codex): T005 smoke coverage is thin
Missing tests for: repo precedence, explicit-missing `$Z_HARNESS_REPO_CONFIG`, invalid-enum global fallback path, schema-version mismatch, TOML parse error, event de-dup, full `should-notify` truth table (Gemini F16: 9 branches).

**Recommendation:** Expand T005 acceptance matrix per the full SPEC §"Exit code truth table" + SPEC §"Layered validation rules" + the full should-notify truth table.

### F-MAJOR-8 (Codex): T008 corrupts dev's real `~/.config/z-harness/config.toml`
Manual e2e tests need isolation.

**Recommendation:** T008 acceptance prefaces every test with `XDG_CONFIG_HOME=$(mktemp -d)` and a `trap 'rm -rf $XDG_CONFIG_HOME' EXIT`.

### F-MAJOR-9 + F9 (Codex + Gemini): pre-flight + SPEC contradiction
- Pre-flight: T006/T007 should verify `PushNotification` and (for T006) doc-fetcher dispatch patterns exist in target files BEFORE starting.
- SPEC contradiction: ensure no stale "invalid enum → exit 2" text remains that contradicts the layered policy (warn+fallback for global, exit 2 for repo/env).

**Recommendation:** Both. Pre-flight check added to T006/T007. SPEC text re-read for residual contradictions.

### F10 (Gemini): subagent re-emit race
**Pushback considered:** Subagents typically don't re-invoke `config.py export-env`; they read env they inherited. The race is academic.

**Recommendation:** DEMOTE to NIT. Add one SPEC sentence: "Subagents must not re-invoke `config.py export-env`; they inherit env from parent."

### F11 (Gemini): git worktree edge case
**Pushback:** `git rev-parse --show-toplevel` handles worktrees correctly. Not actually a bug.

**Recommendation:** DROP. No action needed.

### F12 (Gemini): `_dotted_to_env` key format
**Recommendation:** Add regex validation `^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$` in `_dotted_to_env`; exit 2 on mismatch.

### F13 (Gemini): T008 doesn't assert `config_resolved` payload accuracy
**Recommendation:** T008 adds: "Run /z-do with repo-local override; parse events.jsonl for `config_resolved`; assert `sources["notify.level"] == "repo"`."

### F14 (Gemini): env-vs-repo precedence not tested
**Recommendation:** T008 adds: "With both `.z-harness/config.toml` (notify.level=approval_only) AND `Z_HARNESS_NOTIFY_LEVEL=all` set, run `config.py explain notify.level`; assert source=env, value=all."

### F-MINOR-10 (Codex): `$Z_HARNESS_RUN` in temp-file path
**Pushback:** RUN is harness-generated (timestamp + slug). No user input. Risk is theoretical.

**Recommendation:** DROP. No action.

### F-MINOR-2 (Codex): `$PLUGIN_ROOT` inconsistency in SPEC prose
SPEC uses `$PLUGIN_ROOT` shorthand in some examples; actual commands use `${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}`.

**Recommendation:** Find/replace in SPEC examples. Trivial.

### F8 (Gemini): export-env empty value idempotency
**Pushback:** No slice-1 knob has an empty default; the case is hypothetical.

**Recommendation:** DEMOTE to MINOR. Add: "Empty TOML string value rejected at validation time."

---

## Consensus vs Disagreement

**Consensus (flagged by multiple layers):**
- F1 tri-state demotion (reality-check + design): drop tri-state.
- F-MAJOR-5 + F15 README link sequencing (Codex + Gemini).
- F-MAJOR-7 + F16 thin test coverage (Codex + Gemini).
- F-MAJOR-9 + F9 pre-flight verification (Codex + Gemini).

**Outliers (single-source, worth scrutiny):**
- F10 subagent race (Gemini only) — DEMOTED.
- F11 worktree (Gemini only) — DROPPED.
- F-MINOR-10 RUN sanitization (Codex only) — DROPPED.

---

## Actionable Recommendations (for `/z-amend`)

### Must amend before implementation (blockers + majors)

1. **Drop tri-state**: SPEC, PLAN — change `docs.always_apply` to binary `"always" | "never"`, default `"always"`. Remove "auto" entirely.
2. **Export `Z_HARNESS_RUN`**: SPEC and T006/T007 setup snippets prepend `export Z_HARNESS_RUN="$RUN"` before the config.py eval. Or change config.py to accept `--run` flag.
3. **META_KEYS exclusion**: SPEC §"export-env" — declare `schema_version` is meta-only; `export-env`, `get`, `explain` skip meta keys.
4. **Drop /z-update claim**: SPEC §"Edge cases" — replace "modified to invoke `ensure-defaults`" with manual invocation guidance in README install section.
5. **Re-sequence PRs**: TASKS — merge T001 into the same PR as T002–T005. Final PR shape: PR1 = T001+T002+T003+T004+T005 (everything except command migration + e2e); PR2 = T006+T007+T008+T009.
6. **Add T009**: mechanical prose pass updating Z_HARNESS_NOTIFY refs in non-migrated commands (~30 min, low risk).
7. **Clarify T006/T007**: require updating BOTH `commands/<cmd>.md` AND `skills/<cmd>/SKILL.md`. Pre-flight: verify expected patterns exist before migration.
8. **Expand T005 test matrix**: full exit-code truth table + full should-notify 9-branch matrix + de-dup + parse-error + schema-mismatch.
9. **Isolate T008**: `XDG_CONFIG_HOME=$(mktemp -d)` with cleanup trap; assert event payload `sources` accuracy; test env-shadows-repo precedence.

### Minor cleanup (do in /z-amend or defer to implementer)

10. Find/replace `$PLUGIN_ROOT` shorthand in SPEC examples → `${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}`.
11. Add regex key-format validation in `_dotted_to_env`.
12. Add one SPEC sentence: "Subagents must not re-invoke `config.py export-env`."
13. Note: empty TOML string values rejected at validation time.
14. Re-read SPEC for residual contradictions on enum-invalid policy (global vs repo/env).
15. Slice-2 note: auto-generate docs/human/config.md knobs table before 3rd knob.

---

## Status

Audit complete. 2 BLOCKERS, 7 MAJORS, 6 MINORS post-pushback.
Recommended next action: `/z-amend` with the 9 must-amend items.
