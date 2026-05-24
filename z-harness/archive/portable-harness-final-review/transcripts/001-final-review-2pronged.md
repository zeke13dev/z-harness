# Final Review: Portable-Harness Refactor (2-Pronged)

## Consultation Context
- Mode: final-review-2pronged
- SPEC: z-harness/portable-harness/SPEC.md (15 tasks, 24+ deliverables)
- PLAN: z-harness/portable-harness/PLAN.md (ordered phases, dependencies)
- TASKS: z-harness/portable-harness/TASKS.md (all marked [x])
- Implementation: z-harness/portable-harness/archive/20260524T174504Z-review/cumulative.diff (63 files, 2433 insertions/1032 deletions)

## Prong A — Drift (Files missing from implementation)

### Blocker (9 files)
- File: `agents/consultant-primary.md` — Reason: SPEC §Consultant + reviewer agents — generalized dispatch replaces `gemini-consultant`; without this canonical agent, all `subagent_type="consultant-primary"` call sites fail.
- File: `agents/consultant-secondary.md` — Reason: SPEC §Consultant + reviewer agents — generalized dispatch replaces `codex-consultant`; without this canonical agent, all `subagent_type="consultant-secondary"` call sites fail.
- File: `agents/reviewer.md` — Reason: SPEC §Consultant + reviewer agents — `codex-reviewer` was deleted and dispatch sites now route to `reviewer`; without it, implementation/review gates fail.
- File: `commands/z-providers-discover.md` — Reason: SPEC §Provider discovery requires a slash command to create/bind `providers.json`; without it, the new provider system has no supported setup path.
- File: `scripts/export-cursor.py` — Reason: SPEC §Multi-IDE export requires a Cursor adapter; `/z-export --target=cursor` cannot work without it.
- File: `scripts/export-codex.py` — Reason: SPEC §Multi-IDE export requires a Codex adapter; `/z-export --target=codex` cannot work without it.
- File: `scripts/export-agy.py` — Reason: SPEC §Multi-IDE export requires an Antigravity adapter; `/z-export --target=agy` cannot work without it.
- File: `scripts/bundle-plugin.sh` — Reason: SPEC §Install/update requires a tarball bundler; `/z-update` and portable install flows cannot produce or verify release artifacts without it.
- File: `install.sh` — Reason: SPEC §Install requires a root installer; tarball/symlink installation is not user-accessible without it.

### Major (18 files)
- File: `commands/z-export.md` — Reason: SPEC §Multi-IDE export calls `/z-export`; without the slash command, export scripts are not exposed through the harness UX.
- File: `commands/z-update.md` — Reason: SPEC §Install/update calls `/z-update`; without it, installed harnesses cannot self-update through the documented path.
- File: `exports/cursor/CAPABILITIES.md` — Reason: SPEC §Cursor export requires target capabilities documentation; missing file leaves unsupported subagent/skill behavior undocumented.
- File: `exports/cursor/README.md` — Reason: SPEC §Cursor export requires install/use documentation for generated Cursor rules.
- File: `exports/cursor/.cursor/rules/*.mdc` — Reason: SPEC §Cursor export requires generated `.mdc` files; absent or stale generated rules mean the Cursor export is not actually usable.
- File: `exports/codex/CAPABILITIES.md` — Reason: SPEC §Codex export requires capability/limitation documentation.
- File: `exports/codex/AGENTS.md` — Reason: SPEC §Codex export requires consolidated agent documentation because Codex CLI has no native subagent dispatch.
- File: `exports/codex/README.md` — Reason: SPEC §Codex export requires install/use documentation.
- File: `exports/codex/prompts/*.md` — Reason: SPEC §Codex export requires generated prompt files; without them, the Codex target is only described, not exported.
- File: `exports/agy/CAPABILITIES.md` — Reason: SPEC §Antigravity export requires capability/limitation documentation.
- File: `exports/agy/agy-plugin.yaml` — Reason: SPEC §Antigravity export requires an export manifest.
- File: `exports/agy/README.md` — Reason: SPEC §Antigravity export requires install/use documentation.
- File: `exports/agy/prompts/*.md` — Reason: SPEC §Antigravity export requires generated prompts; without them, the target is incomplete.
- File: `docs/human/PROVIDERS.md` — Reason: SPEC §Provider docs requires human documentation for schema, precedence, discovery, and troubleshooting.
- File: `docs/human/INSTALL.md` — Reason: SPEC §Install docs requires human documentation for install/update modes.
- File: `docs/human/MULTI-IDE.md` — Reason: SPEC §Multi-IDE docs requires human documentation for Cursor/Codex/Antigravity exports.

### Minor (4 files)
- File: `exports/cursor/.cursor/rules/reviewer.mdc` — Reason: Cursor generated output must reflect new canonical agents; current generated content appears stale if it still includes deleted `codex-reviewer.mdc` but lacks `reviewer.mdc`.
- File: `exports/cursor/.cursor/rules/codex-consultant.mdc` — Reason: Deleted source agent should not remain in generated Cursor output.
- File: `exports/cursor/.cursor/rules/gemini-consultant.mdc` — Reason: Deleted source agent should not remain in generated Cursor output.
- File: `exports/cursor/.cursor/rules/codex-reviewer.mdc` — Reason: Deleted source agent should not remain in generated Cursor output.

