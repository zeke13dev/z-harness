MODE: bundled-decisions

## Context

I'm building a pre-AskUserQuestion preference resolver (v1 scope: audit→amend + slug-derivation retrofit across ~9 sites).

**Framing (from completed BRAINSTORM.md, chosen_framing: codex):**
- Typed question payload (not raw prose) with `{kind, choices, default, context}`
- 5-tier signal strength: `hard|strong|very_strong|weak|conflict`
- Config-first authority (TOML), memories as soft signal
- Two-level storage (global + per-project)

**Input artifact (decisions.md, Phase 2):**
Five consult-flagged decisions are presented below. Gemini has already reviewed and surfaced three cross-decision concerns:
1. D1 stdout pollution risk — config.py debug prints would corrupt JSON output
2. D3 should parse JSON files directly, not grep MEMORIES-FLAT.md
3. D2↔D3 ID synchronization — typos silently fail; needs enum validation

**Code reference:** config.py at scripts/config.py (lines 1-556) shows:
- Existing 4-layer loader: defaults → global ~/.config/z-harness/config.toml → repo-local .z-harness/config.toml → Z_HARNESS_<SECTION>_<KEY> env vars
- Subcommands: get, export-env, ensure-defaults, explain, should-notify (all work cleanly; no debug prints pollute stdout)
- VALIDATORS dict maps `notify.level` → {off, approval_only, all}; extensible

**Tier definitions (not flagged but interacts with D7):**
- hard (config explicit) → skip|prefill
- strong (repeated/explicit memory + low-risk) → prefill, surface
- very_strong (explicit "always X" memory + low-risk) → skip
- weak (vague memory) → prefill only, never skip
- conflict (config vs memory disagree, or project vs global disagree) → always ask, show sources
- none → ask

---

## The Five Consult-Flagged Decisions

### D1. Resolver entry point
**Tentative:** extend scripts/config.py with `resolve-question` subcommand.
**Alternatives:** standalone scripts/resolve-question.sh or .py.
**Premise:** This is a public CLI surface that every retrofitted AskUserQuestion site (~9 sites) will invoke; renaming later breaks all consumers.

### D2. Question_id naming
**Tentative:** `[workflow]` TOML section, dot-separated IDs (workflow.audit-to-amend, workflow.slug-confirm).
**Alternatives:** [askuser] with fingerprint keys; flat top-level keys.
**Premise:** Names a public surface; hard to rename later. Affects every retrofit edit.

### D3. Memory routing-preference schema
**Tentative:** new type "routing-preference" with {question_id, value, scope: global|project, strength: weak|strong|very_strong, reason}.
**Alternatives:** reuse lesson-learned with routing tag; separate ROUTING-PREFS.md.
**Premise:** Defines memory schema (public surface for /z-suggest-memory and the resolver). Hard to migrate later.

### D5. resolve-question return contract
**Tentative:** JSON on stdout — {result, default, source, rule_id, strength}.
**Alternatives:** key=value lines; exit-code-only.
**Premise:** This is a public wire format consumed by ~9 retrofitted call sites; renaming fields later breaks all consumers.

### D7. Memory strength heuristic
**Tentative:** explicit strength field on the memory, user picks at write time via /z-suggest-memory.
**Alternatives:** regex-infer from text patterns; count-based (3+ matching entries = strong, 1 = weak).
**Premise:** Defines memory-write semantics; affects the user's mental model.

---

## Ask

For each of the five consult-flagged decisions:

1. **Validate the tentative call or push back with a concrete alternative.** Is the tentative choice sound? Are the alternatives weaker, or is one better?
2. **Flag any interaction risks between decisions.** Which decisions depend on each other? Where could misalignment cause silent bugs?
3. **Surface any premise-level concerns about v1 scope.** Is the v1 scope (two patterns, ~9 sites) at risk from any decision's constraint?

In particular:
- **D1 stdout pollution (Gemini's flag):** Does extending config.py itself avoid the risk, or could subcommand output still leak prints? How to validate?
- **D3 memory parsing (Gemini's flag):** Is grepping MEMORIES-FLAT.md brittle? Should it parse `docs/llm/<slug>.json` memories arrays directly?
- **D2↔D3 ID sync (Gemini's flag):** What enum-validation pattern prevents a typo in TOML `workflow.audit-to-amend` from silently mismatching a memory with question_id="workflow.audit_to_amend"?
- **v1 viability:** With D7 using explicit user-chosen strength, is the v1 resolver sufficient (config-only hard tier + memory very_strong tier)? Or does v1 need to skip the memory tier entirely?

## Constraints from context

- AskUserQuestion sites are markdown prose (not function calls) — no function-call interception possible
- config.py already proven safe for stdout (subcommands tested; export-env specifically handles JSON consumers)
- Memory storage: `/z-suggest-memory` is sole writer; memories live in `docs/llm/<slug>.json` memories[] arrays (per Codex finding)
- Collision check must run even when memory says very_strong:skip (from premise requirement)
