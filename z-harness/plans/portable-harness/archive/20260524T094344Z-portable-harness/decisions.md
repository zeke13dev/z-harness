# Phase 2 — Decisions doc

User has accepted >5 consult-flagged decisions for this plan. Hard cap of 5/bundle applies per round, so consults will go in **two waves** (Phase 3a + Phase 3b) rather than one.

---

## D1 — New plan-output path: `z-harness/plans/<slug>/`
- **Options:** (a) `z-harness/plans/<slug>/`; (b) `.z-harness/<slug>/` (hidden); (c) `plans/<slug>/` (move out of z-harness/ entirely).
- **Tentative:** (a) `z-harness/plans/<slug>/`. Keeps everything under the existing namespace; only one symbol changes.
- **Consult? no.** User pre-specified this shape; mechanical move.

## D2 — Archive sub-path also moves
- Today: `z-harness/<slug>/archive/<run-id>/`. After D1: `z-harness/plans/<slug>/archive/<run-id>/`. The top-level `z-harness/archive/` (legacy orchestration logs) stays put.
- **Tentative:** archive lives inside the relocated plan dir, as today (relative to slug).
- **Consult? no.** Direct consequence of D1.

## D3 — Backwards compat for existing in-flight plans
- **Options:** (a) one-shot migration script that moves existing `z-harness/<slug>/` → `z-harness/plans/<slug>/`; (b) dual-read fallback in commands (look at new path, fall back to old); (c) leave old plans behind, only new plans use new path.
- **Tentative:** (a) one-shot migration script (`scripts/migrate-plan-layout.sh`), idempotent, plus a single grace-period release where commands log a warning if they see a legacy `z-harness/<slug>/PLAN.md`.
- **Consult? yes.** Touches the user's existing dogfooded plans (~10 dirs); a botched migration is annoying.
- **Trigger:** reversibility — wrong migration loses plan history; affects multiple modules.

## D4 — Provider registry: where it lives and its schema
- **Options:** (a) `~/.config/z-harness/providers.json` (user-global, XDG); (b) repo-local `.z-harness/providers.json`; (c) hybrid: user-global default, repo-local overrides.
- **Tentative:** (c) hybrid. User-global covers personal setup; repo-local lets a teammate pin "this repo uses gpt-5 for review".
- **Schema sketch:**
  ```json
  {
    "providers": {
      "<name>": {
        "kind": "cli" | "anthropic_api",
        "cli": {"command": "codex", "args_template": ["exec", "-"], "stdin": true, "timeout_s": 300},
        "anthropic_api": {"model": "claude-opus-4-7"}
      }
    },
    "roles": {
      "consultant_a": "codex",
      "consultant_b": "gemini",
      "reviewer": "codex"
    }
  }
  ```
- **Consult? yes.** Public schema; rename-resistant; touches every consultant agent + reviewer.
- **Trigger:** public surface; >1 module; reversibility.

## D5 — Consultant agents: keep two specific roles, or generalize?
- **Options:** (a) Keep `codex-consultant` + `gemini-consultant` files but make them read provider registry under those role names; (b) Replace both with one generic `consultant.md` that takes `provider` as a prompt parameter; (c) Generate per-provider files at install time from a template.
- **Tentative:** (b) one `consultant.md` that takes a `role` (consultant_a / consultant_b) and routes via registry; keep aliases `codex-consultant.md` / `gemini-consultant.md` as thin shims for backward-compat for the duration of one release.
- **Consult? yes.** Affects every command that dispatches consultants (bundled consult calls in /z-plan, /z-audit, /z-plan-light, /z-fix, /z-debug, /z-mr-review).
- **Trigger:** boundary change; touches many commands.

## D6 — Reviewer agent: same generalization?
- **Tentative:** yes — `codex-reviewer.md` becomes `reviewer.md`, reads `roles.reviewer`. Same shim pattern.
- **Consult? no.** Mirrors D5 with no new decisions; rises and falls with it.

## D7 — Haiku discovery of provider CLIs
- **Options:** (a) On-demand: when a role is requested with no registry entry, dispatch a Haiku subagent to `which`/probe known CLIs and propose an entry; (b) One-shot `/z-providers-discover` slash command; (c) Skip — require manual registry.
- **Tentative:** (b) one-shot `/z-providers-discover` (Haiku agent that probes PATH for known CLIs — `codex`, `gemini`, `claude`, `gpt`, `ollama`, `agy` — and writes the registry). On-demand probing inside hot paths bloats latency.
- **Consult? yes.** New slash command, new surface, decision shapes the user's onboarding.
- **Trigger:** new public surface.

