# Z-harness retro: remote-control

**Run:** `/Users/zeke/.local/state/z-harness/hermes-agent-82be6e23/plans/remote-control/archive/20260630T003717Z-review`
**Date:** 2026-07-01
**Status:** draft — under discussion

## Run summary

`/z-review-all remote-control` resumed at Phase 4 and produced `REVIEW-TASKS.md` with two major drift findings and one escalation; `/z-execute --tasks REVIEW-TASKS.md` then completed T-REV-001 and dropped T-REV-002 by user decision. The feature shipped, but consultant/reviewer trust collapsed: both final consultants and the per-task reviewer ran degraded and emitted hallucinated citations/findings that had to be manually grounded.

## Friction observed

- **Silent consultant/reviewer proxy fallback:** `findings.md` records provider timeout/tooling constraints and Haiku proxy fallback; degraded answers still appeared as named Gemini/Codex/reviewer findings.
- **Hallucinated citations and blockers:** Codex cited `spawn.py:1483` for handlers at `spawn.py:543`; T-REV-001 reviewer claimed `getattr(event, "")` at nonexistent diff line 193 even though the diff used `getattr(event, "text", "")`.
- **Retry gate would trust degraded FAIL:** `/z-execute` Step 7 retries on any first-cycle blocker/major, so the false degraded FAIL would have triggered a wasted implementer retry without manual grounding.
- **Review-derived run brief approach failed:** `/z-review-all` used raw `findings.md` as run-brief approach input; `run-brief.sh` rejected file-path/file:line tokens that are normal in review findings.

## Proposed improvements

### Proposal 1: Add structured degraded-consult provenance to reviewer and consultant returns
- **Symptom:** Degraded proxy output was indistinguishable from normal provider output until a human noticed timeout/fallback prose.
- **Edit target:** `agents/reviewer.md`; `agents/consultant-primary.md`; `agents/consultant-secondary.md`
- **Proposed change:** After provider dispatch, classify degraded output using structured capture state first (`review_capture_fallback`, timeout/supervised-run failure, empty outfile fallback) and a conservative fallback-prose detector second. Log a `degraded_consult` event with `role`, `provider`, `reason`, `capture_mode`, and `artifact`; include stable metadata in non-RAW returns (`degraded_consult: true|false`, `degraded_reason: <enum>`). For RAW consultant modes, keep the raw provider body unchanged and rely on the archived event plus transcript metadata.
- **Why this helps:** The orchestrator can tell “real external reviewer verdict” from “proxy/advisory fallback” without rereading transcripts or trusting model self-description.
- **Risk:** Text-based fallback detection can misclassify; prefixing RAW modes can break downstream parsers, so RAW modes must use out-of-band metadata only.

### Proposal 2: Ground degraded reviewer FAILs before retrying in `/z-execute`
- **Symptom:** A hallucinated degraded reviewer blocker nearly caused an unnecessary cycle-2 implementer dispatch.
- **Edit target:** `skills/z-execute/SKILL.md` Step 7 (`Handle review outcome`) and Step 6 reviewer parsing notes.
- **Proposed change:** If the base reviewer response has blockers/majors and `degraded_consult: true`, run a bounded mechanical grounding check before the first-failure retry. The check should validate cited file existence, cited line/range or changed-file intersection, claimed symbol/text presence in `diff.patch` or changed files, and cited failing test/log presence; only grounded blocker/major findings are eligible to trigger retry. If none ground, log `degraded_review_advisory`, accept the implementation path to tests/Step 8, and surface the review artifact as advisory.
- **Why this helps:** Degraded reviews remain visible, but they cannot burn retries unless at least one concrete claim survives repository grounding.
- **Risk:** A purely mechanical check can miss real semantic bugs; the rule should downgrade only degraded reviews, not normal provider reviews.

### Proposal 3: Carry consultant trust through `/z-review-all` findings and promotion
- **Symptom:** Degraded consensus looked like cross-LLM consensus even though both answers came through the same low-trust fallback class.
- **Edit target:** `skills/z-review-all/SKILL.md` Phase 5 aggregation and Phase 6 promotion rules.
- **Proposed change:** Add per-finding `Trust:` labels (`grounded`, `single-degraded`, `degraded-consensus`, `ungrounded`) when building `findings.md`. Forbid auto-amend, blocker promotion, or `REVIEW-TASKS.md` promotion from degraded-only findings unless the orchestrator independently grounds them against diff/spec/tests; ungrounded degraded findings stay report-only or become follow-ups.
- **Why this helps:** Cross-LLM gates retain value when providers are healthy, but degraded fallback cannot masquerade as independent corroboration.
- **Risk:** Adds one manual/mechanical validation step to final review aggregation; if too vague, it becomes another subjective review pass.

### Proposal 4: Sanitize review run-brief approach bullets before `run-brief.sh set-section`
- **Symptom:** `/z-review-all` finalization errored because raw `findings.md` bullets contain legitimate file paths and file:line tokens.
- **Edit target:** `skills/z-review-all/SKILL.md` Phase 8 Run Brief finalize; optionally `scripts/run-brief.sh` approach validation.
- **Proposed change:** Prefer a generated `run-brief-approach-seed.md` for review runs instead of raw `findings.md`, with bullets such as “Cross-LLM final review against cumulative diff” and “Promoted N candidate review tasks”. Keep `run-brief.sh` validation strict for generic approach input.
- **Why this helps:** Review findings can keep precise citations while run-brief approach gets human-readable, schema-safe bullets.
- **Risk:** Sanitized bullets are less specific than raw findings; detailed evidence remains in `findings.md` and `REVIEW-TASKS.md`.

## Discussion log

- 2026-07-01: Primary consultant recommended adopting Proposals 1–3, with structured events/metadata, mechanical citation validation, and no promotion/auto-amend from degraded-only ungrounded findings. Secondary consultant request failed: `Request was aborted`.

## Decisions

_pending_
