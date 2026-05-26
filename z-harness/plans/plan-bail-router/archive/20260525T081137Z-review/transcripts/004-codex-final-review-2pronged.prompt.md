Mode: final-review-2pronged

You are Codex performing the Codex-side final gate review for a z-harness plan.

Repo root: /Users/zeke/dev/z-harness
Plan slug: plan-bail-router
Base: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router
Review run: 20260525T081137Z-review
Base ref: HEAD working tree; changes are uncommitted. Base short message is recorded at /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/base-ref.txt

Inputs to read:
- SPEC: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/SPEC.md
- PLAN: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/PLAN.md
- TASKS: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/TASKS.md
- cumulative diff: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff
- cumulative stat: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.stat
- docs index: /Users/zeke/dev/z-harness/docs/llm/INDEX.json
- relevant concept docs: /Users/zeke/dev/z-harness/docs/llm/agents.json, /Users/zeke/dev/z-harness/docs/llm/commands.json, /Users/zeke/dev/z-harness/docs/llm/skills.json

Important context:
- The cumulative diff is a scoped working-tree diff, including untracked plan-critical additions as /dev/null diffs. Review the diff file, not only git status.
- The diff is large (~820k chars), so use focused read/search commands if needed.
- Treat this as a read-only review. Do not edit files.

Spec summary to check against:
- Add a shared routing policy for planning-family commands: /z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, /z-research.
- Contextual exits: /z-audit-plan, /z-fix, /z-debug, /z-amend, /z-maintain-docs.
- Every bail/recommend flow must write route-decision.md, emit plan_route_decision, present AskUser handoff unless terminal hard refusal, stop if switch, and preserve existing telemetry/run-end events.
- Route artifacts must contain Recommendation, Reason, Signals, Route Chain, Resume Context.
- Telemetry requires fields: from_command, to_command, route_class, reason_codes, signals, confidence, classifier_used, artifact_path, route_chain, user_choice.
- planning-router agent must be read-only/advisory, parseable status routed|ask_user|bad_input, distinguish primary vs contextual, detect loop risk, and avoid inventing facts.
- Add sentineled Plan Route Check sections to canonical command and skill sources for z-do, z-plan-light, z-plan, z-plan-split, z-brainstorm, z-research, z-audit-plan.
- Update docs/memory and regenerate Cursor/Codex/Antigravity exports.
- Invariants: no automatic cross-command execution; standalone exports; hard gates stay stricter; /z-research never recommends implementation approach inside RESEARCH.md; /z-audit-plan stays read-only; planning-router advisory only; existing telemetry preserved.

Known context snippets observed before invoking you:
- agents/planning-router.md exists with Read/Grep/Glob tools and model haiku; it says no shell commands, no edits, compact signals only, exact parseable return shape, and explicit contextual-exit preconditions.
- commands/z-plan.md has a route block after setup that recommends /z-do, /z-plan-light, /z-plan-split, /z-research, /z-brainstorm, contextual exits, route-decision.md, plan_route_decision, AskUser handoff, and loop prevention.
- commands/z-audit-plan.md now exists and states it is read-only, routes to /z-plan when no plan artifacts exist, stays in audit when artifacts exist, and routes to /z-amend or /z-maintain-docs after final report.
- One possible drift candidate noticed: skills/z-plan/SKILL.md setup still says "Run `ls z-harness/` to check for existing slug dirs" whereas commands/z-plan.md was updated to check canonical plans dir plus legacy. Decide whether this is actionable drift or harmless export/source mismatch.

Ask:
Run a final two-pronged review.

Prong A - Implementation faithfulness. Does the cumulative diff implement SPEC.md as written? List drift: files that should have changed but did not, changed files that do not match spec, cross-task drift, stale references, missing tests/assertions called out by acceptance.

Prong B - Spec correctness. Now that implementation exists, is the spec correct/sufficient? List spec gaps: wrong decisions, impossible invariants, missed edge cases, public surfaces too broad/narrow, categories of behavior not anticipated.

For every finding include exactly:
- severity: blocker | major | minor
- prong: A | B
- file/path if applicable
- evidence
- recommendation
- one reason the finding might be wrong

Prioritize concrete blockers and majors. If there are no findings for a prong, say none clearly. Do not include speculative low-value nits unless they could actually matter to the plan shipping.