## D8 — Multi-IDE export: pull vs push, source-of-truth
- **Options:** (a) Source-of-truth = `commands/*.md` + `agents/*.md` + `skills/*/SKILL.md` (Claude Code shape); `scripts/export-<target>.py` reads them and emits target format. (b) Source-of-truth = neutral schema in `portable/` dir; per-IDE compilers including Claude Code consume it. (c) Hand-write target-specific files.
- **Tentative:** (a) Claude Code shape stays canonical; lossy exports to other IDEs. Honest about fidelity gaps.
- **Consult? yes.** Architectural; hard to reverse once we ship the first export.
- **Trigger:** affects every command/agent file; >1 module; reversibility >1h.

## D9 — Which IDE exports we ship in this plan
- **Options:** Cursor, Codex CLI, Antigravity (agy) — all three; or scope to Cursor only first.
- **Tentative:** ship all three skeletons, with a minimum viable export per target (a single command/agent each end-to-end). Mark unfinished targets `experimental:`.
- **Consult? no.** User explicitly named all three.

## D10 — Cursor Rules format
- **Options:** legacy `.cursorrules` single file vs newer `.cursor/rules/*.mdc` per-rule files (one MDC per command/agent/skill).
- **Tentative:** `.cursor/rules/*.mdc` (current Cursor recommendation; gives per-rule glob targeting + descriptions). Verify at implementation time.
- **Consult? no.** Format choice, but consensus is clear; verification is mechanical.

## D11 — Codex CLI export shape
- **Options:** (a) Codex `AGENTS.md` + per-prompt files in `.codex/prompts/`; (b) shell-script wrappers per command.
- **Tentative:** (a) Codex's documented "custom prompt" structure if it exists; else (b) shell wrappers. Resolve at implementation time via WebFetch + smoke test.
- **Consult? no.** Format choice deferred.

## D12 — Antigravity (`agy`) export shape
- **Tentative:** Defer — needs `agy --help` / agy docs read during implementation; export shape will mirror whichever of {Claude Code, Codex} agy supports natively. Spec a "best-effort, marked experimental" target.
- **Consult? no.** Pure research task.

## D13 — Instant updates mechanism
- **Options:** (a) Symlink install: `ln -s $REPO ~/.claude/plugins/z-harness@zeke-tools`. Edits are live without reinstall. (b) Single-file fetch: `curl … | tar xz`, with optional `Z_HARNESS_AUTO_UPDATE=1` HEAD-check at run-start. (c) Both.
- **Tentative:** (c) both — symlink for self-hosted dev (this repo's primary user), single-file `install.sh` for casual users. No autoupdate-on-hot-path (it'd slow down `/z-plan` start); a separate `/z-update` slash command instead.
- **Consult? yes.** Distribution surface; affects how every user gets every future change.
- **Trigger:** public surface; reversibility (changing install model after users adopt it is painful).

## D14 — `/z-update` slash command vs cron/hook
- **Tentative:** explicit `/z-update` slash command that pulls/refreshes the install. No background hook.
- **Consult? no.** Follows D13 directly.

## D15 — `Z_HARNESS_PLANS_DIR` env override
- **Tentative:** support a `Z_HARNESS_PLANS_DIR` env (default `z-harness/plans`) so users can move plans elsewhere (e.g. outside the repo). Path resolution: `${Z_HARNESS_PLANS_DIR}/<slug>/`.
- **Consult? no.** Small ergonomics knob; non-breaking.

## D16 — Docs updates
- Update `docs/llm/commands.json:197` invariant. Update `docs/human/` for new install methods, provider registry, export commands. Update README install section.
- **Consult? no.** Mechanical.

---

## Consult-flagged decisions (this bundle)

| ID | Topic | Wave |
|----|-------|------|
| D3 | Migration of existing plan dirs | 3a |
| D4 | Provider registry location + schema | 3a |
| D5 | Consultant generalization | 3a |
| D7 | Provider discovery: when/how | 3a |
| D8 | Multi-IDE export architecture | 3a |
| D13 | Distribution / instant-updates mechanism | 3b |

Wave 3a = 5 (cap). D13 deferred to Wave 3b (a second consult round on the final SPEC+PLAN at Phase 7 absorbs it — distribution decision can wait for the synthesis pass).
