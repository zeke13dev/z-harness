MODE: bundled-decisions

## Input artifact: decisions.md excerpt (decisions D3, D4, D5, D7, D8)

### D3 — Backwards compat for existing in-flight plans
- **Options:** (a) one-shot migration script that moves existing `z-harness/<slug>/` → `z-harness/plans/<slug>/`; (b) dual-read fallback in commands (look at new path, fall back to old); (c) leave old plans behind, only new plans use new path.
- **Tentative:** (a) one-shot migration script (`scripts/migrate-plan-layout.sh`), idempotent, plus a single grace-period release where commands log a warning if they see a legacy `z-harness/<slug>/PLAN.md`.

### D4 — Provider registry: where it lives and its schema
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

### D5 — Consultant agents: keep two specific roles, or generalize?
- **Options:** (a) Keep `codex-consultant` + `gemini-consultant` files but make them read provider registry under those role names; (b) Replace both with one generic `consultant.md` that takes `provider` as a prompt parameter; (c) Generate per-provider files at install time from a template.
- **Tentative:** (b) one `consultant.md` that takes a `role` (consultant_a / consultant_b) and routes via registry; keep aliases `codex-consultant.md` / `gemini-consultant.md` as thin shims for backward-compat for the duration of one release.

### D7 — Haiku discovery of provider CLIs
- **Options:** (a) On-demand: when a role is requested with no registry entry, dispatch a Haiku subagent to `which`/probe known CLIs and propose an entry; (b) One-shot `/z-providers-discover` slash command; (c) Skip — require manual registry.
- **Tentative:** (b) one-shot `/z-providers-discover` (Haiku agent that probes PATH for known CLIs — `codex`, `gemini`, `claude`, `gpt`, `ollama`, `agy` — and writes the registry). On-demand probing inside hot paths bloats latency.

### D8 — Multi-IDE export: pull vs push, source-of-truth
- **Options:** (a) Source-of-truth = `commands/*.md` + `agents/*.md` + `skills/*/SKILL.md` (Claude Code shape); `scripts/export-<target>.py` reads them and emits target format. (b) Source-of-truth = neutral schema in `portable/` dir; per-IDE compilers including Claude Code consume it. (c) Hand-write target-specific files.
- **Tentative:** (a) Claude Code shape stays canonical; lossy exports to other IDEs. Honest about fidelity gaps.

## Context: current state

- Plan output: every command writes to `z-harness/<slug>/{SPEC,PLAN,TASKS}.md` + `z-harness/<slug>/archive/<run-id>/events.jsonl`.
- Consultants: hardcoded `codex exec` and `gemini -p` CLIs.
- Plugin install: via `/plugin marketplace add` + `/plugin install z-harness@zeke-tools`; no symlink or single-file fetch currently.
- IDE targets: Cursor (Rules), Codex CLI, Antigravity (agy).
- Goal: make harness portable across IDEs, support any LLM model/CLI, cleaner plan output structure, instant updates.

## Task

For each of D3, D4, D5, D7, D8: identify the strongest concrete reason the tentative call is wrong (if any), propose a better alternative (if applicable), and flag the failure mode it creates. Also identify any cross-decision interactions.

Be terse — bullets, file-paths where relevant. Do not propose new decisions outside the 5 unless they directly destabilize one of the 5.
