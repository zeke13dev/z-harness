# Research: AskUserQuestion call-site semantics — routing vs scope-novel vs error-recovery vs content-input

## Findings

### Inventory scale and shape
- **169 distinct `AskUserQuestion` call sites** across `commands/`, `skills/`, and `agents/`. Many sites pair-mirror between `commands/<name>.md` and `skills/<name>/SKILL.md` (e.g., [z-plan-light.md:60](commands/z-plan-light.md:60) and [z-plan-light/SKILL.md:61](skills/z-plan-light/SKILL.md:61) describe the same gate).
- The 169 reduces to **~30 distinct semantic patterns** once near-duplicates and structural twins (commands/skills mirrors) are collapsed.
- Two agent files use `AskUserQuestion` directly: [scope-reconciler-brainstorm.md:158](agents/scope-reconciler-brainstorm.md:158) (framing selection) and [cluster-planner.md:213](agents/cluster-planner.md:213) (decision payload guidance). All other agents delegate user interaction back to their dispatcher.

### Four-way classification of the 30 distinct patterns

**routing — stored preference would skip or pre-answer (12 patterns, ~95 sites collapsed):**
- Slug-derivation confirmation when auto-derived slug is non-obvious — same person almost always confirms ([z-plan.md:21](commands/z-plan.md:21), [z-fix.md:18](commands/z-fix.md:18), [z-debug/SKILL.md:17](skills/z-debug/SKILL.md:17), [z-brainstorm/SKILL.md:19](skills/z-brainstorm/SKILL.md:19), [z-research/SKILL.md:117](skills/z-research/SKILL.md:117), [z-plan-light/SKILL.md:19](skills/z-plan-light/SKILL.md:19), [z-uplift.md:71](commands/z-uplift.md:71))
- Existing-artifact handling (overwrite vs continue vs abort): [z-brainstorm/SKILL.md:23](skills/z-brainstorm/SKILL.md:23) BRAINSTORM.md, [z-research/SKILL.md:119](skills/z-research/SKILL.md:119) RESEARCH.md, [z-plan-split/SKILL.md:34](skills/z-plan-split/SKILL.md:34) MANIFEST.md, [z-init-docs.md:14](commands/z-init-docs.md:14)
- Cost-confirmation gate (proceed/reduce/abandon) — stable user cost tolerance ([z-research.md:92](commands/z-research.md:92))
- Synthesis/fix approval after a clean prior step — users typically approve when the prior step completed cleanly ([z-fix.md:130](commands/z-fix.md:130), [z-plan-light/SKILL.md:128](skills/z-plan-light/SKILL.md:128))
- Flagged-shortcut approval (e.g., skip tests, accept shortcut) — stable per-user preference ([z-fix.md:135](commands/z-fix.md:135), [z-plan-light/SKILL.md:133](skills/z-plan-light/SKILL.md:133), [z-plan.md:254](commands/z-plan.md:254))
- Approval gate before applying changes ([z-do/SKILL.md:131](skills/z-do/SKILL.md:131), [z-fix.md:241](commands/z-fix.md:241))
- Stale-docs gate before plan/uplift ([z-uplift.md:134](commands/z-uplift.md:134) and the equivalent `/z-plan` Phase 0 gate; this is the audit→amend cousin)
- Stale-research-citations gate ([z-plan.md:53](commands/z-plan.md:53))
- Skip-flagged-task halt at `/z-implement-all` ([z-implement-all/SKILL.md:262](skills/z-implement-all/SKILL.md:262)) — user's policy on REMOTE/skip-marker tasks is typically stable
- Audit-result top-level action ([z-maintain-docs/SKILL.md:102](skills/z-maintain-docs/SKILL.md:102), [z-maintain-docs/SKILL.md:235](skills/z-maintain-docs/SKILL.md:235)) — **this is the canonical post-audit→amend bridge the user named**
- Doc-staleness route gate in /z-plan and /z-uplift Setup (mentioned in [commands.md](docs/human/commands.md) gotchas)
- Post-audit-plan next-step prompt — the canonical motivating example from BRAINSTORM ("I almost always amend after audit") — currently not actually a single AskUserQuestion site; `/z-audit-plan` exits with a recommendation rather than prompting

