# Final review — portable-harness
Run: 20260524T174504Z-review
Base ref: HEAD (338e138; all changes uncommitted)
Diff stats: 63 files tracked-modified · ~241 untracked (focused diff = 10709 lines of source + new files)
Consultants: Gemini (consultant-primary) + Codex (consultant-secondary)

## Triage note on Codex findings

Codex returned **9 blockers + 18 majors claiming most new files are "missing"** — `agents/consultant-primary.md`, `agents/reviewer.md`, `scripts/export-cursor.py`, `install.sh`, etc. These claims are **false**: all listed files exist on disk (verified). Codex was confused by the focused-diff format (untracked files were embedded as `--- BEGIN NEW FILE ---` stanzas, not git diff hunks). All 9 Codex "missing-file blockers" and most of its "missing-file majors" are **rejected** as premise-error.

The remaining Codex findings (Prong-B design gaps) below are kept where independently verifiable.

## Prong A — Implementation drift

### Blocker
- **`scripts/log-providers.sh` is dead code.** [Gemini] Verified: no `commands/*.md`, `agents/*.md`, or `skills/**/SKILL.md` calls `scripts/log-providers.sh`. SPEC §T005 acceptance requires "Run-start observability: a separate `scripts/log-providers.sh` invoked from each consultant/reviewer dispatch site" — implementation creates the script but no dispatch site invokes it.
  - One reason this might be wrong: maybe the spec intends the agent files themselves (not their callers) to invoke it. But the spec wording ("each consultant/reviewer dispatch site") points to the orchestrator, and no agent body calls it either. Finding stands.

### Major
- **Generated export trees not committed.** [Gemini] `exports/cursor/.cursor/rules/*.mdc`, `exports/codex/prompts/*.md`, `exports/agy/.agent/**` exist in working tree but are untracked. SPEC §T010 explicitly says "commit the generated tree so users can `git clone` and use." User needs to `git add` them.
- **No tests for provider resolver.** [Gemini] SPEC §T005 calls for "Tests against fixture providers.json"; no `tests/` or `scripts/test_resolve_provider.py` was produced.

### Minor
- **Transcript filenames use `$MODE` instead of `<topic>`.** [Gemini] Cosmetic; doesn't break correctness.
- **In-flight plans still reference legacy agent names.** [T008 sweep summary] `z-harness/mr-style-reviewer/TASKS.md`, `z-harness/brainstorm-and-research/TASKS.md`, `z-harness/z-fix-hypothesis-driven/TASKS.md` still mention `gemini-consultant`/`codex-consultant`. Not auto-edited per spec; user nudge already printed.

## Prong B — Spec gaps

### Blocker
- **`timeout` is not on default macOS PATH.** [Gemini] All three new agents (`consultant-primary.md`, `consultant-secondary.md`, `reviewer.md`) wrap CLI calls in `timeout "$TIMEOUT" $COMMAND $ARGS`. macOS does not ship `timeout(1)` natively; users without `coreutils` (brew) will see `timeout: command not found`. Spec/agents should fall back to `gtimeout` then to no-timeout-wrapper with a one-time warning.
  - One reason this might be wrong: most macOS dev users already have coreutils via Homebrew. Still — a portable harness must not assume this.

- **`scripts/bundle-plugin.sh` exclusion list leaks legacy plan dirs.** [Gemini] Exclusions cover `./z-harness/plans`, `./z-harness/archive`, `./z-harness/improvements`, `./.z-harness`, and `*/providers.json`. They do **not** cover bare `./z-harness/<slug>/` legacy dirs (e.g. `z-harness/portable-harness/`, `z-harness/mr-style-reviewer/`, …). On an unmigrated repo, a `bundle-plugin.sh` invocation would ship the maintainer's private plan content (SPEC.md, TASKS.md, archive transcripts) in the public tarball.
  - One reason this might be wrong: `audit-tarball.sh` would catch the leak post-bundle. Verified the audit fail list: it includes `z-harness/plans/`, `z-harness/archive/`, `z-harness/improvements/`, but NOT bare `z-harness/<slug>/`. So no, the audit doesn't catch it either. Real blocker for any pre-migration release.

