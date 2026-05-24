# Phase 3 — Final decisions (post-consult synthesis)

Each accepted recommendation is preceded by **one concrete reason it might be wrong** (per protocol).

---

## D1, D2 — Path relocation (no change)
- `z-harness/plans/<slug>/` for plan output. Archive lives inside (`z-harness/plans/<slug>/archive/<run-id>/`). Legacy `z-harness/archive/` (top-level orchestration logs) untouched.

## D3 — Migration: dual-read + warn for one release, then deprecate
- **Reason this might be wrong:** dual-read doubles path-resolution branches in every command and we carry the dead branch indefinitely if we forget to rip it out.
- **Final:** scripts/migrate-plan-layout.sh (idempotent) + commands prefer new path, fall back to legacy path with a single-line warning offering the exact migration command. Add a `MIGRATION_DEADLINE` line in the warning ("removed in next release"). Track removal as a follow-up task.
- (Adopts Codex's middle ground over Gemini's hard-fail.)

## D4 — Provider registry: CLI-only, hybrid config with explicit precedence
- **Reason this might be wrong:** dropping `anthropic_api` as a registry "kind" makes us ship and maintain a Python `anthropic-api-as-cli` adapter we wouldn't otherwise need.
- **Final:**
  - Registry schema is **CLI-only**. One `kind: cli`. No `anthropic_api` kind.
  - Bundle a thin adapter `scripts/llm-cli/anthropic-api.py` users can register as a CLI if they want Anthropic API fallback (auth via `ANTHROPIC_API_KEY`).
  - Hybrid config: user-global default at `~/.config/z-harness/providers.json`, repo-local override at `.z-harness/providers.json`. Precedence is explicit: **repo overrides user**, role-by-role and provider-by-provider. Shadowing is logged with a `provider_shadowed` event at run-start.
  - At every command's run-start: log resolved-provider+model for each role to stdout AND to `events.jsonl` (`provider_resolved` event).

## D5 — Consultant generalization: stable role-named files, no middleman shim
- **Reason this might be wrong:** role names `consultant-primary` / `consultant-secondary` are opaquer to a human reader than `gemini-consultant` / `codex-consultant`.
- **Final:**
  - Canonical files: `agents/consultant-primary.md`, `agents/consultant-secondary.md`, `agents/reviewer.md`. Each reads the registry to resolve its provider; the agent file itself is provider-agnostic.
  - Legacy names `agents/gemini-consultant.md`, `agents/codex-consultant.md`, `agents/codex-reviewer.md` become thin shims that delegate to the new files (one release of compat).
  - Every command that dispatches consultants is updated to use the new names.

## D6 — Reviewer agent: same generalization
- Adopted as part of D5 above.

## D7 — Provider discovery: shell script, user-global by default
- **Reason this might be wrong:** a hardcoded probe list won't catch new LLM CLIs users add in the future without us updating the list.
- **Final:**
  - `scripts/discover-providers.sh` — deterministic shell script that probes a hardcoded list (`codex`, `gemini`, `claude`, `ollama`, `agy`, `gpt`) via `command -v` and emits a proposed providers.json.
  - `/z-providers-discover` slash command wraps it with: (a) preview the proposed config; (b) confirm before write; (c) default write target is **user-global**, never repo-local unless `--repo` flag.
  - Future LLM CLIs the script doesn't know about: documented manual-add procedure in `docs/human/PROVIDERS.md`.
  - No Haiku in this hot path (consultants drop "Haiku discovery" idea entirely).

## D8 — Multi-IDE export: Claude Code canonical + per-target CAPABILITIES.md + smoke-test
- **Reason this might be wrong:** documenting fidelity gaps doesn't prevent broken installs; a user installs the Cursor export, it appears fine, blows up at runtime.
- **Final:**
  - **Source of truth stays Claude Code shape** (`commands/*.md`, `agents/*.md`, `skills/*/SKILL.md`).
  - Per target: `exports/<target>/CAPABILITIES.md` enumerating unsupported constructs (e.g. "Cursor: no Agent subagent dispatch; affected commands: /z-plan, /z-debug, …").
  - **Smoke test per target:** at least one command + one agent exported, manually verified to load in the target IDE during this plan. Mark every other export `experimental:` until similarly smoke-tested.
  - Reject Gemini's "neutral schema" proposal — over-engineering for v1; we'd rewrite every command file. Revisit if export count grows past 3 targets or fidelity loss becomes intolerable.

## D9–D16 — unchanged
D9 (ship 3 IDE skeletons), D10 (`.cursor/rules/*.mdc`), D11 (Codex prompt format TBD at impl-time), D12 (agy export experimental, research at impl), D13 (symlink install + `install.sh` + explicit `/z-update`, no autoupdate), D14 (`/z-update` is a slash command), D15 (`Z_HARNESS_PLANS_DIR` env override), D16 (docs updates).

---

## Shortcuts being taken (need user approval at Phase 5)
- **Antigravity (agy) export marked `experimental:`** — schema research happens during impl, may end up as raw shell-wrappers if agy lacks a native plugin shape. Robust alternative: build a full agy adapter with first-class manifest. Cost of shortcut: agy users get worse ergonomics until follow-up plan.
- **Migration dual-read carry** — commands carry a fallback path-read branch for one release. Robust alternative: hard-fail migration (Gemini's pick). Cost: a few branches of `if exists(old) ...` until deadline removal.
- **Single set of role names + thin shims for one release** — old `gemini-consultant.md` / `codex-consultant.md` / `codex-reviewer.md` kept as thin shims. Robust alternative: rip them out immediately. Cost: short compat tail.

## Cross-decision integrity checks (from consult)
- D4+D5: roles resolved centrally via registry; shims never hardcode provider names. ✓
- D4+D7: discovery writes user-global by default; repo-local opt-in via `--repo`. ✓
- D3+D8: every exporter reads new path `z-harness/plans/<slug>/` only; legacy fallback is a command-side concern. ✓
- D5+D8: stable role-named files are export-clean (no parameter passing). ✓
- D7+D8: exports must not bundle the local providers.json — add explicit exclusion in `scripts/export-*.sh`. ✓
