# Phase 7 — Final-review synthesis

For each finding: "one concrete reason it might be wrong" → accept/reject.

## Accepted (with SPEC/PLAN/TASKS impact)
- **Move agy research before agent rewrites.** Reason wrong: front-loads delay. Accepted — agy schema could force agent format changes; better to know first. Sequencing: agy research = phase 1 (parallel with foundation), agent rewrites stay at phase 5.
- **Exclude `exports/` from tarball; audit-lint script.** Both flagged. Add to bundle-plugin.sh excludes and add `scripts/audit-tarball.sh` lint as a release gate.
- **`Z_HARNESS_PLANS_DIR` override in PLAN.** Already addressed by user's SPEC edit; mirror to PLAN Phase 1 task.
- **`/z-update` dirty-tree pre-flight.** Already in SPEC edge cases; add explicit acceptance criterion in the install/update task.
- **Distinct-provider invariant: primary ≠ secondary, reviewer free.** Codex flagged ambiguity. Lock: `consultant_primary ≠ consultant_secondary` enforced by resolver; `reviewer` may equal either.
- **`resolve-provider.sh` requires jq or Python.** Implement as Python script `scripts/resolve-provider.py`; the `.sh` wrapper just `exec python3`s it. Same for `discover-providers.py` (already .py).
- **Merge depth = "per top-level key in providers map and per role"**, not field-level. Document explicitly in SPEC.
- **Dual-read warning de-dup.** Warn at most once per command run via env-guard.
- **Unbound role behavior = fail-fast** with actionable message.
- **Smoke-test acceptance criteria.** Minimum = automated JSON-schema / MDC syntax validation; manual IDE sign-off is release checklist (out of plan scope).
- **`provider_shadowed` event UX.** stdout warn line + jsonl event, non-fatal.
- **Path sweep via grep**, not hand-list (Codex). The TASKS task says "grep `z-harness/\\$Z_HARNESS_SLUG` and `z-harness/<slug>` across repo; update every hit".
- **Tarball versioning** = `version.sh` already produces this; append git short SHA + closest tag if present.
- **In-flight TASKS.md references to old agent names**: rename sweep also scans `z-harness/plans/**/TASKS.md` and `z-harness/**/TASKS.md` for the three deleted names and prints a one-shot migration nudge (no auto-edit).

## Rejected (with reason)
- **Combine Phase 2 + Phase 5 sweeps** (Gemini). Reason: combining makes one giant diff that's harder to review; the dispatch-name change is semantically separate from path relocation. Kept separate.
- **Docs-per-phase instead of all-at-end** (Codex). Reason: docs/llm/INDEX.json updates per phase add overhead; one final pass + `/z-maintain-docs` is sufficient. Each task that touches a doc-visible surface still gets a `**DOCS:**` flag for /z-maintain-docs to pick up later.
- **Neutral-schema source-of-truth** (Gemini, re-raised). Locked in user direction; stays Claude-canonical.

## SPEC additions (light) needed
- Note merge depth = top-level keys in `providers` and `roles` maps.
- Note `consultant_primary ≠ consultant_secondary` resolver-enforced; reviewer free.
- Note dual-read warning de-dup per command run.
- Note `provider_shadowed` is non-fatal warn.
- Note `audit-tarball.sh` lint gate.

(Light enough to live in TASKS.md acceptance criteria rather than a SPEC rewrite.)