### Major
- **`Z_HARNESS_LEGACY_WARNED` env-guard inside `$()` subshell.** [Gemini] `resolve_plan_path` is called as `BASE="$(resolve_plan_path "$slug")"`. The `export Z_HARNESS_LEGACY_WARNED=1` runs inside the subshell, so the variable dies on return. Result: warning fires on every path resolution, not "once per run" as spec requires.
  - One reason this might be wrong: maybe `Z_HARNESS_LEGACY_WARNED` is meant to be exported by the caller before invoking commands. Reading T003 task: "warn ONCE per run (env-guard `Z_HARNESS_LEGACY_WARNED=1`)" — implies the guard should self-set. The subshell pattern defeats it. Real bug; fix needs the warning to write a stamp file or use a different IPC.

- **Provider invocation contract underspecified.** [Codex Prong-B blocker, verified worth keeping as major] Agents do `$COMMAND $ARGS` (unquoted) on the joined argv. Args with spaces, shell metacharacters, or required quoting will break. The spec's `args_template: ["exec", "-"]` shape works for current providers but offers no escape hatch for CLIs that need quoted args or placeholder substitution.

- **No schema validation of `args_template` shape.** [Codex] `resolve-provider.py` validates `version == 1` and primary≠secondary but doesn't typecheck `args_template` (must be `list[str]`), `stdin` (must be bool), `timeout_s` (must be int). Malformed entries pass through and explode in agent bash.

- **`provider_shadowed` de-dup is per-process only.** [Codex] Env-guard inside a single Python invocation doesn't persist across the three role resolutions (consultant_primary, consultant_secondary, reviewer) when each is its own `resolve-provider.sh` call. Same root cause as the `LEGACY_WARNED` issue above.

### Minor
- **`$XDG_CONFIG_HOME` not respected.** [Gemini] Spec hardcodes `~/.config/z-harness/providers.json`. POSIX/XDG convention says fall back to `$XDG_CONFIG_HOME` if set. Easy fix.
- **Smoke-test gate is not automatable.** [Gemini] SPEC §T010-T012 acceptance says "automated check: every emitted .mdc parses (basic MDC syntax)" — implementer did this. But the spec also gestures at "manual IDE sign-off" in non-goals; current PLAN treats this as out-of-scope, which is fine.

## Consensus vs disagreement

**Both LLMs flagged (high confidence):**
- (None — Codex's findings were largely premise-error; the only overlap with Gemini is "spec is underspecified somewhere", which both raised in different forms.)

**Gemini-only (worth manual scrutiny):**
- log-providers.sh dead code (✓ verified)
- macOS `timeout` portability (✓ verified)
- bundle-plugin.sh legacy-plan-leak (✓ verified)
- Z_HARNESS_LEGACY_WARNED subshell trap (✓ verified)
- Uncommitted generated exports (✓ verified)

**Codex-only (Prong-B design issues, post-triage):**
- Provider invocation contract underspecified
- Schema validation gap for `args_template`/`stdin`/`timeout_s` types
- `provider_shadowed` de-dup is per-process only

---

## Recommended action items

**Must-fix (blocker):**
1. Wire `log-providers.sh` into orchestrator commands (z-plan, z-debug, z-implement-all, z-review-all, z-mr-review at minimum) — single line near run start.
2. Add `timeout` fallback in all three agent bodies: `TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || echo "")"`; if empty, skip the wrapper with a one-time stderr warning.
3. Extend `bundle-plugin.sh` exclusion list to skip bare `./z-harness/<slug>/` legacy plan dirs (regex or post-migration enforcement); extend `audit-tarball.sh` to fail on `z-harness/<slug>/SPEC.md|PLAN.md|TASKS.md` entries.

**Should-fix (major):**
4. Replace `Z_HARNESS_LEGACY_WARNED` env-guard with a stamp file under `/tmp/z-harness-<pid>` (or a stamp inside `$BASE`) to survive across subshells. Same fix applies to `provider_shadowed` de-dup.
5. Add `args_template`/`stdin`/`timeout_s` type validation in `resolve-provider.py`.
6. Generate + commit the export trees (`scripts/export-{cursor,codex,agy}.py`), then `git add exports/`.
7. Add minimal pytest fixtures for `resolve-provider.py` (one happy path, one shadowing, one invariant violation).

**Nice-to-have (minor):**
8. Honor `$XDG_CONFIG_HOME` in `resolve-provider.py` config loading.
9. Update README.md + docs/human/{agents,mr-reviewer,style-init}.md to drop residual references to legacy agent names.
