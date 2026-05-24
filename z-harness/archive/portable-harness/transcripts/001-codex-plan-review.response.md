## Critical inconsistencies and missing details

**Provider invariant conflict:** `SPEC.md:190` only requires `consultant-primary` and `consultant-secondary` to be distinct, but `SPEC.md:82` shows both resolving to codex while `reviewer=codex`. The invariant as stated contradicts the example. Clarify: are all three roles required distinct, or only the two consultants?

**Non-goals not in PLAN:** `PLAN.md:22-26` restates non-goals but omits `SPEC.md:197` (no per-task provider override) and `SPEC.md:198` (legacy fallback stays this release). Both affect scope and review criteria — list them explicitly.

**Abstraction mismatch (provider invocation):** `SPEC.md:176` references `scripts/llm-cli/` per-provider adapters, but `SPEC.md:96` says agents invoke `command + args_template` directly. Neither `SPEC.md:38` nor `PLAN.md` creates per-provider CLI wrappers. Decide: wrapper shims or direct invocation?

**Stdin/argument interpolation:** `SPEC.md:96` says prompt goes through stdin, but `SPEC.md:110` lists Gemini's `-p ...` template which expects argument text. Schema has `stdin: true`, but no model for how non-stdin CLIs get the prompt text or how quoting/escaping happens.

**Provider merge semantics unclear:** `SPEC.md:74` says repo-local overrides user-global "per key", but provider entries are nested JSON objects. Does repo-local `providers.codex.timeout_s` override only timeout, or the entire `codex` provider block? Specify merge depth (top-level keys only, or recursive).

**Thin event taxonomy:** `PLAN.md:36` only names `provider_resolved` / `provider_shadowed`. Missing events for: malformed JSON, unsupported schema version, unbound role, missing CLI on PATH, CLI timeout, nonzero exit, provider collision check failure. Those will be inconsistent across commands without a shared schema.

**Run-start provider logging:** `SPEC.md:82` says every command logs all roles at startup. `PLAN.md:36-38` has no shared preflight helper — this becomes duplicated markdown across ~13 commands. Extract to a helper script with one definition.

**Path sweep is incomplete:** `PLAN.md:35` says `commands/*.md`, `agents/*.md`, `scripts/*.sh`, but path refs also live in `scripts/test_extract_dismissals.py`, `README.md`, `docs/llm/*.json`, `docs/human/*.md`. `SPEC.md:25-29` list is missing `agents/remote-runner.md`, `agents/auditor.md`, `agents/mr-reviewer.md` (found by grep). Use a grep-based discovery to avoid stale path lists.

**Split-plan layout ambiguity:** `/z-plan-split` uses tree-rooted paths today: `z-harness/<root>/<cluster>/`. The new canonical path `z-harness/plans/<slug>/` doesn't specify whether cluster subdirs become `z-harness/plans/<root>/<cluster>/` or `z-harness/plans/<root>/plans/<cluster>/`. Clarify before phase 1.

**Migration script gaps:** `migrate-plan-layout.sh --all` (`SPEC.md:41-42`) doesn't specify discovery logic. Exclusions: `z-harness/archive`, `z-harness/metrics.jsonl`, future `z-harness/plans`, partial runs? Needs a predicate and a `--dry-run` or `--list` mode.

**Migration event ordering:** `SPEC.md:42` says migration logs `migration_done`, but if this happens before `log-event.sh` is updated (phase 1), the event lands in legacy location. Reorder phase 1 to update `log-event.sh` + `log-phase.sh` before running any migrations.

**Legacy write behavior:** `SPEC.md:23` says legacy fallback is read-only, but `/z-amend`, `/z-implement-all`, `/z-test`, `/z-improve` write to the selected plan. If user selects a legacy plan via fallback, do they write legacy, auto-migrate first, or halt? Not specified.

**Provider discovery recursion risk:** `SPEC.md:184` says missing config triggers `/z-providers-discover` implicitly if interactive. Slash commands don't reliably recurse into other slash commands in all environments. Use an explicit shared script, not `Agent(subagent_type="z-providers-discover", ...)`.

**Discovery validation loop:** `/z-providers-discover` must validate that discovered providers cover the three roles and they're distinct. If only one CLI is found (e.g., only `codex`), discovery should ask user before accepting or explicitly bind the same provider to multiple roles (violating the invariant). Add a validation gate.

**Export smoke tests are not testable:** `SPEC.md:140` says "verified to load by hand". This is not automatable and can't be reviewed. Define minimum static checks (e.g., JSON schema validity, mdc file syntax for Cursor), and keep "manual IDE check" as a separate release/launch checklist, not a blocker.

**Agy research timing is risky:** Agy research is phase 6, after agent/provider rewrites (phases 1-5). If agy cannot express required subagent shapes or provider abstractions, adapter design may force changes to source files after they're finalized. Move Agy research to phase 0 (pre-implementation) alongside provider & agent contract lock-in.

**Export tarball payload unclear:** `bundle-plugin.sh` (`SPEC.md:153`) excludes plan/archive/provider files, but doesn't say whether `exports/` is included. If tarball is the full plugin payload, including pre-generated IDE exports may bloat installs; if excluded, `/z-export` must regenerate post-install. Specify.

**Docs sequencing delays stale guidance:** Stale docs already list `agents/codex-consultant.md` and old paths. Phases 1-8 can complete while repo docs remain actively misleading. Update `docs/llm/*.json` for touched contract surfaces (agent names, path conventions, command dispatch) as each phase lands, not phase 9.
