**D1 — Agent Topology**

Failure mode: the split can drift, with `qt-market-lookup` re-solving generic retrieval behavior instead of only adding market-specific interpretation.  
Accept A, but require both agents to share the same output contract from D3/D8.  
Interaction: D3 becomes important because two agents need one stable return shape.

**D2 — Tool Whitelist For `external-lookup`**

Failure mode: Bash-only lookup may push the agent toward ad hoc `curl`/`jq` even when first-party web tools would be cleaner, and blocklists are easy to under-specify.  
Modify: use C, but with a strict Bash verb-blocklist and explicit "prefer WebSearch/WebFetch for public docs; use Bash for authenticated/local/CLI/API cases."  
Interaction: D8 must require commands run, so Bash usage is auditable.

**D3 — Output Contract Surface**

Failure mode: a standalone JSON contract can become stale if agent prompts evolve and nobody updates the artifact.  
Accept B, with a rule that agent markdown links to the contract and treats it as authoritative.  
Interaction: D1 and D8 both depend on this; without it, two agents plus structured output will diverge.

**D5 — Model Tier For `qt-market-lookup`**

Failure mode: Sonnet may be overkill for simple market listing or metadata lookup, adding cost/latency where Haiku would suffice.  
Accept Sonnet as the default for `qt-market-lookup`, especially for expiry, strike, payout, and settlement interpretation.  
Interaction: D8's confidence/unresolved ambiguity fields help justify Sonnet by forcing semantic judgment, not raw retrieval.

**D8 — Output Token Budget + Structure**

Failure mode: a structured envelope can become verbose and eat the entire 3 KB budget before the synthesis says anything useful.  
Modify C: fixed compact YAML header plus terse body, hard cap around 3 KB, with source IDs reused instead of repeated URLs.  
Interaction: D2's Bash commands and D3's contract fields need to be represented compactly, or the budget will fail under paginated API lookups.