**scope-novel — answer genuinely varies per run; no stored pref can help (10 patterns, ~40 sites):**
- Empty-arg input "what task / symptom / topic / fix" ([z-plan.md:12](commands/z-plan.md:12), [z-fix.md:12](commands/z-fix.md:12), [z-debug/SKILL.md:13](skills/z-debug/SKILL.md:13), [z-brainstorm/SKILL.md:13](skills/z-brainstorm/SKILL.md:13), [z-do/SKILL.md:13](skills/z-do/SKILL.md:13), [z-test/SKILL.md:17](skills/z-test/SKILL.md:17), [z-improve.md:20](commands/z-improve.md:20), [z-research/SKILL.md:13](skills/z-research/SKILL.md:13))
- Multi-candidate pick when N>1 ([z-implement-all/SKILL.md:37](skills/z-implement-all/SKILL.md:37), [z-review-all/SKILL.md:61](skills/z-review-all/SKILL.md:61), [z-stats/SKILL.md:14](skills/z-stats/SKILL.md:14), [z-implement-next/SKILL.md:18](skills/z-implement-next/SKILL.md:18), [z-audit-plan/SKILL.md:43](skills/z-audit-plan/SKILL.md:43))
- Premise / concerns surface before proceeding — content is plan-specific ([z-plan.md:120](commands/z-plan.md:120), [z-plan-light/SKILL.md:75](skills/z-plan-light/SKILL.md:75), [z-do/SKILL.md:78](skills/z-do/SKILL.md:78), [z-uplift.md:537](commands/z-uplift.md:537), [z-fix.md:67](commands/z-fix.md:67))
- Needs_clarification halt ([z-implement-all/SKILL.md:352](skills/z-implement-all/SKILL.md:352))
- Decision_needed halt (major design decision) ([z-implement-all/SKILL.md:354](skills/z-implement-all/SKILL.md:354))
- Per-candidate memory review (accept/edit/skip) ([z-implement-all/SKILL.md:725](skills/z-implement-all/SKILL.md:725), [z-review-all/SKILL.md:508](skills/z-review-all/SKILL.md:508), [z-debug/SKILL.md:636](skills/z-debug/SKILL.md:636), [z-suggest-memory/SKILL.md:111](skills/z-suggest-memory/SKILL.md:111))
- Per-stale-entry doc action ([z-maintain-docs/SKILL.md:187](skills/z-maintain-docs/SKILL.md:187))
- Mid-implementation scope-growth halt ([z-plan-light/SKILL.md:192](skills/z-plan-light/SKILL.md:192))
- Auditor blockers after review ([z-audit.md:501](commands/z-audit.md:501))

**error-recovery — runtime artifact, blast radius too high for auto-skip (7 patterns, ~25 sites):**
- Slug collision resolution ([z-plan.md:20](commands/z-plan.md:20), [z-research/SKILL.md:116](skills/z-research/SKILL.md:116))
- Spec_problem halt — stale references ([z-implement-all/SKILL.md:318](skills/z-implement-all/SKILL.md:318))
- No_change_on_retry halt ([z-implement-all/SKILL.md:380](skills/z-implement-all/SKILL.md:380))
- Reviewer second-failure halt ([z-implement-all/SKILL.md:389](skills/z-implement-all/SKILL.md:389))
- Test failure second-attempt halt ([z-implement-all/SKILL.md:460](skills/z-implement-all/SKILL.md:460), [z-do/SKILL.md:160](skills/z-do/SKILL.md:160), [z-plan-light/SKILL.md:221](skills/z-plan-light/SKILL.md:221), [z-fix.md:235](commands/z-fix.md:235))
- Auditor unable-to-complete (retry/skip/abort) ([z-audit.md:375](commands/z-audit.md:375), [z-uplift.md:1845](commands/z-uplift.md:1845))
- Tag collision resolution ([z-maintain-docs/SKILL.md:219](skills/z-maintain-docs/SKILL.md:219))

