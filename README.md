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

## Where to look next

- [docs/human/INDEX.md](docs/human/INDEX.md) — human reference (commands, skills, agents, scripts)
- [docs/llm/INDEX.json](docs/llm/INDEX.json) — LLM-tier two-tier docs; agents read this via doc-fetcher
- [docs/human/config.md](docs/human/config.md) — TOML config (notify level, doc-fetcher policy)

## License

MIT
