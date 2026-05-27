# Phase 2 — Decisions

## D1. Resolver entry point: shell script vs Python module vs inline-in-config.py?
- **Options:**
  - A. New `scripts/resolve-question.sh` — bash wrapper that calls Python internally, returns stdout `skip|prefill|ask <default-option>|conflict <source-a>|<source-b>`
  - B. New `scripts/resolve_question.py` — invoked directly via `python3 scripts/resolve_question.py <question_id> [--json]`
  - **C. Extend `scripts/config.py` with a `resolve-question` subcommand**, reusing the existing 4-layer precedence ladder for free
- **Tentative call:** C. The 4-layer precedence is exactly what we need; duplicating it would violate DRY. `config.py` already knows env-var transliteration, TOML parsing, and slug-aware repo-local config.
- **Consult? YES.** Defines a public CLI surface that every retrofitted AskUserQuestion site will invoke; renaming later breaks ~9 site edits.

## D2. Question_id naming + namespace strategy
- **Options:**
  - **A. `[workflow]` section, dot-separated IDs.** Examples: `workflow.audit-to-amend`, `workflow.slug-confirm`. Maps cleanly to TOML keys like `workflow.audit_to_amend = "amend"`.
  - B. `[askuser]` section keyed by site fingerprint (e.g. `askuser.z-audit-plan-185 = "amend"`). Brittle — fingerprints break on prose edits.
  - C. Flat top-level keys (`audit_to_amend`, `slug_confirm`). Pollutes namespace; bad if config grows.
- **Tentative call:** A. Matches Claude framing's `[workflow]` suggestion and is the cleanest TOML shape.
- **Consult? YES.** Names a public surface; hard to rename later. Affects every retrofit edit.

## D3. Memory routing-preference schema (for the strong/very_strong/weak tiers)
- **Options:**
  - **A. New memory `type: "routing-preference"`** with required fields `{question_id, value, scope: "global|project", strength: "weak|strong|very_strong", reason}`. Resolver greps `docs/llm/MEMORIES-FLAT.md` for `[*] [routing-preference *]` entries on this question_id.
  - B. Use existing `type: "lesson-learned"` with a `routing` tag. Less explicit; risk of false-positive matches.
  - C. Separate file `docs/llm/ROUTING-PREFS.md` outside the memory system. Adds a fourth tier to docs/ layout.
- **Tentative call:** A. Memory types are already extensible; one new value is cheaper than a fourth doc tier. The required `question_id` field makes matching deterministic, not fingerprint-based.
- **Consult? YES.** Defines memory schema (public surface for /z-suggest-memory and the resolver). Hard to migrate later.

## D4. /z-suggest-memory routing-preference redirect mechanism
- **Options:**
  - **A. Detect at /z-suggest-memory Phase 3a** — when user's free-text or candidate JSON includes routing-flavored language ("always X after Y", "usually X"), surface a one-shot AskUserQuestion: "This looks like a routing preference. Write to .z-harness/config.toml [workflow] instead? (yes / write as routing-preference memory / write as lesson-learned anyway)"
  - B. Add a separate `/z-config-set` command and never touch /z-suggest-memory.
  - C. Make `/z-suggest-memory --kind=routing-preference` a separate flow; no auto-detection.
- **Tentative call:** A. Closes the user-confusion loop Gemini flagged in BRAINSTORM. Detection heuristic is simple (regex on text); user always has override.
- **Consult? NO.** Internal UX tweak inside /z-suggest-memory; reversible without breaking contracts.

## D5. resolve-question return contract (typed payload)
- **Options:**
  - **A. JSON on stdout** with shape `{"result": "skip|prefill|ask", "default": "<option-label>", "source": "config|memory|conflict|none", "rule_id": "<key>", "strength": "hard|strong|very_strong|weak|none"}`. Caller `jq -r .result` or parses fully.
  - B. Newline-separated lines: `result=skip\nsource=config\nrule_id=workflow.audit_to_amend`. Bash-parseable without jq.
  - C. Exit-code-only with stderr message. Limits expressiveness.
- **Tentative call:** A. JSON is the right shape for typed payload; `jq` is already a hard dep across z-harness scripts (used in run-memory-review.sh, log-event.sh consumers).
- **Consult? YES.** Public wire format consumed by ~9 retrofitted call sites; renaming fields later breaks consumers.

## D6. v1 question_id inventory (which sites get retrofitted)
- **Options:**
  - **A. Two patterns, ~9 sites total:**
    - `workflow.audit-to-amend` → 2 sites: z-audit-plan.md:183, z-audit-plan-style.md:384
    - `workflow.slug-confirm` → 7 sites: z-plan.md:21, z-fix.md:18, z-debug/SKILL.md:17, z-brainstorm/SKILL.md:19, z-research/SKILL.md:117, z-plan-light/SKILL.md:19, z-uplift.md:71
  - B. Audit→amend only (2 sites). Per Premise check this was an option; user picked "both".
  - C. Extend to existing-artifact handling and approval-before-applying. More sites, more risk.
- **Tentative call:** A. Matches user's Premise gate answer.
- **Consult? NO.** User already decided in Premise gate.

