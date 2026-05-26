# Phase 3 — Decisions, post-consult

For each of the 5 consult-flagged decisions: one concrete "could be wrong" before accepting, then the final call.

---

## D1 — Agent topology

**Both consultants:** accept A (two agents).
**One way Codex might be wrong:** drift risk — `qt-market-lookup` might re-invent generic retrieval logic.
**Mitigation:** D3's shared contract is the synchronization point. Both agent files cite the contract as source-of-truth.
**Final: A — two agents, contract-synchronized.**

## D2 — Tool whitelist for `external-lookup`

**Disagreement.**
- Gemini: drop Bash entirely → option A (`WebFetch, WebSearch, Read, Grep, Glob`). Verb-blocklist on a shell handling untrusted web data is genuinely weaker than the `remote-runner` precedent (which handles trusted internal DB/log output). Concrete bypass: `eval`, `curl -d <exfil-payload>`, piping to `sh`.
- Codex: keep Bash with explicit preference rules + verb-blocklist → option B (or C).

**One way Codex might be wrong:** processing untrusted web content with shell access is materially different from `remote-runner`'s threat model. Verb-blocklists are easy to under-specify. The bypass vectors Gemini names are concrete.

**One way Gemini might be wrong:** WebFetch has known limits (auth headers, some content types, pagination quirks) — eliminating Bash may force ugly workarounds when `gh api` or `jq` would be one line.

**Final (user override): B — Bash kept with verb-blocklist.** Accept Gemini's flagged exfiltration risk as known; rely on the verb-blocklist mechanism mirroring `remote-runner` plus web-mutation patterns (`git push|git commit|gh pr create|gh issue close|curl.*(-X|--request)\s*(POST|PUT|DELETE|PATCH)`). The user values flexibility (`gh api`, `jq`, raw `curl GET`) over the tightest possible whitelist.

**Cross-decision:** D8's provenance section MUST capture the literal Bash commands run (not just "tools used"), so the user can audit any external-lookup invocation that touched shell.

## D3 — Output contract surface

**Disagreement.**
- Gemini: prose in `agents/external-lookup.md` (option A) — avoid over-engineering, agents are self-contained by convention.
- Codex: standalone `docs/llm/lookup-contract.json` (option B) — lynchpin for D1's drift prevention.

**One way Codex might be wrong:** another stale-tracked artifact in a `docs/llm/` that's currently 100% stale; adds maintenance.

**One way Gemini might be wrong:** the contract is the API between two agents in two repos. Embedding it in one agent file forces the other to read that whole file — tighter coupling and harder drift detection.

**Final: B (Codex).** Versioned contract = first-class artifact. `docs/llm/lookup-contract.json` becomes the canonical contract; both agents cite it explicitly. The "100% stale" docs concern is orthogonal — that's a separate maintenance gap. This new concept will start fresh.

## D5 — Model tier for `qt-market-lookup`

**Both:** accept Sonnet.
**One way both might be wrong:** Sonnet cost compounds on frequent market queries; Haiku might actually suffice for ticker discovery if the prompt is well-scoped.
**Mitigation:** make the tier a single-line frontmatter setting; downgrade trivially if metrics show Haiku would do.
**Final: Sonnet** (with explicit "re-evaluate after N runs" note in PLAN.md).

## D8 — Output budget + structure

**Disagreement.**
- Gemini: structured Markdown sections + ≤3 KB. LLM serialization is fragile under YAML/JSON.
- Codex: compact YAML header + terse body + ≤3 KB. Provenance demands structure.

**One way Codex might be wrong:** LLMs produce malformed YAML/JSON regularly (unescaped quotes, bad indentation). Orchestrator parsing fails → forced retries → cost.

**One way Gemini might be wrong:** Markdown section extraction still requires regex; not actually simpler than YAML at the parser layer for the orchestrator.

**Final synthesis: STATUS-line + Markdown sections, ≤3 KB.** Matches existing z-harness convention (`remote-runner` returns `STATUS: <token>` + raw body; `doc-fetcher` returns prose + file:line markers). Specifically:

```
STATUS: ok | refused | partial

## Answer
<≤500 word synthesis>

## Provenance
- query: <restated query>
- tools_used: <WebFetch | WebSearch | Read+Grep>
- sources: <list of url:section or path:line>
- freshness_ts: <ISO 8601 UTC of retrieval>
- confidence: <high | medium | low>

## Unresolved
- <ambiguities the orchestrator should know about>

## Raw artifact pointer (optional)
- <path to ./z-harness/lookup-cache/<hash>.raw if a big artifact was saved, else omitted>
```

Total ≤3 KB. STATUS line is the first machine-parseable token. Below it is structured Markdown — robust to LLM serialization noise.

---

## Final consult bundle decisions

| ID  | Final                                                                    | Changed from tentative? |
|-----|--------------------------------------------------------------------------|-------------------------|
| D1  | Two agents (contract-synchronized via D3)                                | no                      |
| D2  | `WebFetch, WebSearch, Bash, Read, Grep, Glob` (Bash + verb-blocklist)    | no (user override after consult flip) |
| D3  | `docs/llm/lookup-contract.json` as canonical                              | no                      |
| D5  | Sonnet (re-evaluate post-deploy)                                         | no                      |
| D8  | `STATUS:` header + Markdown sections + ≤3 KB                              | **YES** (was YAML/JSON envelope) |

## Shortcuts taken (require user approval in Phase 5)

- **No main-thread WebFetch hard-block** (D6, not consulted): documentation-only enforcement. Robust alternative: build a hook that intercepts WebFetch from main and routes through `external-lookup`. Cost of shortcut: relies on model honoring docs. Recovery cost: substantial — building a hook is its own project.
- **`qt-market-lookup` deposit is manual** (D10): user runs `qt-bot-remote` skill to scp the file to qt-bot's `.claude/agents/`. Robust alternative: extend `z-export` to push to a configured remote. Cost of shortcut: every contract revision requires a manual re-deploy.
