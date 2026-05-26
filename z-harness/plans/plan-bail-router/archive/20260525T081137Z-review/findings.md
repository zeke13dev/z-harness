# Final review - plan-bail-router

Run: 20260525T081137Z-review
Base ref: HEAD working tree (uncommitted plan changes; scoped diff includes untracked additions)
Diff stats: 10,868 lines, 820,344 bytes; see `cumulative.stat`

## Prong A - Implementation Drift

### Severity: blocker

- [from codex] `/z-audit-plan` Phase 5 still contains imperative action wording that can violate read-only/contextual-only semantics.
  Evidence: Codex reported `commands/z-audit-plan.md` offers actions like "Proceed as-is" / "Reject & Re-plan" with wording that says to "start implementation" or "Discard current plan artifacts and rerun `/z-plan`."
  Recommendation: Convert those Phase 5 choices into route-decision handoffs or clearly say they are recommendations only; write `route-decision.md`, emit `plan_route_decision`, present switch/continue/abandon, and stop.
  One reason this might be wrong: the text may be intended as user-facing next-step advice, not an instruction for the agent to execute, but the wording is risky enough for a final-gate blocker.

### Severity: major

- [from codex] `/z-plan-split` route/archive setup may use `$Z_HARNESS_PLAN_DIR` before defining it.
  Evidence: Codex reported `commands/z-plan-split.md`, `skills/z-plan-split/SKILL.md`, and generated exports reference `$Z_HARNESS_PLAN_DIR/archive/$RUN/...` while setup only exports `Z_HARNESS_SLUG`.
  Recommendation: Define `Z_HARNESS_PLAN_DIR` through `scripts/plan-path.sh` during setup, then define `CURRENT_ARCHIVE_DIR` immediately after creating the run archive; regenerate exports.
  One reason this might be wrong: the runtime may already provide `Z_HARNESS_PLAN_DIR`, but exported prompts are intended to be standalone.

- [from codex] Most route blocks do not embed the required `route-decision.md` Markdown template.
  Evidence: SPEC requires `Recommendation`, `Reason`, `Signals`, `Route Chain`, and `Resume Context`; Codex reported only the lightweight blocks describe artifact content, while other command/skill blocks mostly say "write route-decision.md."
  Recommendation: Add the required route artifact headings/template to every canonical route block, then regenerate exports.
  One reason this might be wrong: agents can read SPEC/docs memory and infer the artifact structure, but exported prompts should not depend on hidden context.

- [from codex] `skills/z-plan/SKILL.md` and generated z-plan exports may still have stale existing-plan discovery compared with `commands/z-plan.md`.
  Evidence: Codex reported the command checks canonical `z-harness/plans/` plus legacy `z-harness/`, while the skill/export surfaces still mention only `ls z-harness/`.
  Recommendation: Sync skill source and exports with the command source for existing-plan discovery.
  One reason this might be wrong: this is adjacent setup behavior, not strictly inside the new route block, but it affects contextual existing-plan routing.

- [from gemini] Route blocks may not expose the stable `reason_codes` enum locally enough for deterministic route decisions.
  Evidence: Gemini reported route blocks emit `reason_codes` but may not include the stable enum list from SPEC.
  Recommendation: Embed or reference the stable reason-code enum in each route block, or include the subset relevant to the command.
  One reason this might be wrong: many route blocks do name concrete reason codes inline, and telemetry consumers may tolerate additional strings.

### Severity: minor

- [from gemini] Sentinel heading placement is inconsistent.
  Evidence: Gemini reported some files put `## Plan Route Check` outside `PLAN_ROUTE_CHECK_START/END`, while others put it inside.
  Recommendation: Standardize the heading inside the sentinel block for predictable extraction.
  One reason this might be wrong: validation only requires sentinel presence, and extractors may intentionally ignore headings.

## Prong B - Spec Gaps

### Severity: blocker

- None reported.

### Severity: major

- [from gemini] `planning-router` tool access conflicts with "no expensive repo sweeps."
  Evidence: SPEC/frontmatter grants `Read`, `Grep`, and `Glob` while also says the router should rely on compact signals and not sweep the repo.
  Recommendation: Either remove tools from `planning-router` or narrow the spec to allow only targeted reads and forbid broad searches.
  One reason this might be wrong: limited read/search tools can be useful for validating malformed inputs without becoming expensive exploration.

- [from gemini] The spec does not require an exact `planning-router` dispatch template.
  Evidence: SPEC defines required inputs, but route blocks can simply say "call `planning-router`."
  Recommendation: Add an exact subagent dispatch prompt/template with `current_command`, `task_or_topic`, `signals_json`, `route_chain_json`, and `repo_root`.
  One reason this might be wrong: local command files already contain many subagent call examples, so the orchestrator may infer the pattern.

- [from gemini | from codex] Route telemetry ordering/payload is underspecified.
  Evidence: Gemini flagged missing safe JSON construction for nested `signals`/`route_chain`; Codex flagged `user_choice` is required in telemetry before AskUser has returned.
  Recommendation: Specify either two events (`route_presented`, `route_choice`) or emit `plan_route_decision` after AskUser; provide a `jq -n` payload template.
  One reason this might be wrong: the numbered route contract may not be intended as strict execution order, and current log-event usage can still emit `not_asked` or later follow-up events.

- [from codex] No-plan `/z-audit-plan` archive path is not specified.
  Evidence: SPEC says `/z-audit-plan` artifacts live under `$BASE/archive/$RUN` where `$BASE=$Z_HARNESS_PLAN_DIR`, but no plan artifacts means no selected plan dir.
  Recommendation: Add a no-plan audit archive path such as `z-harness/archive/$NO_PLAN_RUN/route-decision.md` to SPEC.
  One reason this might be wrong: implementation already invented a reasonable no-plan archive location, but the contract should say so.

- [from codex] Route-chain handoff across commands is underspecified.
  Evidence: Loop prevention depends on carrying `route_chain`, but SPEC does not define how the next command receives the previous chain when switching from adhoc to slugged plan contexts.
  Recommendation: Add an explicit handoff mechanism, such as `--route-from <path>` or required pasted `Resume Context` in the next invocation.
  One reason this might be wrong: the AskUser handoff can rely on the user-visible route artifact, but loop prevention is weaker without a formal mechanism.

### Severity: minor

- [from gemini] `planning-router` returns comma-separated `REASON_CODES` while telemetry wants a JSON array.
  Evidence: The route contract requires `REASON_CODES: <comma-separated stable reason codes>`; telemetry requires `reason_codes` as a JSON array.
  Recommendation: Change router output to `REASON_CODES: [\"small_fix\", \"needs_research\"]` or specify the split/serialization step.
  One reason this might be wrong: parsing a comma-separated list into an array is straightforward, and current route blocks may handle it operationally.

## Consensus vs Disagreement

- Items both LLMs effectively flagged: telemetry/payload underspecification around route decision events.
- Items only Codex flagged: `/z-audit-plan` Phase 5 read-only risk, `/z-plan-split` setup variable drift, route artifact template incompleteness, existing-plan discovery drift, no-plan archive path, route-chain handoff.
- Items only Gemini flagged: stable reason-code enum local availability, sentinel heading placement, planning-router tool access, explicit router dispatch template, `REASON_CODES` comma-string mismatch.
