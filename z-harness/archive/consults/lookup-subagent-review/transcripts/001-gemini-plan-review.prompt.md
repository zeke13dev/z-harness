# MODE: plan-review

You are reviewing a detailed plan for a lookup-subagent infrastructure. The plan defines a two-tier system (generic `external-lookup` in z-harness + domain-specific `market-lookup` in a trading/market repo) that both emit a standardized output contract. The critical constraint: Bash is included in the toolset WITH an LLM-honored verb-blocklist (no runtime enforcement).

## Key decision backstory
The user CHOSE to keep Bash + web tools together after being flagged on an exfiltration risk. The mitigation is a verb-blocklist (grep-before-exec pattern mirroring existing `remote-runner` approach in the codebase). The decision is final. **Your review should critique whether the verb-blocklist is actually exhaustive against the real attack surface.**

## SPEC summary (lookup-subagent)

### File 1: docs/llm/lookup-contract.json (NEW)
- Canonical machine-readable contract: STATUS first line + Markdown sections (Answer, Provenance, Unresolved, optional Raw artifact pointer)
- Invariants: STATUS in {ok, refused, partial}; no raw HTML/JSON in Answer; Provenance mandatory fields (query, tools_used, sources, freshness_ts, confidence)
- Body ≤3 KB total

### File 2: agents/external-lookup.md (NEW, Haiku)
- Tools: WebFetch, WebSearch, Bash, Read, Grep, Glob
- Output: same envelope as File 1
- Verb-blocklist (MANDATORY grep-before-exec):
  - DB writes: INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|VACUUM
  - Git mutations: git push|git commit|git reset --hard|git rebase --|git stash drop|git branch -D|git checkout --
  - GitHub mutations: gh pr create|gh pr merge|gh pr close|gh issue create|gh issue close|gh release create
  - HTTP mutations: curl[^|]*(-X|--request)\s*(POST|PUT|DELETE|PATCH)
  - Eval/shell escapes: \beval\b|\bsh\b\s*<|`\s*\|\s*sh\b|\bbash\b\s*<
  - Filesystem destructive: rm\s+-(rf|fr)\b|>\s*/dev/sd
- Raw artifact overflow (if response >3 KB) → lookup-cache/<sha256>.raw
- WebFetch 4xx/5xx → STATUS:partial + one fallback; pagination >3 pages → truncate + note unresolved

### File 3: agents/market-lookup.md (trading repo, Sonnet)
- Same envelope, PLUS trading-specific verb-blocklist extensions (order placement, account mutations, real-money operations)
- Domain enrichment: symbol, title, expiry, payout schema, price, OI

### Files 4–7 (supporting)
- docs/llm/INDEX.json (add lookup-contract + external-lookup-agent entries)
- docs/human/lookup-contract.md (human-tier reference)
- lookup-cache/.gitignore (for raw-artifact overflow)
- README.md (add external-lookup row to agents table)

---

## PLAN summary

**Ordered phases:** contract → external-lookup agent → cache dir → market-lookup (manual deposit) → smoke tests → docs update.

**Approved decisions (all final):**
- D2: Bash + verb-blocklist (user override after exfiltration flag)
- D7: Bash verb-blocklist = DB + git + gh + curl-mutate + eval + filesystem
- Output structure = STATUS line + Markdown sections, ≤3 KB total

**Accepted risks:** Bash + untrusted web data is meaningful attack surface; verb-blocklist is model-honored (not runtime-enforced); all Bash commands logged in Provenance for audit trail.

---

## Your review should critique:

### 1. Verb-blocklist exhaustiveness

Is the regex set actually sufficient to prevent shell injection attacks when an LLM receives untrusted web content?

- Are there obvious bypass vectors (shell metacharacters, alternate shell syntax, indirect mutations) not yet blocked?
- Is the curl regex strong enough? (Does it catch `curl | jq . | python -c eval(input())`?)
- Does the eval/shell escape regex catch all common injection vectors (heredoc, process substitution, command substitution)?
- Are there dangerous shell builtins (source, ., export, set, shopt, etc.) that should be blocked?
- Does the HTTP mutations regex handle all mutation methods (PATCH, OPTIONS, CONNECT, TRACE)?
- Is there a risk from piped commands where the first part is benign but pipes to a malicious second part?
- What about arguments that look innocent but contain code (e.g., `--arg '$(malicious)'`)?

### 2. Contract spec clarity

Would a fresh-context implementer encounter ambiguities?

- The "Bash commands recorded verbatim" — is there a clear truncation rule for long args (spec says ≤120 chars)?
- "Refused responses MUST give reason" — exact formatting of the reason (Answer section or separate field)?
- The ≤3 KB cap — measured with or without frontmatter/markdown overhead? Strategy if Answer naturally exceeds 2 KB?
- Raw artifact pointer format — file path, URL, or relative path?
- Pagination: "fetch first 3 pages max" — what defines a "page"? (APIs use pageNum, but WebFetch paginated HTML is ambiguous.)
- Confidence field — scalar (low/medium/high) or numeric range? The spec names it but doesn't define values.

### 3. Missing SPEC / gaps

- Is there a missing env-var or path resolution rule? The spec says "path resolved at deposit time" but no fallback if wrong.
- Schema for `## Provenance` section? The spec names fields (query, tools_used, sources, freshness_ts, confidence) but not Markdown structure (YAML block, table, bullet list?).
- The `lookup-cache/<sha256>.raw` pointer — should the SHA256 hash the query or response? If query, how are variations normalized?
- Missing rule for `STATUS: partial` vs `STATUS: refused`? The boundary is fuzzy (e.g., "API rate-limit hit" — which one?).

### 4. Fragility / other gaps

- The contract says "agent never reads contract JSON directly" — but how is the contract communicated at runtime? Pasted into prompt? Fetched via agent input? Fallback if fetch fails?
- Manual market-lookup deposit; spec says agents "cite the contract slug" for drift detection — but there's no automated check or lint rule.
- Provenance `commands:` field is truncated (≤120 chars per arg) — could hide injection attempts. Should full command be logged separately for audit?
- The `freshness_ts` field — is it the retrieval timestamp or the source's "last updated" timestamp? If web page says "updated 2025-01-15," which one goes in freshness_ts?
- Real-money gate (e.g., `ENV` check) — is this a shell-evaluated env var or hardcoded constant? If shell-evaluated, injection risk from agent's own env-var setting?

---

## Format

Respond with exactly three sections:

### Wrong
List specific claims / assumptions in the SPEC/PLAN that are incorrect or misleading.

### Missing
List specific things the SPEC/PLAN should define but doesn't (files, fields, rules, clarifications).

### Fragile
List specific design choices that feel fragile even if technically correct — high-risk, low-margin decisions, unclear recovery paths.

Do NOT recommend an alternative approach. This is a critique of the plan as written, not a design review. Be terse and concrete. Quote the SPEC when pointing to specific language that's unclear.
