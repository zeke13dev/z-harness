# Plan Review: lookup-subagent infra

## Goal
Implement two-tier lookup subagent infra:
- Generic `external-lookup` agent (z-harness, read-only, uses WebFetch/WebSearch)
- Domain-specific `qt-market-lookup` agent (qt-bot, read-only, uses Bash/Read/Grep)
- Shared output contract at `docs/llm/lookup-contract.json`

## SPEC highlights

### File 1: docs/llm/lookup-contract.json (NEW)
- slug: lookup-contract
- Invariants: STATUS first line in {ok, refused, partial}
- Fixed section order (## Answer, ## Provenance, ## Unresolved, optional ## Raw artifact pointer)
- No raw HTML/JSON in Answer section
- Mandatory provenance fields: query, tools_used, sources, freshness_ts, confidence
- Bash commands recorded verbatim
- Total size ≤3 KB

### File 2: agents/external-lookup.md (NEW)
- frontmatter: name=external-lookup, model=haiku, tools={WebFetch, WebSearch, Bash, Read, Grep, Glob}
- Verb-blocklist (enforced via grep-before-exec, not runtime):
  - DB writes: INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|VACUUM
  - Git mutations: git push|git commit|git reset --hard|git rebase --|git stash drop|git branch -D|git checkout --
  - GitHub mutations: gh pr create|gh pr merge|gh pr close|gh issue create|gh issue close|gh release create
  - HTTP mutations: curl (with -X|--request POST|PUT|DELETE|PATCH)
  - Eval/shell escapes: eval, sh <, pipes to sh, bash <
  - Filesystem destructive: rm -(rf|fr), >/dev/sd*
- Raw artifact overflow → z-harness/lookup-cache/<sha256>.raw (gitignored)
- Failure handling: WebFetch 4xx/5xx → STATUS:partial + one fallback; pagination >3 pages → truncate + note

### File 3: agents/qt-market-lookup.md (qt-bot, deposited via qt-bot-remote)
- frontmatter: name=qt-market-lookup, model=sonnet, tools={Bash, Read, Grep, Glob}
- Same envelope as external-lookup
- Additional trading verb-blocklist: place_order|cancel_order|trade|sell|buy(?!_?info)|withdraw|deposit|--execute|--submit; --real|--live|--mainnet under non-paper env
- Enrichment fields: symbol, title, expiry, payout schema, price, OI
- Stale cache → confidence: low

### Files 4-7
- INDEX.json modified to include lookup-contract entry
- lookup-contract.md added to human docs
- lookup-cache/.gitignore created
- README.md row added

## PLAN highlights

### Phases (ordered)
1. Create docs/llm/lookup-contract.json (output envelope spec)
2. Create agents/external-lookup.md (read-only web lookup agent)
3. Create z-harness/lookup-cache/.gitignore
4. Create agents/qt-market-lookup.md (authored+deposited via qt-bot-remote skill)
5. Update INDEX.json and human docs
6. Smoke tests

### Non-goals
- No hook for main-thread fetch ban
- No caching layer
- No z-export remote push
- No third agent

### Approved shortcuts
- Docs-only fetch ban (no runtime enforcement)
- Manual qt-bot deposit via qt-bot-remote

### Accepted risks
- Bash + web data attack surface (verb-blocklist is model-honored, not runtime-enforced)

---

## Review questions

1. Is the SPEC implementable end-to-end by a fresh-context implementer with no ambiguity?
2. Are the ordered phases in PLAN.md complete? Anything that needs to happen but isn't enumerated?
3. Is there a load-bearing assumption that's not stated (e.g., about how WebFetch behaves with auth headers, about how qt-bot's Kalshi client is invoked, about how docs/llm/INDEX.json entries are picked up)?
4. Anything else fragile.

Be terse and concrete.
