
The diff closely mirrors `/z-plan-light` structure. Key patterns to check:
- Setup steps 1-7 match (slug, RUN, mkdir, version stamp, fix_run_start event)
- Auto-bail thresholds identical (>5 files, >2 decisions, cross-module)
- Phase numbering and decision flow similar
- FIX.md schema similar but with "Hypothesis" and "Evidence" sections added (per `/z-fix` spec requirements)
- Codex review with retry-once policy
- No post-mortem in `/z-plan-light`; `/z-fix` adds optional post-mortem with auto-suggest logic

## Scrutinize rigorously

Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

OUTPUT BUDGET — respect strictly:
- Total response under 8000 characters
