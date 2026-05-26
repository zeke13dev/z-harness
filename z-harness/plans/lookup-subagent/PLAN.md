# PLAN — lookup-subagent

## Goal

Cut main-thread token + context cost on repetitive external retrieval by introducing two subagents (z-harness's generic `external-lookup` + qt-bot's domain-specific `qt-market-lookup`) sharing one published output contract.

## Approved decisions

| ID  | Decision | Rationale |
|-----|----------|-----------|
| D1  | Two agents (`external-lookup` in z-harness + `qt-market-lookup` in qt-bot) | Matches z-harness's per-concern subagent convention; clean security boundary; qt-bot owns its own model tier + tools. |
| D2  | `external-lookup` whitelist = `WebFetch, WebSearch, Bash, Read, Grep, Glob` with verb-blocklist (user override after Gemini's exfiltration flag) | User values `gh api` / `jq` / authenticated `curl` flexibility over the tightest possible whitelist. Verb-blocklist mirrors `remote-runner` + adds web/git/eval/destructive patterns. |
| D3  | Contract lives in `docs/llm/lookup-contract.json` (canonical) + `docs/human/lookup-contract.md` (human) | Versioned, doc-fetcher-discoverable; agents cite it explicitly so drift is detectable. |
| D4  | `external-lookup` model: Haiku | Matches `doc-fetcher` / `remote-runner` precedent. |
| D5  | `qt-market-lookup` model: Sonnet (revisit after N runs) | Codex/Gemini both flagged Haiku as risky for market specifics. |
| D6  | Main-thread WebFetch ban: docs-only (best effort) | Building a hook is its own project. |
| D7  | Bash verb-blocklist: DB + git + gh + curl-mutate + eval + filesystem destructive | Mechanical extension of `remote-runner` pattern. |
| D8  | Output structure: `STATUS:` first line + Markdown sections (`## Answer`, `## Provenance`, `## Unresolved`, optional `## Raw artifact pointer`), total ≤3 KB | Mirrors `remote-runner` / `doc-fetcher` precedent; robust to LLM serialization noise. |
| D9  | Caching: disabled | Premature; re-evaluate with usage data. |
| D10 | qt-bot deposit: manual via `qt-bot-remote` skill | Extending z-export to push remote is real scope. |

## Non-goals

- Building a runtime hook to intercept main-thread WebFetch.
- Auto-deploying `qt-market-lookup` via z-export's existing pipeline.
- Designing a caching layer (deferred until usage justifies it).
- Adding a third agent for weather-only or NOAA-only lookup.
- Modifying the existing `doc-fetcher` or `remote-runner` agents.
- Authoring qt-bot's Kalshi client itself — only the agent file that wraps an existing client.

## Approved shortcuts (user-confirmed)

1. **No main-thread WebFetch hard-block.** Docs-only enforcement. Recovery cost if needed: build a hook later.
2. **Manual qt-bot deposit.** One-off scp via `qt-bot-remote` skill. Recovery cost if revisions become frequent: extend `z-export` to push remote.

## Ordered phases

1. **Contract first.** Create `docs/llm/lookup-contract.json` (canonical) + `docs/human/lookup-contract.md` (human-tier reference). Read existing INDEX.json to confirm schema, then add the `lookup-contract` entry.
2. **Generic agent.** Create `agents/external-lookup.md` with the full SPEC body (mission, output contract reference, tool guidance, verb-blocklist regex block, budget rules, freshness, refusal modes, provenance schema, confidence scale, edge cases).
3. **Generic agent's two-tier doc body.** Create `docs/llm/external-lookup-agent.json` (paired body for the INDEX entry, per the existing per-concept-JSON convention). Add the `external-lookup-agent` INDEX entry. If `docs/llm/agents.json` exists and is an agent registry, append an entry there too.
4. **README + cache dir scaffolding.** Add the `external-lookup` row to `README.md`. Create `z-harness/lookup-cache/.gitignore` (`*\n!.gitignore`).
5. **Domain agent staging.** Author `qt-market-lookup.md` locally under `z-harness/plans/lookup-subagent/staging/qt-market-lookup.md`. Use `<KALSHI_CLIENT>` and `<PAPER_ENV_VAR>` placeholders for fields that must be resolved on the remote host.
6. **Domain agent discovery + deposit.** Use the `qt-bot-remote` skill to: (a) inspect qt-bot's tree on `zeke-pc` and discover the agents-dir path, the Kalshi client invocation, and the paper-env var name; (b) substitute placeholders into the staged file; (c) scp the finalized file to the discovered remote agents dir; (d) static-verify on remote (file exists, frontmatter parses, `name:` equals `qt-market-lookup`). If discovery fails any check, halt deposit and surface to user.
7. **Static smoke tests (mechanical — no live API calls).** For both new agent files: frontmatter parses (YAML lints clean); all required sections present (`## Mission`, `## Output contract`, `## Tool guidance`, `## Verb-blocklist`, etc.); verb-blocklist regex block compiles as Python regex; contract JSON validates against the existing INDEX schema; `docs/llm/external-lookup-agent.json` has the same key set as a comparable existing per-concept JSON. **Defer any live API smoke test to a follow-up user-driven verification step** — it's not a fresh-context implementer task because it depends on environment + secrets.
8. **Docs freshness update.** Touch `last_updated` on every new/modified INDEX entry to the current run date. /z-maintain-docs run is NOT required since these are new concepts (not drift).

## How this plan respects DRY / KISS / SOLID

- **DRY:** contract lives in exactly one canonical location; verb-blocklist core is defined once in `external-lookup` and *extended* (not duplicated) by `qt-market-lookup`.
- **KISS:** zero new infrastructure. Uses existing agent file convention, existing two-tier docs convention, existing `qt-bot-remote` skill. No hooks, no runtime guards beyond the model-honored verb-blocklist.
- **SOLID (SRP):** each agent owns one concern (generic web vs. domain market). The contract owns the wire format.
- **SOLID (OCP):** contract is the closed interface; future agents (e.g. `weather-noaa-lookup`) plug in without touching it.
- **SOLID (ISP):** small contract with mandatory + optional fields. Consumers parse only what they need.

## Risks accepted

- Bash + untrusted web data is a meaningful attack surface; verb-blocklist is a model-honored convention, not a runtime guard. **Mitigation:** all Bash commands recorded verbatim in `## Provenance` so the user can audit retroactively. User accepted this risk explicitly in Phase 5.
- `qt-market-lookup` deposit is manual; contract drift can sneak in. **Mitigation:** the agent cites the contract slug; doc-fetcher can be asked to verify alignment.
- Main-thread WebFetch ban is best-effort. **Mitigation:** documented in `external-lookup.md`; user can add a `~/.claude/CLAUDE.md` rule themselves.
