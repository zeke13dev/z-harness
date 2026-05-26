Ripgrep is not available. Falling back to GrepTool.
### D1 — Agent topology
*   **Failure Mode:** Orchestrator confusion. The main thread struggles to decide which agent to call (e.g., using `external-lookup` to find market data), resulting in double-invocations or hallucinated tool attempts.
*   **Recommendation:** **Accept** (A).
*   **Cross-interaction:** Dictates D3 and D8. Because there are two agents, they must adhere to the exact same output structure so the orchestrator can parse them uniformly.

### D2 — Tool whitelist for `external-lookup`
*   **Failure Mode:** Regex-blocking Bash is notoriously brittle. An agent pulling external untrusted web data with access to `curl` can easily bypass read-only regex blocks (e.g., `curl -d`, `eval`, or piping to `sh`), creating a severe exfiltration risk.
*   **Recommendation:** **Modify** to A. Use managed, secure tools (`WebFetch`, `WebSearch`, `Read`, `Grep`, `Glob`) for generic external lookups. Do not give raw shell access to an agent processing raw web data.
*   **Cross-interaction:** If you drop Bash, D8's provenance envelope must track "tools and parameters used" rather than "commands run".

### D3 — Output contract surface
*   **Failure Mode:** Over-engineering and drift. Extracting a specific JSON contract requires the main thread to load an extra file or the subagents to drift from the standalone JSON schema. `z-harness` subagents are usually self-contained.
*   **Recommendation:** **Modify** to A. Document the contract in prose inside the agent's markdown file (`agents/external-lookup.md`).
*   **Cross-interaction:** Direct dependency on D8's chosen format.

### D5 — Model tier for `qt-market-lookup`
*   **Failure Mode:** High latency. Sonnet executing multi-step Kalshi pagination, reasoning, and data extraction will heavily block the main thread compared to Haiku.
*   **Recommendation:** **Accept** (Sonnet). The risk of Haiku misunderstanding complex financial schemas or payout rules is worse than the latency hit.
*   **Cross-interaction:** None directly.

### D8 — Output token budget + structure
*   **Failure Mode:** Brittle parsing. Forcing strict YAML/JSON envelopes risks syntax errors (e.g., unescaped quotes in summaries) that break the orchestrator's parser. Main thread LLMs extract data from Markdown just as efficiently without the syntax risk.
*   **Recommendation:** **Modify** to structured Markdown sections (e.g., `### Provenance`, `### Unresolved`, `### Summary`) with a strict ≤3 KB limit.
*   **Cross-interaction:** Simplifies D3, as a Markdown contract is much easier to define natively in the agent's prompt than enforcing strict JSON/YAML generation.
