# external-lookup-agent

> Last updated: 2026-06-24
> Covers source: agents/external-lookup.md

## Overview

`external-lookup-agent` is the Haiku-tier retrieval worker defined in `agents/external-lookup.md`. The main thread delegates noisy external information gathering to it — web docs, public APIs, paginated JSON responses, and library docs outside the model training cutoff — so that retrieval artifacts do not pollute the orchestrator's context window.

The agent is strictly read-only. Every response follows the canonical `lookup-contract` envelope: a single `STATUS` line (`ok`, `partial`, or `refused`), then fixed `## Answer`, `## Provenance`, `## Unresolved`, and optional `## Raw artifact pointer` sections in that exact order. Total response size is capped at 3 KB; oversized raw material is spilled to `z-harness/lookup-cache/<sha256>.raw` and referenced via the artifact pointer section. The authoritative envelope definition lives in `docs/llm/lookup-contract.json`; if the inline agent prose ever conflicts with that JSON, the JSON wins.

## Key entry points

- `agents/external-lookup.md:1` — `external-lookup` — Agent frontmatter: Haiku model, description, and tool allowlist (`WebFetch`, `WebSearch`, `Bash`, `Read`, `Grep`, `Glob`).
- `agents/external-lookup.md:12` — `Output contract` — Fixed STATUS-headed Markdown envelope and required section order.
- `agents/external-lookup.md:51` — `Verb-blocklist` — Regex guard compiled once, tested before every Bash call; match produces `STATUS: refused`.
- `agents/external-lookup.md:91` — `Budget` — 3 KB total cap, normalized-query SHA256 rule, raw artifact cache behavior.
- `agents/external-lookup.md:99` — `Freshness discipline` — `freshness_ts` is the UTC retrieval timestamp (not document last-modified); stale cache (>24h mtime) forces `confidence: low`.
- `agents/external-lookup.md:105` — `Refusal modes` — Defines `ok`, `partial`, `refused` semantics and three refusal categories: `mutation_blocked`, `out_of_scope`, `auth_missing`.
- `agents/external-lookup.md:22` — `Provenance section format` — Provenance fields: `query`, `tools_used`, `sources`, `freshness_ts`, `confidence`, `commands`. Commands are always verbatim, never truncated in provenance.
- `agents/external-lookup.md:127` — `Confidence scale` — Three-value enum: `high` (authoritative source, no interpolation), `medium` (inference or partial contradiction), `low` (stale cache or single uncorroborated source).
- `agents/external-lookup.md:137` — `Edge cases` — Specifies partial/refused handling for 4xx/5xx, WebSearch no-results, pagination depth limit (WebFetch max depth 2), and auth-missing.
- `agents/external-lookup.md:144` — `Invariants` — Formal checklist: STATUS line first, section order fixed, ≤3 KB, no raw HTML/JSON/YAML in Answer, verb-blocklist before every Bash, commands verbatim in provenance.

## How it interacts with others

- `agents` — This is one specialized agent in the broader z-harness agent suite.
- `lookup-contract` — The agent must follow `docs/llm/lookup-contract.json`; that JSON contract is the canonical definition and wins over any conflicting inline prose.
- `multi-ide-exports` — The agent source is exported into downstream CLI surfaces (Codex AGENTS.md, Antigravity workflows, pi agents list) by the multi-IDE export pipeline.

## Edge cases / gotchas

- `WebFetch` 4xx/5xx responses become `STATUS: partial` with one fallback attempt (WebSearch or `gh api`) before giving up; there is no retry loop.
- Bash commands are checked against the verb-blocklist before execution — the blocklist is compiled once and tested against the joined argv string case-insensitively. A match produces `STATUS: refused` with `mutation_blocked`; the command is never sanitized and run.
- Authenticated endpoints without available secrets are refused as `auth_missing`; the agent must not sniff environment variables.
- Raw HTML, JSON, or YAML must not appear in `## Answer`; oversized raw material belongs in `z-harness/lookup-cache/<sha256>.raw` (gitignored; created with `mkdir -p` if absent).
- Provenance `commands:` entries are verbatim and never truncated in the provenance section. If verbatim commands push total response over 3 KB, the full response goes to the raw artifact pointer file.
- Tool allowlist includes `Grep` and `Glob` (for repo-local lookups) in addition to the four network tools — new since early versions of this agent.
- Pagination depth: WebSearch returns at most 10 results; WebFetch follows at most one link per source (original + one hop). Deeper pagination must be noted in `## Unresolved`.

## Examples

- A request for current library docs should use `WebSearch` or `WebFetch`, summarize under `## Answer`, cite URLs under `## Provenance`, and set a UTC `freshness_ts`.
- A request to run `curl -X POST ...` should return `STATUS: refused` with `Refused: mutation_blocked — matched pattern ...` instead of executing the command.
- A paginated API query that only covers the first page should return `STATUS: partial` and note pagination truncation in `## Unresolved`.
- A repo-local file lookup (e.g. inspecting `scripts/config.py`) should use `Read` or `Grep` and set `tools_used: Read` in provenance.
