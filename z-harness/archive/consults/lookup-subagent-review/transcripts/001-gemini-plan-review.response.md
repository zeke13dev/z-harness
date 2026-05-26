Ripgrep is not available. Falling back to GrepTool.
### Wrong

*   **HTTP mutation regex is bypassable:** The regex `curl[^|]*(-X|--request)\s*(POST|PUT|DELETE|PATCH)` is incorrect because it misses implicit mutations, such as `curl -d "data"` or `curl -F "file=@..."` (which default to POST), as well as alternative binaries like `wget --post-data`.
*   **Eval/shell escape regex is inadequate:** The regex `\beval\b|\bsh\b\s*<|`\s*\|\s*sh\b|\bbash\b\s*<` misses standard command substitution (`$(...)` and `` `...` ``), process substitution (`<(...)`), and alternative interpreters (e.g., `curl url | python`, `perl -e`, `ruby -e`).
*   **Database blocklist assumptions:** The `INSERT|UPDATE|DELETE|DROP...` regex assumes SQL is passed plainly in shell arguments. It completely misses file-based executions (e.g., `psql -f malicious.sql`, `sqlite3 db < script.sql`) or simple destructive overwrites of local DB files (`> local.db`).

### Missing

*   **Provenance Schema:** The contract names mandatory fields (`query`, `tools_used`, `sources`, `freshness_ts`, `confidence`) but does not define their Markdown representation (e.g., YAML block, table, or bullet list).
*   **Field Definitions:** `confidence` lacks a defined scale (e.g., low/medium/high vs. 0.0-1.0). `freshness_ts` is completely ambiguous (does it represent the execution timestamp of the retrieval, or the parsed "last updated" date from the HTML?).
*   **Refusal Format:** The spec mandates "Refused responses MUST give reason" but does not define where or how that reason is structured when `STATUS: refused` is emitted.
*   **Cache Hashing Target:** For the `lookup-cache/<sha256>.raw` pointer, the plan does not define what string is actually being hashed (the user query, the source URL, or the raw payload data).
*   **Status Boundaries:** There is no defined boundary between `STATUS: partial` and `STATUS: refused` for transient failures (e.g., distinguishing between a 429 Rate Limit vs. a 403 Forbidden). 

### Fragile

*   **Haiku vs. Prompt Injection:** Relying on a smaller model (`external-lookup` using Haiku) to faithfully enforce an honor-system verb-blocklist against untrusted web data is highly susceptible to prompt injection attacks (e.g., a webpage instructing the model to ignore the blocklist).
*   **Audit Trail Truncation:** Truncating Bash arguments to "≤120 chars per arg" in the `Provenance` section actively destroys the auditability of the system by hiding the exact trailing payloads used in shell injections.
*   **Pagination Ambiguity:** The instruction to "fetch first 3 pages max" is extremely brittle for `WebFetch`, as HTML pages do not consistently define "pages" like REST APIs do. The model will guess or hallucinate the pagination boundary.
*   **Hard Size Caps:** The "≤3 KB total" constraint does not specify if it includes Markdown/Provenance overhead. A 2.9 KB `Answer` will randomly fail validation once `Provenance` is appended. 
*   **Manual Drift Detection:** Relying on external agents to manually "cite the contract slug" without automated, cross-repo validation ensures the two-tier contract will silently diverge over time.
