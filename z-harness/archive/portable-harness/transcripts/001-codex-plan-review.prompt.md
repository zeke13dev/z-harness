MODE: plan-review

## SPEC.md (full)
See above — file covers: plan-layout migration, provider registry (hybrid config, 3 roles, CLI-only kind), role-named agent files (consultant-primary, consultant-secondary, reviewer), multi-IDE export (Cursor, Codex, Agy with per-target CAPABILITIES.md), symlink + tarball install + /z-update, and docs updates.

Path layout: z-harness/plans/<slug>/ with dual-read fallback (legacy z-harness/<slug>/).
Provider schema: versioned JSON with per-key precedence (repo-local overrides user-global).
Export shape: Claude Code → per-target adapters → exports/<target>/ trees.
Roles: three fixed (consultant_primary, consultant_secondary, reviewer); cross-model invariant enforced (they must resolve to distinct providers).
Non-goals: lossless compile, autoupdate, per-task provider override.

## PLAN.md (full)
9 phases:
1. Foundation: plan-path.sh + migrate-plan-layout.sh + dual-read plumbing
2. Sweep: command/script path edits (~13 commands + scripts + agents)
3. Provider registry: resolve-provider.sh + schema + event taxonomy
4. Discovery: discover-providers.sh + /z-providers-discover
5. Consultant/reviewer rewrite: 3 new agents, delete legacy, dispatch-site sweeps
6. Agy adapter research + spec lock-in
7. Export pipeline (Cursor → Codex → agy) with CAPABILITIES.md + smoke tests
8. Distribution: install.sh + bundle-plugin.sh + /z-update
9. Docs sweep + INDEX.json updates + README rewrite

Decisions: path layout (D1), dual-read + migration (D3), hybrid CLI-only registry (D4), role-named stable agents (D5), shell discovery (D7), Claude Code shape + per-target adapters (D8), symlink + tarball + /z-update (D13).

Background context (from previous round):
- Dual-read migration adopted.
- Explicit per-key precedence in hybrid config adopted.
- Stable role-named agent files adopted; legacy shims ripped.
- Machine-local discovery scope (shell, deterministic) adopted.
- Per-target CAPABILITIES.md adopted.
- Agy export is first-class (not experimental).
- Source-of-truth stays Claude Code shape.

## Critique task
Critique this plan — what is wrong, missing, or fragile? Particularly:
- Drift between SPEC and PLAN (e.g., SPEC says X but PLAN doesn't call it out or sequence it).
- Non-goal that should be a goal, or vice versa.
- Edge case not covered (invariants, error paths, compat risk).
- DRY/KISS/SOLID violations.
- Ordering risk in the 9 phases (dependencies, circular deps, parallelism missed).

Be terse, bullets. File:line where possible. Do NOT repeat round-1 concerns.