## D7. Memory consultation strength heuristics (mapping memory entries → tier)
- **Options:**
  - **A. Strength is recorded explicitly on the memory.** Resolver reads `strength` field directly from the routing-preference memory entry. User picks tier at memory-creation time via /z-suggest-memory question.
  - B. Resolver infers strength from text patterns ("always X" → very_strong, "usually X" → strong, "sometimes X" → weak). Brittle; LLM-dependent.
  - C. Strength is derived from count of matching memories (3+ matching entries = strong, 1 = weak). Requires counting.
- **Tentative call:** A. Explicit + user-chosen is least surprising. Matches the "structured contract" theme.
- **Consult? YES.** Defines memory-write semantics across /z-suggest-memory and the resolver; affects the user's mental model.

## D8. Conflict resolution: config vs memory disagreement
- **Options:**
  - A. Config always wins (hard tier always beats anything below it). Surface a one-line "config overrode your memory" notice.
  - **B. Surface as `conflict` tier — always ask, show both sources verbatim.** Most transparent; trains user to clean up the conflict.
  - C. Most recent wins (compare timestamps).
- **Tentative call:** B. Matches Gemini's "opaque automation is the risk to avoid" critique. The whole point of the 5-tier system is named transparency.
- **Consult? NO.** Internal resolver semantics; documented in /z-stats output. Reversible.

## D9. Per-project vs global storage layering
- **Options:**
  - **A. Inherit existing 4-layer precedence from config.py.** Global config (`~/.config/z-harness/config.toml`) provides defaults; repo-local (`.z-harness/config.toml`) overrides. No new layer.
  - B. New "per-slug" layer at `z-harness/<slug>/.workflow-prefs.toml`. Adds noise.
  - C. Per-project only — never read global config.
- **Tentative call:** A. Reuse existing infrastructure. Global is the right default for slug-confirm (user-level habit); per-project is the right default for audit-to-amend (project-policy). Both naturally fall out of A.
- **Consult? NO.** Reuses existing pattern; no novel surface.

## D10. Retrofitting strategy: explicit hook calls in prose vs implicit
- **Options:**
  - **A. Explicit prose convention.** Each retrofitted spec section adds a line: "Before AskUserQuestion, call `python3 scripts/config.py resolve-question workflow.audit-to-amend`. If result is `skip`, auto-select the default. If `prefill`, present with default pre-filled. If `ask`, normal."
  - B. Implicit — assume the orchestrator LLM reads config.toml on its own at runtime. Fragile.
  - C. Wrapper macro in skill prose: a `{{resolve_question:workflow.audit-to-amend}}` placeholder that a pre-processor expands. Adds build step.
- **Tentative call:** A. Most reliable; matches existing skill-prose conventions (commands already invoke `scripts/log-event.sh`, `scripts/version.sh` explicitly).
- **Consult? NO.** Following existing convention.

## D11. v1 telemetry — what events does the resolver emit?
- **Options:**
  - **A. Emit `askuser_resolved` event** with `{question_id, result, source, rule_id, strength}` whenever the resolver is invoked. Includes "asked" path (no skip) for baseline. Read by /z-stats Phase 4c (new).
  - B. Emit only on skip/prefill (silent on "ask"). Loses denominator.
  - C. No new events — rely on existing user_wait_start/end deltas.
- **Tentative call:** A. Denominator matters for measuring resolver effectiveness. One event per AskUser is cheap; ~9 sites × ~1 invocation each per run = trivial volume.
- **Consult? NO.** Following existing event-emission pattern.

## D12. Documentation surface for v1
- **Options:**
  - A. New concept `routing-preferences` (its own docs/human/ + docs/llm/ pair). Discoverable via INDEX.json.
  - **B. Extend existing `config` concept** with the `[workflow]` section. Keep memory-routing-preference under existing `review-agent` or `commands` concept.
  - C. Just inline in the relevant SKILL.md files.
- **Tentative call:** B. The config concept already exists and is the right home for new TOML stanzas. Keep doc surface stable.
- **Consult? NO.** Following existing doc convention.

## D13. CLI flag override
- **Options:**
  - A. `--ask-anyway` flag at each retrofitted command — bypasses the resolver for that one run.
  - **B. Single global env var `Z_HARNESS_ASK_ALL=1`** — bypasses resolver for the entire invocation.
  - C. Both.
- **Tentative call:** B. KISS. Per-command flags would need to be added to ~9 commands.
- **Consult? NO.** Reversible; cheap to add per-command later if needed.

---

## Consult-flagged decisions (5 within hard cap)
- D1 — resolver entry point (extend config.py)
- D2 — question_id naming + `[workflow]` namespace
- D3 — memory routing-preference schema
- D5 — resolve-question JSON return contract
- D7 — memory strength heuristic (explicit field)

## Obvious decisions (no consult)
- D4 (/z-suggest-memory redirect), D6 (v1 question_id list — user already picked), D8 (conflict tier behavior), D9 (storage layering), D10 (retrofit strategy), D11 (telemetry), D12 (docs surface), D13 (CLI flag override)