**content-input — free-text or multi-field collection (4 patterns, ~9 sites):**
- Test-runner template collection ([z-implement-all/SKILL.md:151](skills/z-implement-all/SKILL.md:151))
- New concept slug free-text ([z-suggest-memory/SKILL.md:126](skills/z-suggest-memory/SKILL.md:126))
- Memory fields collection ([z-suggest-memory/SKILL.md:208](skills/z-suggest-memory/SKILL.md:208))
- /z-debug clarifying-questions structured set ([z-debug/SKILL.md:48](skills/z-debug/SKILL.md:48), [z-debug/SKILL.md:59](skills/z-debug/SKILL.md:59))

### Authority gradient inside `routing`
Within the routing class, two sub-classes emerge that justify different skip thresholds:
- **`skip`-eligible (5 patterns):** slug-derivation confirmation, flagged-shortcut approval, stale-docs gate, stale-research-citations gate, skip-flagged-task halt (with-confirmation). User's answer is consistent AND blast radius of being wrong is reversible.
- **`prefill-only`-eligible (7 patterns):** existing-artifact overwrite, cost gate, synthesis/fix approval, approval-before-applying-changes, audit-result top-level action, post-audit→amend bridge, skip-flagged-task halt. User has a habitual answer but blast radius warrants confirmation.

### The audit→amend bridge is structurally different
- `/z-audit-plan` and `/z-audit-plan-style` produce read-only REPORT.md / PLAN_STYLE_AUDIT.md and **exit with a recommended-next push-notify** ([z-audit-plan-style.md:78-89](commands/z-audit-plan-style.md:78-89) per BRAINSTORM scaffolding).
- `/z-amend` is a separate top-level command the user must invoke (Setup step 1 at [z-amend.md](commands/z-amend.md)).
- There is no AskUserQuestion site that asks "amend now?" after audit. The friction is the manual invocation + slug-discovery dance inside `/z-amend`, not a prompt that fires automatically.
- Implication: a preference-resolver hook before AskUserQuestion alone would NOT skip this case. The bridge needs either (a) `/z-audit-plan` to fire an AskUserQuestion at finalize, OR (b) `/z-amend` to auto-detect audit context from `$Z_HARNESS_PLAN_DIR` and pre-pin its slug.

### Patterns that recur identically across multiple call sites (best preference-resolver leverage)
- Slug-derivation confirmation appears in 7+ commands with identical option set ("yes" / "no, suggest alternative") — one stored pref skips all 7.
- "Approval-before-applying" appears in 4+ commands (z-do, z-fix, z-maintain-docs, z-uplift) with same option set.
- Test-failure-second-attempt appears in 4 commands with identical 3-option set ("Proceed anyway / patch manually / abandon task") — but classified as error-recovery, not routing, so preferences are risky here.
- Per-candidate memory review (accept/edit/skip) loops appear in 4 commands (Phase 9 / 7 / 10 / suggest-memory) — but candidate content varies, so this is scope-novel, not routing.

## Constraints discovered

