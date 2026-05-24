# PLAN.md — portable-harness

## Goals
1. Eliminate plan-output pollution at top of `z-harness/` by relocating to `z-harness/plans/<slug>/`.
2. Generalize LLM provider routing through a versioned, hybrid (user-global + repo-local) JSON registry — no more hardcoded `codex` / `gemini` CLI invocations.
3. Make consultant + reviewer agent files provider-agnostic via role names (`consultant_primary`, `consultant_secondary`, `reviewer`).
4. Export commands+agents+skills to Cursor, Codex CLI, and Antigravity (agy), with per-target CAPABILITIES.md.
5. Provide symlink-based instant updates for self-hosted users, tarball install for casual users, and an explicit `/z-update` refresh command.

## Decisions (with rationale)

| ID | Decision | Why |
|----|----------|-----|
| D1 | Plans live under `z-harness/plans/<slug>/` | Separates plan output from infra dirs (`archive/`, `metrics.jsonl`) at top of `z-harness/`; user-requested. |
| D3 | Dual-read fallback for one release; migration script | User has ~10 in-flight plans; hard-fail would block. Compat tail is short. |
| D4 | CLI-only provider registry, hybrid config, explicit per-key precedence, run-start resolved-provider log | API-kind adds complexity; CLI uniformity is simpler. Hybrid covers personal + team setups. Explicit precedence prevents silent shadowing. |
| D5 | Stable role-named agent files (`consultant-primary`, `consultant-secondary`, `reviewer`); legacy files deleted | Static files are export-clean (D8 alignment); thin shim middleman wastes tokens + breaks Cursor/agy export. User opted to rip legacy now. |
| D7 | `scripts/discover-providers.sh` (deterministic shell) wrapped by `/z-providers-discover`; user-global default | LLM probing PATH is over-engineering for a small known CLI set. Shell is deterministic + fast. |
| D8 | Claude Code shape canonical; per-target adapter scripts; per-target CAPABILITIES.md; smoke-test gate | Neutral-schema rewrite is too large for v1. CAPABILITIES.md + smoke test give honest fidelity guarantees. Agy gets first-class adapter per user direction. |
| D13 | Symlink + tarball install via `install.sh`; `/z-update` slash command; no autoupdate | Symlink for dev (hot iter); tarball for casual; autoupdate adds latency to hot paths and can introduce silent breakage. |

## Non-goals
- Lossless export across IDEs.
- Background or hot-path autoupdate.
- Anthropic API as a registry "kind".

## Approved shortcuts (Phase 5 user approval)
- Dual-read migration for one release (D3).
- Legacy agent shim files are **not** kept (user reversed the recommendation — rip immediately).
- Agy adapter is **first-class** (user reversed `experimental` → full adapter).

## Ordered phases (implementation sequencing)

1. **Foundation: plan-path helper + migration script + dual-read.** Lands the `Z_HARNESS_PLANS_DIR` plumbing first; every later command edit picks it up trivially.
2. **Sweep: command/script path edits.** Mechanical replace across all `commands/*.md`, `agents/*.md`, and `scripts/*.sh` that reference `z-harness/<slug>`.
3. **Provider registry.** Add `scripts/resolve-provider.sh`, schema docs, and `provider_resolved` / `provider_shadowed` event taxonomy. Tests against fixture providers.json.
4. **Discovery + slash command.** `scripts/discover-providers.sh` + `commands/z-providers-discover.md`.
5. **Consultant + reviewer rewrite.** Author canonical `consultant-primary.md`, `consultant-secondary.md`, `reviewer.md`. Delete legacy files. Sweep all dispatch sites in commands to new names.
6. **Agy adapter research + spec lock-in.** `agy --help` + docs read; spec `agy-plugin.yaml` shape. Output a small design note saved under the run's archive.
7. **Export pipeline (Cursor first, then Codex, then agy).** Per-target adapter scripts; `commands/z-export.md`; per-target `CAPABILITIES.md`. Smoke-test gates per target.
8. **Distribution: `install.sh` + `bundle-plugin.sh` + `/z-update`.**
9. **Docs sweep.** `docs/human/PROVIDERS.md`, `INSTALL.md`, `MULTI-IDE.md`; INDEX.json updates; README install rewrite.

## DRY / KISS / SOLID — how this plan respects them
- **DRY:** path + provider resolution are single-source-of-truth shell helpers used everywhere.
- **KISS:** three role names total; one registry kind (`cli`); no parameterized agents; no autoupdate.
- **SOLID:** new IDE target = new file under `exports/`, no source-file touching. New provider = entry in providers.json, zero code change.
