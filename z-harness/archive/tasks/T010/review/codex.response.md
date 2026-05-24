Codex review of agents/mr-reviewer.md Step 5 dismissal-pattern matching spec.

### Blockers
None.

### Major
1. **Text field mismatch (agents/mr-reviewer.md:244):** Step 5 normalizes current `detail` field, but extract-dismissals.py sources dismissed signatures from prior finding `title` snippets. This field mismatch may cause intended dismissal matches to fail silently. Specify that both should normalize the same field: either update the agent to normalize current `title` or modify extract-dismissals.py to normalize `detail` instead.

2. **Multiple match handling (agents/mr-reviewer.md:244-255):** The spec states "compare to each signature" and "on match: demote" without stopping, so one finding could match multiple dismissed signatures, get tagged multiple times, demoted multiple tiers, and counted multiple times in dismissal_pattern_matches. Define dismissal matching as a boolean: once any same-file/same-category signature reaches Jaccard ≥ 0.6, apply the tag and demotion once per finding.

3. **Empty union division by zero (agents/mr-reviewer.md:250-253):** Jaccard computation does not handle the case where stopword removal empties both token sets, resulting in division by zero. Specify that empty unions are not matches and the score defaults to 0.

---
Note: The Jaccard formula (set semantics, ≥ 0.6 threshold) and P0 protection are correctly specified. Ordering after consensus tier-bump is explicit. Empty dismissed_signatures.json case is handled (skip loop cleanly per Step 1 semantics).
