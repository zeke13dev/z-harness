## Review T003 (Round v2)

**Confirmed Fixed:**
- M1 fixed: `CROSS_CUTTING_SKIP=true` now explicitly stops Steps 1-7 and only runs the skip telemetry path.
- M3 fixed: entry-file fallback now preserves component root directories via `os.path.isdir(abs_ep)`.
- M4 fixed: `LICENSE`/`NOTICE` no longer match because fallback source candidates require known source extensions.
- M5 fixed: `G_COUNT`, `C_COUNT`, and `R_COUNT` are computed before the Step 6 `G_COUNT > 0` gate.
- M6 fixed: Step 6 parses dash-separated `key: value` segments independent of order.
- M7 fixed: MANIFEST insertion is now idempotent by updating an existing cross-slug row.
- M8 fixed: telemetry no longer uses `grep -c || echo 0`.

### Blockers
None.

### Major

1. **M2 only partially fixed: merge parser silently rejects valid consultant output without `G-NNN` prefixes.** Step 5's `extract_findings()` splits on `(?=^[-*]\s+(?:G|C|R)-\d+)` and only parses blocks matching `^[-*]\s+(G|C|R)-(\d+)`. The spec asks consultants to emit findings with explicit `component:` and `class:` fields; it does NOT require `G-001` pre-numbering. A finding like `- component: api — class: global-task — subject: drift` is silently dropped. This produces empty CROSS-CUTTING.md, suppresses synthetic plan creation, and violates "3 sections with component: markers" acceptance. Fix: split on any markdown bullet, then classify from explicit `class:` field first; treat `G/C/R` prefixes as optional fallback.

2. **Field parsing is not order-independent for inline one-line findings.** Step 5's regex `(?:^|\s){key}:\s*(.+?)(?:\n|$)` uses `\n|$` as terminator, so for `- G-001 — component: api — files: a, b — subject: drift`, the `component` regex captures `api — files: a, b — subject: drift` (stops only at end of line). This corrupts `files` and `subject`. Step 6 improved parsing, but Step 5 writes corrupted CROSS-CUTTING.md first, causing downstream parsing failures. Fix: parse by segmenting on ` — ` / ` - ` separators and match `key: value` per segment.

3. **Missing `class:` defaults incorrectly from prefix instead of to `per-component-context`.** V1 requirement was "missing classification defaults to `per-component-context`." The v2 code does `if prefix == "G": fields["class"] = "global-task" elif prefix == "R": fields["class"] = "risk"`. This means a consultant's `- G-001 — component: api — subject: issue` (no explicit class) becomes global-task even though the spec says unclassified defaults to per-component-context. This can incorrectly create synthetic plans and violate the 3-section intent. Fix: default missing `class` to `per-component-context` unconditionally.
