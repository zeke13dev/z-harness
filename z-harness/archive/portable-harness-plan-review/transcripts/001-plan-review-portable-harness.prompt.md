MODE: plan-review

**SPEC.md** (input artifact — file-level spec for portable-harness):

Restructure z-harness to:
1. Relocate plan output to `z-harness/plans/<slug>/` (cleanup)
2. Generalize LLM-provider routing via config-file registry (CLI-only, hybrid user-global + repo-local)
3. Export commands+agents+skills to Cursor / Codex CLI / Antigravity (agy) with per-target CAPABILITIES.md
4. Symlink + tarball distribution + `/z-update` refresh command
5. Three stable agent files: `consultant-primary.md`, `consultant-secondary.md`, `reviewer.md` (provider-agnostic via role names)

Files updated: all 23 commands, scripts, agents that reference `z-harness/<slug>` paths.
Helper: `scripts/plan-path.sh` (single-source-of-truth for path construction).
Provider registry: `~/.config/z-harness/providers.json` + `<repo>/.z-harness/providers.json` (versioned schema v1, precedence per-key, not whole-file merge).
Discovery: `scripts/discover-providers.sh` (shell, deterministic) + `/z-providers-discover` slash command (user-driven with role binding).
Export pipeline: Claude Code canonical → per-target adapters (Cursor, Codex, agy) → per-target CAPABILITIES.md + smoke test.
Distribution: `install.sh` (symlink or tarball), `scripts/bundle-plugin.sh`, `/z-update` command (git pull for symlink, atomic tarball swap for tarball).
Docs: new INDEX entries, PROVIDERS.md, INSTALL.md, MULTI-IDE.md, README rewrite.

DRY/KISS/SOLID checks all present. Edge cases listed: no providers.json, unbound roles, missing CLI on PATH, Z_HARNESS_PLANS_DIR override, /z-update with uncommitted changes, export filters, consultant-primary/secondary must be distinct.

Non-goals: lossless multi-IDE, autoupdate, per-task provider override, legacy removal in this plan, Anthropic API adapter.

---

**PLAN.md** (implementation sequencing — 9 phases):

Phase 1: plan-path helper + migration script + dual-read fallback.
Phase 2: Mechanical path edits across 23 commands/scripts/agents.
Phase 3: Provider registry (resolve-provider.sh + schema docs + tests).
Phase 4: Discovery + /z-providers-discover command.
Phase 5: Consultant + reviewer rewrite (canonical agents, delete legacy, sweep dispatch sites).
Phase 6: Agy adapter research (agy --help + docs) + spec lock-in.
Phase 7: Export pipeline (Cursor, Codex, agy, per-target CAPABILITIES.md, smoke tests).
Phase 8: Distribution (install.sh, bundle-plugin.sh, /z-update).
Phase 9: Docs sweep.

Decisions: D1-D13 identified. Approved shortcuts: dual-read migration for one release, legacy shims ripped (user override), agy first-class.

---

**Context for critique:**

This is a follow-up consult. Round 1 already happened on bundled decisions; round-1 concerns about CLI-only registry, no parameterized middleman, deterministic discovery, and per-target CAPABILITIES.md were adopted. User locked two decisions: (a) source-of-truth stays Claude Code shape, and (b) legacy agent shims are ripped (not kept for a release).

---

**Your task:**

Critique this plan — what's wrong, missing, or fragile? Focus on:
- **Drift:** Any gap between SPEC and PLAN (e.g., SPEC says X but PLAN doesn't cover it, or vice versa)?
- **Non-goals:** Any non-goal that should be a goal, or vice versa?
- **Edge cases:** Any unhandled scenario or ordering risk?
- **DRY/KISS/SOLID:** Any pattern violation?
- **Ordering risks:** Do the 9 phases work in the stated order, or are there hidden dependencies?

Be terse. Bullets. File:line where possible. Don't repeat round-1 concerns (CLI-only, no parameterized middleman, deterministic discovery, per-target CAPABILITIES.md — already decided).
