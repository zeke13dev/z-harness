# lookup-contract

> Last updated: 2026-06-24
> Covers source: agents/external-lookup.md

## Overview
The `lookup-contract` concept defines the output envelope that the `external-lookup` Haiku subagent must return after fetching web docs, public API responses, paginated JSON, or library docs outside the main thread's training cutoff. It lives entirely in `agents/external-lookup.md`, where the agent prompt specifies the exact `STATUS` line, Markdown section order, provenance fields, 3 KB budget, verb-blocklist, refusal modes, confidence scale, freshness discipline, and edge-case behavior.

The contract keeps noisy retrieval predictable for orchestrators: every result is a small, STATUS-headed Markdown synthesis with provenance and unresolved gaps in fixed sections. The JSON tier (`docs/llm/lookup-contract.json`) is the canonical fast-lookup contract; `agents/external-lookup.md` explicitly states that `lookup-contract.json` wins on any conflict with the inline prose.

## Key entry points
<!-- AUTO-START: entry-points -->
- `agents/external-lookup.md:1` — `external-lookup` — Agent metadata declares the Haiku model, tool allowlist (WebFetch, WebSearch, Bash, Read, Grep, Glob), and lookup role.
- `agents/external-lookup.md:12` — `Output contract` — Defines the fixed STATUS-headed Markdown envelope: STATUS line, then `## Answer`, `## Provenance`, `## Unresolved`, optional `## Raw artifact pointer`.
- `agents/external-lookup.md:51` — `Verb-blocklist` — Python regex patterns tested case-insensitively before every Bash invocation; any match forces `STATUS: refused` and aborts execution.
- `agents/external-lookup.md:91` — `Budget` — Total response cap of 3 KB; overflow goes to `z-harness/lookup-cache/<sha256-of-normalized-query>.raw`.
- `agents/external-lookup.md:99` — `Freshness discipline` — `freshness_ts` is retrieval time in UTC ISO 8601, not the source's last-modified date; cache >24h old lowers confidence to low.
- `agents/external-lookup.md:105` — `Refusal modes` — Defines the three mutually exclusive STATUS values and the three refusal categories: `mutation_blocked`, `out_of_scope`, `auth_missing`.
- `agents/external-lookup.md:127` — `Confidence scale` — Three-value enum `{high, medium, low}` tied to source authority and corroboration.
- `agents/external-lookup.md:137` — `Edge cases` — Specifies partial/refused handling for fetch failures, pagination (depth ≤2, results ≤10), no results, and missing auth.
- `agents/external-lookup.md:144` — `Invariants` — Machine-checkable hard rules: STATUS first, fixed section order, 3 KB cap, no raw dumps, verbatim provenance.
<!-- AUTO-END: entry-points -->

## How it interacts with others
- `agents` — The contract is authored inside the `external-lookup` agent prompt and follows the agent frontmatter/tooling conventions defined by the `agents` concept. `agents.json` lists `lookup-contract` as a dependency.
- `external-lookup-agent` — The external-lookup agent is the sole implementor of this contract; every response it emits must conform to the STATUS-headed envelope defined here.

## Edge cases / gotchas
- The first output line must be exactly `STATUS: <ok|partial|refused>` with no leading blank line or extra tokens.
- Section order is load-bearing: `## Answer`, `## Provenance`, `## Unresolved`, then optional `## Raw artifact pointer`. Wrong order violates the contract.
- `## Answer` must synthesize and cite; raw HTML, JSON, or YAML belongs in the raw artifact pointer file, never in the answer body.
- `refused` covers only verb-blocklist matches, explicit mission-scope violations, and `auth_missing`; fetch failures and pagination gaps are `partial`, not `refused`.
- Bash commands must be checked against the verb-blocklist before execution and, if executed, recorded verbatim in provenance — never truncated in provenance (display-side truncation in `## Answer` is allowed with `...`).
- `freshness_ts` is the retrieval timestamp in UTC, not a source document's own last-modified date.
- Cache keys use the normalized query: lowercase, collapse internal whitespace, trim leading/trailing whitespace.
- Auth-required endpoints must refuse as `auth_missing`; do not attempt env-var sniffing for credentials.
- Pagination limits: WebSearch returns at most 10 entries; WebFetch link-follow depth is at most 2. Truncation must be noted in `## Unresolved`.

## Examples
- A successful docs lookup begins with `STATUS: ok`, gives a concise synthesized `## Answer`, cites URL sections under `## Provenance`, records `freshness_ts`, and sets `## Unresolved` to `none`.
- A blocked mutating shell command returns `STATUS: refused`; the first line under `## Answer` is `Refused: mutation_blocked — matched pattern '<pattern>' in command '<verbatim cmd>'`.
- A rate-limited or paginated API lookup returns `STATUS: partial`, records the attempted source and commands in provenance, and explains the truncation or retry gap in `## Unresolved`.
- A request to fetch from an authenticated endpoint without available credentials returns `STATUS: refused` with category `auth_missing`.