## Prong B — Spec gaps (Design issues surfaced by actual implementation)

### Blocker (2 issues)
- **Provider invocation contract underspecified.** The agent design joins JSON array `args_template` elements into one shell string and executes `$COMMAND $ARGS`, losing argument quoting; cannot safely represent args with spaces, shell metacharacters, or placeholders like `{prompt}` or `@-`. One concrete reason: CLIs like Gemini with `-p "<prompt>"` syntax don't map to stdin piping, and the spec provides no mechanism to override the default argv+stdin model.
- **Provider stdin semantics don't match real CLI needs.** The design only supports "pipe prompt to stdin" or "append prompt as final argv"; it does not define placeholder substitution, temp-file prompts, or alternative invocation patterns. One concrete reason: if `reviewer` resolves successfully but the configured CLI's args_template cannot be invoked using the simplistic argv/stdin model, all review gates fail after provider resolution succeeds, with no fallback.

### Major (7 issues)
- **Schema validation gap in resolver.** `scripts/resolve-provider.py` does not validate `kind`, required field types, or `args_template` shape. One concrete reason: a malformed `args_template` (e.g., not an array, or containing non-string elements) will pass resolution and fail later inside agent shell snippets, delaying detection.
- **Shadow warning de-dup is process-local only.** The spec says "warn once per run," but the implementation uses `os.environ` inside a single Python invocation, which does not persist across separate `resolve-provider.sh` calls. One concrete reason: if a command spawns multiple subagent roles, each role's resolver invocation is a separate process, so the "already warned" flag is lost.
- **Log-providers.sh observability hook is not enforced.** The spec says every command that dispatches a consultant/reviewer logs provider resolution at start-up, but the diff shows no command-sweep requirement to call `scripts/log-providers.sh`. One concrete reason: without explicit per-command edits, dispatch sites may skip observability logging, leaving no audit trail.
- **Discovery command is model-dependent.** `commands/z-providers-discover.md` is specified as an interactive markdown procedure, not a standalone executable. One concrete reason: it depends on the orchestrating Claude Code model correctly implementing `AskUserQuestion`, conflict handling, env passing, and atomic write — if any step fails, there's no fallback.
- **Discovery validation is incomplete.** `scripts/discover-providers.py` checks `PATH` and emits hard-coded defaults, but does not validate that detected CLIs accept the configured args or stdin mode. One concrete reason: generated `providers.json` can be syntactically valid but operationally broken (e.g., `gemini` detected but `-p "" --approval-mode plan` args rejected).
- **Export generation leaves stale outputs.** `scripts/export-cursor.py` (and siblings) do not appear to clean removed source outputs before writing new files. One concrete reason: deleted agents (e.g., `codex-consultant.md`) can survive as stale `.mdc` rules in the generated tree, confusing users about which agents are actually available.
- **Doc index update requirement was underspecified.** The spec says "edit `docs/llm/INDEX.json`" but does not enforce a sweep to remove deleted agent references. One concrete reason: `docs/llm/agents.json` still lists `codex-consultant`, `gemini-consultant`, `codex-reviewer` as live concepts, contradicting the claimed deletion.

### Minor (2 issues)
- **Documentation sweep missed legacy references.** `README.md` still references `codex-reviewer`, `codex-consultant`, and `gemini-consultant` in tree diagrams and command descriptions. One concrete reason: `z-implement-all` description still mentions `codex-reviewer` safety gate, not the new provider-agnostic `reviewer`.
- **Human docs reference deleted agents.** `docs/human/agents.md` still describes deleted agent files; `docs/human/mr-reviewer.md` still refers to `codex-consultant` and `gemini-consultant` voices; `docs/human/style-init.md` still mentions deleted consultant names. One concrete reason: stale user-facing guidance contradicts the portable-harness design goal.

---

## Summary

**Implementation completion: ~30-40%.** Core foundation (plan-path, resolve-provider, discover-providers) is present in new source files, but:
- All three new canonical agents (consultant-primary, consultant-secondary, reviewer) are missing.
- All three IDE export targets (scripts + generated output trees) are missing.
- All three new slash commands (/z-providers-discover, /z-export, /z-update) are missing.
- All supporting docs (PROVIDERS.md, INSTALL.md, MULTI-IDE.md) are missing.
- Legacy agent deletion was completed, but dispatch sites were not successfully migrated (docs still reference old names).

**Spec design gaps.** Several assumptions in the spec were not validated by implementation:
- Provider invocation contract (shell args quoting, stdin vs args vs placeholder expansion) is underspecified.
- Schema validation, de-dup semantics, and observability hooks lack enforcement.
- Export cleanup, doc index updates, and reference sweeps were not thoroughly specified.

