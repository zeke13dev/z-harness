# Final review — askuser-prefs-hook
Run: 20260527T223909Z-review
Base ref: HEAD (work uncommitted; diff = working tree against HEAD)
Diff stats: 36 files changed, 2019 insertions, 121 deletions

## Prong A — Implementation drift

### Severity: blocker

**A-1. skills/z-map/SKILL.md missing slug-confirm retrofit**
- *From: Gemini + Codex, verified.* Both consultants independently flagged.
- Verified: `grep -c "resolve-question workflow.slug_confirm" skills/z-map/SKILL.md` returns 0.
- SPEC lists `skills/z-research/SKILL.md:117` as a target site. The repo has renamed z-research → z-map at some prior point (visible in cumulative.stat: `skills/{z-research => z-map}/SKILL.md`). T009's implementer chased the SPEC reference, found no `skills/z-research/SKILL.md` source, and instead edited `.agent/skills/z-research/SKILL.md` (agy export — will be wiped on next `/z-export`).
- **Net effect:** One of the 7 advertised slug-confirm retrofit sites silently has NO resolver hook. Users will get unconditional AskUser prompts on `/z-map` invocations despite `workflow.slug_confirm` config.
- *One reason it might be wrong:* `/z-map` is a renamed (or possibly differently scoped) skill — maybe it doesn't have a slug-derivation step that warrants retrofit. **Verified:** z-map SKILL.md has the same Setup pattern with slug derivation and confirmation; it IS a valid target.
- **Fix:** Edit `skills/z-map/SKILL.md` to apply the same retrofit pattern. Update SPEC + scripts/config.py QUESTION_IDS callsite from `skills/z-research/SKILL.md:117` to `skills/z-map/SKILL.md:<line>`.

### Severity: major

**A-2. docs/llm/INDEX.json stale z-research references**
- *From: Gemini, verified.* INDEX.json:63 and :142.
- The `commands` concept entry lists `commands/z-research.md` (file doesn't exist). The `skills` concept entry lists `skills/z-research/SKILL.md` (renamed to z-map).
- *One reason it might be wrong:* INDEX may have been intentionally kept pointing at the old name for backward-compat. **Counter:** doc-fetcher uses these paths to discover concepts; stale entries mean concept misses.
- **Fix:** Replace both with `z-map` paths.

**A-3. docs/llm/config.json created but not registered in INDEX**
- *From: Gemini, verified.* No `slug: "config"` concept in INDEX (only the older `config-design`).
- T013 acceptance criterion said "Create the file if missing with proper INDEX.json registration." — registration was skipped.
- **Fix:** Add `config` slug entry to INDEX with appropriate `source_file` array (scripts/config.py, scripts/propose-prefs.py, docs/human/config.md) and `depends_on: ["scripts", "config-design"]`.

**A-4. scripts/config.py QUESTION_IDS callsites still reference `skills/z-research/SKILL.md`**
- *From: Gemini, verified.* The callsite list is metadata, not runtime-critical, but it's the documented source of truth for "what 9 sites" the resolver is wired into.
- **Fix:** bundled with A-1 fix.

### Severity: minor
- Two consultants flagged that the callsite list is unenforced documentation. Already acknowledged in SPEC §"Known v2 hygiene items."
- Codex flagged retrofit prose density (audit-plan conflict-handling bullet conflates 3 concerns) — cosmetic.

## Prong B — Spec gaps

### Severity: blocker
- (none)

### Severity: major

**B-1. T014 missing test for Z_HARNESS_ASK_ALL=1 + conflict-tier interaction**
- *From: Gemini (escalated CRIT) + Codex.*
- T014 acceptance criteria list smoke tests for: stdout discipline, config-explicit skip, conflict-tier, slug-confirm collision-check survives skip, proposer threshold. None explicitly test `Z_HARNESS_ASK_ALL=1` set while config+memory disagree.
- The implementation is correct (config.py:902-919 checks ASK_ALL first), but the test gap means a future optimization could break the override invariant silently.
- *One reason it might be wrong:* The implementation is verifiably correct via code read; an extra smoke test adds marginal value. **Counter:** override-precedence is a public contract; should be regression-protected.
- **Fix:** Add a 7th smoke test case to T014: set env ASK_ALL=1, write conflicting config + memory, verify result=ask + source=override.

**B-2. SPEC vague on `required` vs `optional` memory schema fields**
- *From: Codex.*
- SPEC §"Memory routing-preference schema" lists fields `{type, question_id, value, scope, strength, reason, date, project_root}` without distinguishing required vs optional. Code (config.py) defines `_ROUTING_PREF_REQUIRED_FIELDS = {"type", "question_id", "value", "scope", "strength"}` — `reason`/`date`/`project_root` are optional.
- *One reason it might be wrong:* SPEC said "missing required fields → malformed" which implies a required set exists; the imprecision is minor. **Counter:** v2 schema migrations will need a clearer contract.
- **Fix:** Mark fields in SPEC explicitly: required vs optional.

### Severity: minor
- B-3 (Gemini): callsites list is unenforced documentation — same point as A-4 minor; v2 hygiene.
- B-4 (Codex): suppression-file read/write interaction not explicitly tested in T014 (only proposer-output is tested, not the rejection-write-then-re-check cycle). v2 hygiene.
- B-5 (Codex): option-domain vs result-domain terminology mixing in retrofit prose — cosmetic clarity.

## Consensus vs disagreement

**Both LLMs flagged (high confidence):**
- A-1 (z-map missing retrofit) — verified
- A-2 (INDEX z-research stale) — verified
- A-3 (config.json not in INDEX) — verified

**Only Codex flagged:** B-2 (memory schema required-vs-optional clarity), B-4 (proposer suppression read/write interaction untested).

**Only Gemini flagged:** A-4 (callsites in code stale — sub-case of A-1), B-1 (Z_HARNESS_ASK_ALL+conflict test gap).

Both consultants converged on the rename-cascade (z-research→z-map) as the main blocker class. The other findings are spec-correctness gaps best resolved by SPEC amendments + one extra smoke test.

## Summary

- 1 Prong-A blocker (A-1)
- 3 Prong-A majors (A-2, A-3, A-4 — all rename-cascade or registration-skip)
- 2 Prong-B majors (B-1, B-2 — spec gaps)
- ~3 minors (callsites unenforced, prose density, schema clarity)
