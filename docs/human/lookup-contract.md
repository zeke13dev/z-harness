# lookup-contract

> Last updated: 2026-05-25
> Covers source: agents/external-lookup.md

## Overview
The `lookup-contract` concept is the output envelope that the external lookup worker must return after fetching web docs, public API responses, paginated JSON, or other current information outside the main thread's context. It lives in `agents/external-lookup.md`, where the agent prompt defines the exact `STATUS` line, Markdown sections, provenance fields, budget, refusal modes, and edge-case behavior.

The contract keeps noisy retrieval predictable for orchestrators and other agents: every lookup result is a small, STATUS-headed Markdown synthesis with provenance and unresolved gaps separated from the answer. The JSON tier for this concept is the canonical fast-lookup contract; `agents/external-lookup.md` explicitly says `docs/llm/lookup-contract.json` wins if the inline prose ever conflicts.

## Key entry points
<!-- AUTO-START: entry-points -->
- `agents/external-lookup.md:1` — `external-lookup` — Agent metadata declares the lookup role, Haiku model, and tool allowlist.
- `agents/external-lookup.md:12` — `Output contract` — Defines the fixed `STATUS`-headed Markdown envelope and required sections.
- `agents/external-lookup.md:51` — `Verb-blocklist` — Lists regex patterns that force `STATUS: refused` before any Bash command runs.
- `agents/external-lookup.md:91` — `Budget` — Caps the total response at 3 KB and sends overflow to `z-harness/lookup-cache/<sha256>.raw`.
- `agents/external-lookup.md:99` — `Freshness discipline` — Defines `freshness_ts` as retrieval time and marks stale cache answers low confidence.
- `agents/external-lookup.md:137` — `Edge cases` — Specifies partial/refused handling for fetch failures, pagination, no results, and missing auth.
<!-- AUTO-END: entry-points -->
## How it interacts with others
- `agents` — The contract is authored inside the `external-lookup` agent prompt, so it follows the agent frontmatter/tooling conventions.
- `external-lookup-agent` — The external lookup agent consumes this contract on every response and must obey the JSON contract if it differs from inline prose.

## Edge cases / gotchas
- The first output line must be exactly `STATUS: <ok|partial|refused>` with no leading blank line.
- Section order is load-bearing: `## Answer`, `## Provenance`, `## Unresolved`, then optional `## Raw artifact pointer`.
- `## Answer` must summarize and cite; raw HTML, JSON, or YAML belongs in a raw artifact pointer, not the answer body.
- `refused` is only for mutation-blocked commands, out-of-scope requests, or missing auth; fetch failures and pagination gaps are `partial`.
- Bash commands must be checked against the verb-blocklist before execution and, if executed, recorded verbatim in provenance.
- `freshness_ts` is the retrieval timestamp in UTC, not a source document's last-modified time.
- Cache keys use the normalized query: lowercase, collapse internal whitespace, and trim leading/trailing whitespace.

## Examples
- A successful docs lookup begins with `STATUS: ok`, gives a concise synthesized `## Answer`, cites URL sections under `## Provenance`, records `freshness_ts`, and sets `## Unresolved` to `none`.
- A blocked mutating shell command returns `STATUS: refused`; the first line under `## Answer` is `Refused: mutation_blocked - matched pattern '<pattern>' in command '<verbatim cmd>'`.
- A rate-limited or paginated API lookup returns `STATUS: partial`, records the attempted source and commands in provenance, and explains the truncation or retry gap in `## Unresolved`.
