MODE: bundled-decisions

## Input artifact: consult-flagged decisions from /z-plan phase 2

The user is restructuring z-harness (Claude Code plugin) with four major themes:
1. **Plan output relocation** (D1–D3): move `z-harness/<slug>/` → `z-harness/plans/<slug>/`
2. **Provider abstraction** (D4–D7): introduce configurable LLM provider registry; replace hardcoded `codex` / `gemini` CLIs
3. **Multi-IDE export** (D8–D12): make commands/agents/skills portable to Cursor Rules, Codex CLI, Antigravity (`agy`)
4. **Instant updates** (D13–D14): symlink install + `/z-update` command

Focusing on **five consult-flagged decisions (D3, D4, D5, D7, D8)** in the first bundle.

---

## D3 — Backwards compat for existing in-flight plans

**Tentative call:** (a) one-shot migration script (`scripts/migrate-plan-layout.sh`), idempotent, plus a single grace-period release where commands log a warning if they see a legacy `z-harness/<slug>/PLAN.md`.

**Options:**
- (a) one-shot migration (idempotent) + grace-period warning
- (b) dual-read fallback in every command (try new path, fall back to old)
- (c) cold cutover — old plans abandoned; only new plans use new path

**Load-bearing fact:** ~10 existing plans in user's dogfood; each has `z-harness/<slug>/PLAN.md`, `z-harness/<slug>/archive/<run-id>/events.jsonl`, etc. If migration botches, user loses run history (events.jsonl) or plan artifacts.

---

## D4 — Provider registry: location and schema

**Tentative call:** (c) hybrid — user-global default at `~/.config/z-harness/providers.json` (XDG) + repo-local `.z-harness/providers.json` for team overrides.

**Schema sketch:**
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

**Current state:** consultants hardcoded to invoke CLI by name:
- `agents/codex-consultant.md` calls `codex exec "<prompt>"`
- `agents/gemini-consultant.md` calls `gemini -p "<prompt>" --approval-mode plan`

**Public surface:** This schema becomes the interface between user config and every command/agent that dispatches consultants. Rename-proof? Schema extensible? Breaking changes later?

---

## D5 — Consultant agents: keep two specific roles or generalize?

**Tentative call:** (b) one generic `consultant.md` that takes a `role` parameter (consultant_a / consultant_b / ...) and routes via registry. Keep thin shims `codex-consultant.md` / `gemini-consultant.md` for backward-compat one release only.

**Current dispatch pattern in commands:**
```
Example from z-plan.md Phase 3:
Agent(subagent_type="consultant", role="consultant_a", prompt="MODE: bundled-decisions\n...")
Agent(subagent_type="consultant", role="consultant_b", prompt="MODE: bundled-decisions\n...")
```

**Affected call sites (from context):** z-plan, z-audit, z-plan-light, z-fix, z-debug, z-mr-review.

**Options:**
- (a) Keep two files, make them read registry under `consultant_a` / `consultant_b`
- (b) One generic `consultant.md`, thin shim aliases for compat
- (c) Generate per-provider files at install time from template

---

## D7 — Haiku discovery of provider CLIs

**Tentative call:** (b) one-shot `/z-providers-discover` slash command — Haiku agent probes PATH for known CLIs (`codex`, `gemini`, `claude`, `gpt`, `ollama`, `agy`) and writes to the registry.

**Options:**
- (a) On-demand: when role is requested with no registry entry, dispatch Haiku subagent to probe and propose
- (b) One-shot `/z-providers-discover` command
- (c) Skip — require manual registry

**Trade-off stated:** (a) has latency cost; (b) has discovery latency once, at setup or when user adds a new tool.

---

## D8 — Multi-IDE export: pull vs push, source-of-truth

**Tentative call:** (a) Claude Code format stays canonical. `scripts/export-<target>.py` reads commands/*.md + agents/*.md + skills/*/SKILL.md and emits target format (Cursor Rules, Codex CLI manifest, agy plugin). Lossy exports with documented fidelity gaps.

**Options:**
- (a) Claude Code shape canonical; lossy exports
- (b) Neutral schema in `portable/` dir; per-IDE compilers consume it
- (c) Hand-write target-specific files

**Architectural risk:** Once you ship the first export, it's hard to pivot. Users will reference exported files; changing source-of-truth is a breaking change.

**Scope (D9):** ship all three IDE targets with minimum viable skeleton (one command/agent each end-to-end), marked `experimental:`.

---

## Context: coupled call sites and invariants

**Commands that read/write plan paths** (all will need relocation from `z-harness/<slug>/` to `z-harness/plans/<slug>/`):
- commands/z-plan.md (lines 24, 35, 50–58)
- commands/z-audit.md, z-test.md, z-implement-all.md, z-mr-review.md, z-improve.md, z-brainstorm.md, z-research.md, z-maintain-docs.md
- scripts/log-event.sh (path assembly)
- docs/llm/commands.json:197 (invariant documenting path shape)

**Commands that dispatch consultants** (all will need to route through provider registry instead of CLI name):
- z-plan.md (Phase 3 bundled consults)
- z-audit.md, z-plan-light.md, z-fix.md, z-debug.md, z-mr-review.md

---

## Question for Gemini

For each consult-flagged decision (D3, D4, D5, D7, D8):
1. **What's the strongest concrete reason the tentative call is wrong?** (Not "could be better" — show a failure mode or requirement miss.)
2. **Is there a better alternative?** (Only flag if the tentative call genuinely misses a constraint.)
3. **What failure mode does it create** (in production, dogfooding, or future extension)?
4. **Cross-decision interactions:** Do any of D3–D8 destabilize each other? (E.g., D3's migration and D4's registry both touch paths; D5's generic consultant + D7's discovery creates new latency; etc.)

Keep critique **terse** — bullets, file-paths, concrete failure modes. Do not propose entirely new decisions outside the 5 unless they directly destabilize one.

