# z-harness

A Claude Code plugin that wraps planning and implementation in a rigorous, cross-LLM-reviewed pipeline. Every command writes artifacts to `z-harness/<slug>/`, with run-frozen archives and aggregated telemetry in `z-harness/metrics.jsonl`. Designed for engineers who want AI-assisted code changes to go through a real review loop rather than land silently.

## Install

**Claude Code from a local clone (symlink mode):**

```bash
git clone https://github.com/<org>/z-harness
cd z-harness
bash install.sh
bash scripts/config.sh ensure-defaults  # creates ~/.config/z-harness/config.toml with defaults
```

After installing, run `/z-providers-discover` in Claude Code to configure which LLM CLIs play which roles. For Codex, tarball mode, or full install details, see [docs/human/INSTALL.md](docs/human/INSTALL.md).

## Quickstart

- `/z-do <small task>` — plan-less execution for small changes
- `/z-plan <task>` — rigorous planning pipeline (SPEC/PLAN/TASKS)
- `/z-implement-all` — orchestrate the queue from a /z-plan output

## Command catalogue

### Pre-planning

- **`/z-map <question>`** — Maps terrain with citations + cross-LLM critique. No recommendations — terrain only. Produces `MAP.md`. Cost target: ≤2M tokens.
- **`/z-brainstorm <topic>`** — Cheap parallel idea generation across three vendor-diverse ideators. Produces `BRAINSTORM.md`. Cost target: ≤200K tokens.
- **`/z-research <topic>`** — Higher-order meta-orchestrator. Composes `/z-map` and `/z-brainstorm`, then runs adversarial synthesis panel producing `RESEARCH.md` with approach decision matrix. Cost 3–6M tokens; cost gate at invocation.

Typical chains:
- Murky problem with unknown terrain: `/z-map → /z-brainstorm → /z-plan`
- Murky problem needing full synthesis: `/z-research → /z-plan`
- Lighter case: `/z-brainstorm → /z-plan`
- Standard: `/z-plan` alone

### Planning

- **`/z-plan <task>`** — Rigorous pipeline: premise check → exploration → enumerate decisions → bundled cross-LLM consult → SPEC.md / PLAN.md / TASKS.md.
- **`/z-plan-light <fix>`** — Fast path for 1–5 file fixes; auto-bails to `/z-plan` if scope grows.
- **`/z-plan-split <topic>`** — Pre-emptive scope splitter for sprawling topics.
- **`/z-test`** — Semantic test-case planner; writes `TESTS.md`.

### Implementation

- **`/z-implement-all`** — Orchestrates the full TASKS.md queue with per-task reviewer safety gate and retry.
- **`/z-implement-next`** — Same loop, one task at a time.

### Audit, debug, review

- **`/z-audit <target>`** — Read-only audit pipeline; emits REPORT.md + TASKS.md.
- **`/z-fix <symptom>`** — Lightweight bug-fix command.
- **`/z-debug <symptom>`** — Adversarial hypothesis tournament; writes `DEBUG.md`.
- **`/z-review-all`** — Final-gate cross-LLM review of a completed plan's cumulative diff.
- **`/z-uplift`** — Bulk codebase quality uplift across the whole repo.

### Docs and memory

- **`/z-init-docs`** — Bootstrap two-tier docs (`docs/human/` + `docs/llm/INDEX.json`).
- **`/z-maintain-docs`** — Refresh stale concepts. Dry-run preview by default.
- **`/z-suggest-memory`** — Author a memory entry into a concept's `docs/llm/<slug>.json`.
- **`/z-stats`** — Read-only progress + cost report from `metrics.jsonl`.

## Where to look next

- [docs/human/INDEX.md](docs/human/INDEX.md) — human reference (commands, skills, agents, scripts)
- [docs/llm/INDEX.json](docs/llm/INDEX.json) — LLM-tier two-tier docs; agents read this via doc-fetcher
- [docs/human/config.md](docs/human/config.md) — TOML config (notify level, doc-fetcher policy)

## License

MIT
