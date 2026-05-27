---
artifact: research
slug: askuser-prefs-hook
generated_at: 2026-05-27T21:10:00Z
command: /z-research "how do current z-harness AskUserQuestion call sites differ semantically — which are repeated routing-style prompts that the same user would answer the same way every time vs one-off scope decisions that genuinely vary per run? Enumerate every AskUserQuestion site across commands/ skills/ and agents/, classify each, and surface which sites would benefit from a stored-preference precheck hook." --slug=askuser-prefs-hook
input_hash: 224631744050b505
depends_on: []
explore_calls: 2
status: complete
---

# Research: AskUserQuestion call-site semantics — routing vs scope-novel vs error-recovery vs content-input

## Findings

### Inventory scale and shape
- **~270 raw `AskUserQuestion` occurrences** across `commands/`, `skills/`, and `agents/` per direct `grep -c` (Gemini's count). Phase 2 Explore A surfaced 169 distinct semantic mentions; the larger raw count includes references in prose-only spec text (rationales, hard-rules, gotchas) that don't represent independent gates.
- The 270 raw / 169 mentioned reduce to **~30 distinct semantic patterns** once near-duplicates and structural twins (`commands/<name>.md` ↔ `skills/<name>/SKILL.md` mirrors) are collapsed.
- Not every command has a skill mirror — `/z-amend`, `/z-audit`, `/z-uplift`, `/z-providers-discover` exist in `commands/` only and would be missed by mirror-based dedup ([z-amend.md](commands/z-amend.md), [z-audit.md](commands/z-audit.md), [z-uplift.md](commands/z-uplift.md), [z-providers-discover.md](commands/z-providers-discover.md)).
- Direct agent-level AskUserQuestion sites are rare. [agents/scope-reconciler-brainstorm.md:158](agents/scope-reconciler-brainstorm.md:158) and [agents/cluster-planner.md:213](agents/cluster-planner.md:213) reference it, but the cluster-planner mention is procedural guidance (return decisions one at a time to orchestrator), not an agent-owned interaction.

### Four-way classification of the 30 distinct patterns

**routing — stored preference would skip or pre-answer (~12 patterns):**
- Slug-derivation confirmation when auto-derived slug is non-obvious — same user almost always confirms ([z-plan.md:21](commands/z-plan.md:21), [z-fix.md:18](commands/z-fix.md:18), [z-debug/SKILL.md:17](skills/z-debug/SKILL.md:17), [z-brainstorm/SKILL.md:19](skills/z-brainstorm/SKILL.md:19), [z-research/SKILL.md:117](skills/z-research/SKILL.md:117), [z-plan-light/SKILL.md:19](skills/z-plan-light/SKILL.md:19), [z-uplift.md:71](commands/z-uplift.md:71))
- Existing-artifact handling (overwrite vs continue vs abort) — note: classification may be borderline; some users vary based on artifact age/source ([z-brainstorm/SKILL.md:23](skills/z-brainstorm/SKILL.md:23), [z-research/SKILL.md:119](skills/z-research/SKILL.md:119), [z-plan-split/SKILL.md:34](skills/z-plan-split/SKILL.md:34), [z-init-docs.md:14](commands/z-init-docs.md:14))
- Cost-confirmation gate — stable user cost tolerance ([z-research.md:92](commands/z-research.md:92))
- Synthesis/fix approval after clean prior step ([z-fix.md:130](commands/z-fix.md:130), [z-plan-light/SKILL.md:128](skills/z-plan-light/SKILL.md:128)) — Codex challenges: the same user may not approve identically when the synthesis varies in scope. Borderline routing.
- Flagged-shortcut approval ([z-fix.md:135](commands/z-fix.md:135), [z-plan-light/SKILL.md:133](skills/z-plan-light/SKILL.md:133), [z-plan.md:254](commands/z-plan.md:254))
- Approval gate before applying changes ([z-do/SKILL.md:131](skills/z-do/SKILL.md:131), [z-fix.md:241](commands/z-fix.md:241))
- Stale-docs gate before plan/uplift ([z-uplift.md:134](commands/z-uplift.md:134))
- Stale-research-citations gate ([z-plan.md:53](commands/z-plan.md:53))
- Skip-flagged-task halt ([z-implement-all/SKILL.md:262](skills/z-implement-all/SKILL.md:262))
- **Audit→Amend transition gate ([z-audit-plan.md:183-184](commands/z-audit-plan.md:183), [z-audit-plan-style.md:384-386](commands/z-audit-plan-style.md:384)) — this IS the canonical "I almost always amend after audit" site.** Both /z-audit-plan Phase 5 and /z-audit-plan-style Phase 5 present an AskUserQuestion with "Amend Plan (Run z-amend)" as one option. A stored preference `workflow.after_audit = "amend"` would skip these directly. The audit→amend friction the user named is *not* the absence of a gate; it's that the gate exists and is asked every time even when the answer is stable.
- Provider/role-binding prompts at `/z-providers-discover` ([z-providers-discover.md:32](commands/z-providers-discover.md:32), [z-providers-discover.md:50](commands/z-providers-discover.md:50)) — durable environment-level preference, not per-run.
- Plan-route-decision confirmation gates inside route-policy commands (write `route-decision.md`, emit `plan_route_decision`, then AskUser) ([z-plan-light/SKILL.md:60](skills/z-plan-light/SKILL.md:60))

**scope-novel — answer genuinely varies per run (~10 patterns):**
- Empty-arg input ("what task / symptom / fix / topic") at every top-level command entry
- Multi-candidate pick when N>1 ([z-implement-all/SKILL.md:37](skills/z-implement-all/SKILL.md:37) and ~6 sibling sites)
- Premise / concerns surface before proceeding
- Needs_clarification halt ([z-implement-all/SKILL.md:352](skills/z-implement-all/SKILL.md:352))
- Decision_needed halt (major design decision) ([z-implement-all/SKILL.md:354](skills/z-implement-all/SKILL.md:354))
- Per-candidate memory review (accept/edit/skip) loops at Phase 9/7/10 + `/z-suggest-memory`
- Per-stale-entry doc keep/refresh/drop/ignore ([z-maintain-docs/SKILL.md:187](skills/z-maintain-docs/SKILL.md:187))
- Mid-implementation scope-growth halt ([z-plan-light/SKILL.md:192](skills/z-plan-light/SKILL.md:192))
- Auditor blockers after review ([z-audit.md:501](commands/z-audit.md:501))
- Cross-LLM-disagreement surfacing ([z-test/SKILL.md:130](skills/z-test/SKILL.md:130))

**error-recovery — blast radius too high for auto-skip (~7 patterns):**
- Slug collision resolution ([z-plan.md:20](commands/z-plan.md:20))
- Spec_problem halt — stale references ([z-implement-all/SKILL.md:318](skills/z-implement-all/SKILL.md:318))
- No_change_on_retry halt ([z-implement-all/SKILL.md:380](skills/z-implement-all/SKILL.md:380))
- Reviewer second-failure halt ([z-implement-all/SKILL.md:389](skills/z-implement-all/SKILL.md:389))
- Test failure second-attempt halt ([z-implement-all/SKILL.md:460](skills/z-implement-all/SKILL.md:460), [z-do/SKILL.md:160](skills/z-do/SKILL.md:160), [z-plan-light/SKILL.md:221](skills/z-plan-light/SKILL.md:221), [z-fix.md:235](commands/z-fix.md:235))
- Auditor unable-to-complete (retry/skip/abort) ([z-audit.md:375](commands/z-audit.md:375), [z-uplift.md:1845](commands/z-uplift.md:1845))
- Tag collision resolution ([z-maintain-docs/SKILL.md:219](skills/z-maintain-docs/SKILL.md:219))

**content-input — free-text or multi-field collection (5+ patterns, undercounted in draft):**
- Test-runner template ([z-implement-all/SKILL.md:151](skills/z-implement-all/SKILL.md:151))
- New concept slug + memory fields ([z-suggest-memory/SKILL.md:126](skills/z-suggest-memory/SKILL.md:126), [z-suggest-memory/SKILL.md:208](skills/z-suggest-memory/SKILL.md:208))
- /z-debug clarifying-questions structured set ([z-debug/SKILL.md:48](skills/z-debug/SKILL.md:48))
- Base-ref free-text when fallback fails at /z-review-all ([z-review-all/SKILL.md:101](skills/z-review-all/SKILL.md:101))
- Audit-dimensions multi-select at /z-audit ([z-audit.md:343](commands/z-audit.md:343))

**state-machine repair (new sub-class surfaced by Codex critique, ~3 patterns):**
- Review-state fast-forward at `/z-review-all` ([z-review-all/SKILL.md](skills/z-review-all/SKILL.md) Pre-Phase 0)
- Maintain-docs audit state resume ([z-maintain-docs/SKILL.md](skills/z-maintain-docs/SKILL.md))
- Uplift component-implementation resume ([z-uplift.md:2433](commands/z-uplift.md:2433), [z-uplift.md:2532](commands/z-uplift.md:2532), [z-uplift.md:2603](commands/z-uplift.md:2603))
These are *resume policy* decisions, not pure routing — answer depends on state-file content and run history.

### Authority gradient inside `routing`
Within the routing class, two sub-classes emerge that justify different skip thresholds:
- **`skip`-eligible (5-6 patterns):** slug-derivation confirmation, flagged-shortcut approval, stale-docs gate, stale-research-citations gate, audit→amend transition, provider-role binding. User's answer is consistent AND blast radius of being wrong is reversible (slug renaming is cheap; amend can be reverted via git; provider rebinding is one command).
- **`prefill`-only (5-6 patterns):** existing-artifact overwrite, cost gate, synthesis/fix approval, approval-before-applying-changes, skip-flagged-task halt. User has a habitual answer but blast radius warrants confirmation.

### Patterns recurring identically across commands (best preference-resolver leverage)
- Slug-derivation confirmation appears in 7+ commands with identical option set — one stored pref skips all.
- Audit→Amend transition appears in BOTH /z-audit-plan and /z-audit-plan-style with the same option set ("Amend Plan", "Review and trim", etc.) — one preference (`workflow.after_audit = "amend"`) skips both.
- "Approval-before-applying" appears in 4+ commands with same option set.
- Test-failure-second-attempt appears in 4 commands — but classified error-recovery, not routing, so preferences are risky here.

## Constraints discovered

- **Markdown-not-code call sites.** AskUserQuestion sites are documented in natural-language skill specs that an LLM interprets at runtime, not as a function call with a stable signature. There is no central wrapper to retrofit. A precheck hook must therefore either: (a) be a convention every skill's prose explicitly invokes ("before AskUserQuestion, consult preference resolver"), or (b) live inside the AskUserQuestion tool itself at the harness layer.
- **Existing 4-layer TOML config is the natural home.** [scripts/config.py:238-389](scripts/config.py:238) already resolves built-in defaults → `~/.config/z-harness/config.toml` → `.z-harness/config.toml` → `Z_HARNESS_<SECTION>_<KEY>` env vars. Current keys: `notify.level`, `docs.always_apply`. Env transliteration is `Z_HARNESS_NOTIFY_LEVEL` (not bare `Z_HARNESS_NOTIFY`). Schema-extensible by adding a new section like `[workflow]`.
- **Plan-path canonicalization.** Plan paths use [scripts/plan-path.sh](scripts/plan-path.sh) with canonical layout `z-harness/plans/<slug>/` and a legacy fallback for `z-harness/<slug>/`. Any precheck hook that reads plan-level config must respect this resolver.
- **Memory authoring path is single-writer.** [`/z-suggest-memory`](commands/z-suggest-memory.md) is the sole memory-mutation path. No current consumer parses `memories[]` looking for routing directives (the narrower correct framing — consumers DO read LLM-tier docs and memory metadata for grounding/review). Gemini's framing recommendation that `/z-suggest-memory` should detect routing-preference text and redirect to `config.toml` is a v1 onboarding fix, not a memory-as-config-store move.
- **Stable site identity is hard.** A precheck-hook contract requires every AskUserQuestion site to have a stable identifier (so config can target `[workflow.audit-to-amend]`). Today sites are identified only by file:line in source, which drifts on every edit. Either spec sites adopt explicit `question_id` annotations (mechanical refactor across 30 patterns) or the resolver matches on prompt-text fingerprint (brittle when prose is edited).
- **Telemetry already partly exists.** `user_wait_start`/`user_wait_end` bracket-events are emitted around many AskUserQuestion calls. Specialized events also exist: `decision_gate`, `memory_review_terminal`, `plan_route_decision`. But coverage is uneven — no canonical `askuser_called` event, no question_id field, and not every site emits. Adding uniform telemetry is a prerequisite for evidence-based preference prioritization.
- **Cross-IDE export incompatibility.** The [scripts/export-cursor.py](scripts/export-cursor.py), [scripts/export-codex.py](scripts/export-codex.py), and [scripts/export-agy.py](scripts/export-agy.py) adapters rewrite `AskUserQuestion(...)` site mentions as limitation comments for Cursor/Codex/agy. A precheck hook only works in the Claude Code surface where AskUserQuestion actually fires. The other targets need either: pre-export resolution (resolver bakes prefs into exported prompts statically), or graceful degradation (preference resolution is a Claude-Code-only feature).
- **Flag-conditional prompts.** Many AskUserQuestion sites fire conditionally based on CLI flags (`--slug`, `--apply`, `--tasks`, `--retry-bailed`, `--components`). The presence/absence of a flag is already a kind of stored preference. A resolver layer that doesn't model flag interactions will mis-skip sites.
- **Safety-asymmetric halts.** Several "routing-class" prompts gate write authorization (apply doc refresh, apply amendments). Reversibility differs by site. A resolver must encode per-site blast radius, not treat all routing-class sites uniformly.

## Open questions

- **Question fingerprinting vs explicit IDs.** Do 7-10 of the 30 patterns give >80% preference-skip value? Without uniform `askuser_called` telemetry the question can only be answered by intuition. Adding telemetry is mechanically cheap (one-line event per site).
- **Per-project vs global breakdown.** Likely: slug-confirm and provider-binding prefs are global; doc-refresh, stale-research, and audit→amend prefs are per-project. Not verifiable from source alone.
- **What does "I almost always amend after audit" actually mean operationally?** Now that the audit→amend AskUserQuestion site is confirmed to exist ([z-audit-plan.md:183](commands/z-audit-plan.md:183), [z-audit-plan-style.md:384](commands/z-audit-plan-style.md:384)), the pref maps cleanly: a `workflow.after_audit = "amend"` config key would auto-select "Amend Plan" at these two sites. The user's specific complaint reduces to "skip this prompt, just amend." This is a *true* routing-class skip (no halt class, no scope-novel free-text).
- **Reversibility audit on auto-skip wrong-answers.** For audit→amend: blast = applied diffs committed by /z-amend (recoverable via git). For slug-confirmation: near-zero (slug is just a label). For approval-before-applying: blast = applied changes (recoverable). No site can cause irreversible damage if auto-skipped wrongly, but several have noisy undo cost.
- **Halt-class behavior under preference resolver.** Two halt classes (spec_problem, decision_needed) use AskUserQuestion and are error-recovery / scope-novel. Should the resolver expose a `bypass: true` config for users who want to auto-abandon on these? Probably v2.
- **Multi-IDE-export resolution model.** Should preferences resolve at export time (so Cursor users get prompts pre-answered statically) or only in Claude Code (so cross-IDE users get the prompt-style fallback)? Affects scope of the v1 ship.
- **The deliberately-skipped 3rd Explore was "existing default-handling patterns and ENV var precedence ladder."** Likely findings: detailed precedence chain inside [scripts/config.py](scripts/config.py) plus any existing `--yes` / `--no-confirm` flag conventions. Not consulted. May be relevant for v1 design if the precheck hook needs to interact with `config.py export-env`.

## Cross-LLM review notes

**Gemini surfaced (filled):**
- Raw site count corrected from 169 to ~270 occurrences. Distinct pattern count of ~30 unchanged.
- Telemetry partial-existence acknowledged (user_wait_start/end + specialized events).
- **Audit→Amend bridge correction (critical fix):** Both /z-audit-plan Phase 5 and /z-audit-plan-style Phase 5 DO have AskUserQuestion sites offering the amend transition. Verified at [z-audit-plan.md:183-184](commands/z-audit-plan.md:183) and [z-audit-plan-style.md:384-386](commands/z-audit-plan-style.md:384). Logged `research_temptation` event for the now-removed claim "no AskUserQuestion gates audit→amend." This reshapes the headline finding: the canonical user complaint maps directly to a routing-class skip-eligible site.
- Env var correction: `Z_HARNESS_PAUSE_AT_PCT` removed; `Z_HARNESS_NOTIFY` migrated to `notify.level` with env transliteration `Z_HARNESS_NOTIFY_LEVEL`.
- Multi-IDE-export incompatibility added as a constraint.

**Codex surfaced (filled):**
- Inventory undercount on /z-amend, /z-audit, /z-uplift, /z-review-all, /z-providers-discover, /z-improve — added to mentioned files; the 30-pattern collapse holds but coverage notes updated.
- Plan-path canonical layout (`z-harness/plans/<slug>/` via [scripts/plan-path.sh](scripts/plan-path.sh)) added as constraint.
- State-machine-repair sub-class added (z-review-all resume, z-maintain-docs resume, z-uplift component resume).
- Provider/role-binding flagged as durable environment-level preference (added to routing class).
- Cluster-planner.md mention is procedural, not actual agent-owned interaction (clarified in inventory).
- Memory-consumer framing tightened: "no consumer parses memories for routing directives" was too broad; corrected to the narrower accurate framing.
- Content-input undercount acknowledged — expanded from 4 to 5+ patterns.
- Flag-conditional prompts added as constraint (CLI flags are already a form of stored preference).

**Gemini surfaced (left as Open Question):**
- Telemetry uniformity gap — addressed as a constraint but not resolved here.
- Static-vs-runtime resolution model (pre-process .md files vs inject context vs harness-layer hook) — flagged in constraints, not picked.

**Codex surfaced (left as Open Question):**
- Multi-axis preference scope (user-global, repo-global, slug-local, run-local, provider-environment-local, artifact-state-local) — acknowledged in open questions; full axis-by-pattern mapping deferred to /z-brainstorm or /z-plan.

## No-recommendation

This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