- **Markdown-not-code call sites.** AskUserQuestion sites are documented in natural-language skill specs ([skills/](skills/), [commands/](commands/), [agents/](agents/)) that an LLM interprets at runtime, not as a function call with a stable signature. There is no central wrapper to retrofit. A precheck hook must therefore either: (a) be a convention every skill's prose explicitly invokes ("before AskUserQuestion, consult preference resolver"), or (b) live inside the AskUserQuestion tool itself at the harness layer ([skills/z-suggest-memory/SKILL.md:111](skills/z-suggest-memory/SKILL.md:111) doesn't expose hooks). Option (a) requires editing 169 sites or 30 distinct spec blocks; option (b) requires harness changes outside this repo.
- **Existing 4-layer TOML config is the natural home.** [scripts/config.py:238-389](scripts/config.py) already resolves built-in defaults → `~/.config/z-harness/config.toml` → `.z-harness/config.toml` → `Z_HARNESS_<SECTION>_<KEY>` env vars. Current keys: `notify.level`, `docs.always_apply`. Schema-extensible by adding a new section.
- **Memory authoring path is single-writer.** [`/z-suggest-memory`](commands/z-suggest-memory.md) is the sole memory-mutation path, guarded by validate-and-atomic-write to `docs/llm/<slug>.json`. A "memory says auto-amend after audit" pattern requires writing to memories — but no current consumer parses memories looking for routing directives.
- **Stable site identity is hard.** A precheck-hook contract requires every AskUserQuestion site to have a stable identifier (so config can target `[workflow.slug-derivation-confirm]`). Today sites are identified only by file:line in source, which drifts on every edit. Either spec sites adopt explicit `question_id` annotations (mechanical refactor across 30 patterns), or the resolver matches on prompt-text fingerprint (brittle).
- **No telemetry on which sites fire most.** No `askuser_called` event exists today. Without telemetry, prioritizing which patterns to wire first is guesswork. Adding telemetry is cheap (a one-line event emission per AskUserQuestion) but requires a one-time refactor of all 30 spec patterns to teach them to log.
- **Cross-LLM disagreement halt does not exist as a separate halt class.** [z-test/SKILL.md:130](skills/z-test/SKILL.md:130) handles disagreement via AskUserQuestion but it's a scope-novel surfacing, not a routing-class skipable.
- **Some "routing" gates have ENV opt-outs already.** [`Z_HARNESS_NOTIFY=off`](docs/human/config.md), [`Z_HARNESS_PAUSE_AT_PCT`](skills/z-implement-all/SKILL.md), [`Z_HARNESS_DOC_STALENESS_THRESHOLD`](skills/z-uplift/SKILL.md) — env vars for cross-cutting policy already exist. A `[workflow]` TOML section is a natural extension, but it must integrate with the env-var precedence ladder rather than duplicate it.

## Open questions

- **Question fingerprinting vs explicit IDs.** Of the 30 distinct patterns, do 7-10 give >80% of the preference-skip value? If yes, naming them by hand (`workflow.slug-confirm`, `workflow.flagged-shortcut`, `workflow.stale-docs-refresh`, `workflow.apply-doc-refresh`, `workflow.fix-synthesis-approval`) is cheap and avoids the question-fingerprint vs explicit-ID dilemma. Telemetry would answer "yes" definitively; without it this is a guess.
- **Per-project vs global breakdown.** Are these preferences typically global (slug-confirmation across all repos = yes) or per-project (apply-doc-refresh in qt-bot = yes, in this repo = no)? Not determinable from source alone. Likely answer: slug+approval-style prefs are global; doc-refresh/stale-research prefs are per-project.
- **What does "I almost always amend after audit" actually mean operationally?** Three interpretations: (a) "after `/z-audit-plan` exits, auto-invoke `/z-amend` with audit-context pre-filled" — no current AskUserQuestion gates this; needs a NEW gate or a script-level chain; (b) "the slug-discovery prompt at `/z-amend` Phase 0 should auto-select the slug whose audit just finished" — possible if `/z-amend` reads recent run telemetry; (c) "the final apply-amendments approval should default to Apply" — a true routing-pref skip. The user likely meant (a)+(b), not (c).
- **What happens when a precheck hook auto-skips a question and the wrong action is taken?** Reversibility audit: for slug-confirmation, near-zero blast (slug is just a label). For approval-before-applying, blast = applied diff (recoverable via `git`). For doc-refresh-now, blast = bulk doc rewrites (committable but noisy). No site can cause irreversible damage if auto-skipped wrongly, but several have meaningful undo cost.
- **Does explore-budget=3 → would-have-been-third-explore findings change the picture?** The deliberately-skipped third facet was "existing default-handling patterns and ENV var precedence." Likely findings would surface the [scripts/config.py:60-180](scripts/config.py) precedence ladder details and any existing `--yes` / `--no-confirm` flags. Not consulted here.
- **Halt-class behavior under preference resolver.** Two halt classes (`spec_problem`, `decision_needed`) explicitly use AskUserQuestion and are classified error-recovery / scope-novel. Should the resolver expose a `bypass: true` config for users who want to auto-abandon on these? Out of scope for v1 but a real question.

## No-recommendation

This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
